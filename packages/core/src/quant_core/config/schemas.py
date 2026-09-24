"""Pydantic schemas for configs/ (accounts, agents, pipelines).

Stage-specific options (e.g. `aggregation`, `order_type`) are validated by the package that
owns the stage via `StageConfig.options(Model)`, keeping core free of business knowledge.
Risk-rule and schedule schemas live in the risk and scheduler packages for the same reason.
"""

from __future__ import annotations

import builtins
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from quant_core.llm.base import Effort
from quant_core.models.base import CoreModel, PositiveMoney
from quant_core.models.enums import RunMode
from quant_core.sizing import SizingConfig

SLUG = r"^[a-z][a-z0-9_]*$"

# Canonical stage types and their required relative order (spec §10.1).
CANONICAL_STAGE_ORDER = ("data_update", "sentiment", "decision", "risk", "trading")


class AgentRole(StrEnum):
    SENTIMENT = "sentiment"
    DECISION = "decision"
    RISK = "risk"


# Agents referenced by a canonical stage must have the matching role.
STAGE_AGENT_ROLE = {
    "sentiment": AgentRole.SENTIMENT,
    "decision": AgentRole.DECISION,
    "risk": AgentRole.RISK,
}


class OnError(StrEnum):
    ABORT = "abort"  # stop the run; later stages (incl. trading) never execute
    SKIP = "skip"  # record the error and continue


class AccountConfig(CoreModel):
    name: str = Field(pattern=SLUG)
    broker: str = "ibkr"
    account_id: str = Field(min_length=1)  # e.g. ${IBKR_ACCOUNT}
    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    client_id: int = Field(ge=0)
    base_currency: str = "USD"


class LLMModelConfig(CoreModel):
    provider: str = Field(default="anthropic", pattern=SLUG)  # key in configs/llm_providers.yaml
    name: str = Field(min_length=1)
    max_tokens: int = Field(default=2000, gt=0)
    # Current Claude models (Opus 5, Sonnet 5, ...) reject sampling params; leave unset there.
    temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    effort: Effort | None = None
    max_validation_attempts: int = Field(default=3, ge=1, le=10)


class LLMModelOverride(CoreModel):
    """Model settings given where agents are instantiated; unset fields keep the agent's
    own defaults (if it has any)."""

    provider: str | None = Field(default=None, pattern=SLUG)
    name: str | None = Field(default=None, min_length=1)
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    effort: Effort | None = None
    max_validation_attempts: int | None = Field(default=None, ge=1, le=10)


class AgentConfig(CoreModel):
    agent_id: str = Field(pattern=SLUG)
    role: AgentRole
    impl: str | None = None  # agent registry key; defaults to the role
    prompt_version: str = Field(min_length=1)
    # Optional default; normally the model is chosen where the agent is instantiated
    # (the `model` of a pipeline agent reference, or `Agent(..., model=...)` in code).
    model: LLMModelConfig | None = None
    persona: str = Field(min_length=1)
    prompt_template: str = Field(min_length=1)  # path relative to configs/agents/
    params: dict[str, Any] = Field(default_factory=dict)

    @property
    def registry_key(self) -> str:
        return self.impl or self.role.value


class AgentRef(CoreModel):
    agent: str = Field(pattern=SLUG)
    count: int = Field(default=1, ge=1, le=20)  # >1: independent instances, each its own UUID
    weight: float = Field(default=1.0, gt=0)
    model: LLMModelOverride | None = None  # which LLM these instances use


def resolve_model(agent: AgentConfig, override: LLMModelOverride | None) -> LLMModelConfig:
    """The agent's default model (if any) with the instantiation-time override applied."""
    base = agent.model.model_dump() if agent.model is not None else {}
    changes = override.model_dump(exclude_unset=True) if override is not None else {}
    try:
        return LLMModelConfig.model_validate({**base, **changes})
    except ValueError as exc:
        raise ValueError(
            f"agent {agent.agent_id}: no usable model; set `model: {{provider, name}}` where "
            f"the agent is instantiated (pipeline agent reference) or in the agent config ({exc})"
        ) from exc


class StageConfig(BaseModel):
    """Common stage fields; any extra keys are stage-specific options."""

    model_config = ConfigDict(frozen=True, extra="allow")

    type: str = Field(pattern=SLUG)
    enabled: bool = True
    on_error: OnError = OnError.ABORT
    agents: list[AgentRef] = Field(default_factory=list)

    # `builtins.type`: the `type` field above shadows the builtin inside this class body.
    def options[T: BaseModel](self, model: builtins.type[T]) -> T:
        """Validate this stage's full config (common + extra keys) against `model`."""
        return model.model_validate(self.model_dump())


class BudgetConfig(CoreModel):
    max_capital: PositiveMoney
    currency: str = "USD"


class PipelineConfig(CoreModel):
    name: str = Field(pattern=SLUG)
    mode: RunMode = RunMode.DRY_RUN
    account: str = Field(pattern=SLUG)
    universe: list[str] = Field(min_length=1)
    budget: BudgetConfig
    sizing: SizingConfig = Field(default_factory=SizingConfig)
    stages: list[StageConfig] = Field(min_length=1)

    @field_validator("universe")
    @classmethod
    def _normalise_universe(cls, value: list[str]) -> list[str]:
        symbols = [s.strip().upper() for s in value]
        if any(not s for s in symbols):
            raise ValueError("universe contains an empty symbol")
        dupes = sorted({s for s in symbols if symbols.count(s) > 1})
        if dupes:
            raise ValueError(f"duplicate symbols in universe: {dupes}")
        return symbols

    @model_validator(mode="after")
    def _check_stages(self) -> Self:
        types = [s.type for s in self.stages]
        dupes = sorted({t for t in types if types.count(t) > 1})
        if dupes:
            raise ValueError(f"duplicate stage types: {dupes}")

        enabled = [s.type for s in self.stages if s.enabled]
        canonical = [t for t in enabled if t in CANONICAL_STAGE_ORDER]
        if canonical != sorted(canonical, key=CANONICAL_STAGE_ORDER.index):
            raise ValueError(
                f"stages out of order: {canonical}; required order is {CANONICAL_STAGE_ORDER}"
            )
        # Fail-safe: never trade without a (non-skippable) risk stage in front of it.
        if "trading" in enabled:
            risk = next((s for s in self.stages if s.type == "risk" and s.enabled), None)
            if risk is None or enabled.index("risk") > enabled.index("trading"):
                raise ValueError(
                    "an enabled trading stage requires an enabled risk stage before it"
                )
            if risk.on_error is OnError.SKIP:
                raise ValueError(
                    "the risk stage may not use on_error: skip when trading is enabled"
                )
        return self

    def stage(self, stage_type: str) -> StageConfig | None:
        return next((s for s in self.stages if s.type == stage_type), None)
