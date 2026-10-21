"""Agent base class: persona + Jinja2 prompt + LLM config -> validated structured output."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from jinja2 import FileSystemLoader, StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel

from synodtrade_core.config.schemas import AgentConfig, LLMModelConfig
from synodtrade_core.llm.base import LLMClient, LLMMessage, LLMRequest
from synodtrade_core.llm.recorder import LLMCallRecorder
from synodtrade_core.llm.structured import complete_structured


@dataclass(frozen=True, slots=True)
class AgentResult[T: BaseModel]:
    output: T
    call_ids: list[UUID] = field(default_factory=list)
    error: str | None = None  # set when `output` is the fallback, not the model's answer

    @property
    def fallback_used(self) -> bool:
        return self.error is not None


class Agent[T: BaseModel](ABC):
    """Subclasses set `output_model` and implement `fallback_output` (e.g. HOLD).

    The LLM is chosen at instantiation: `llm` is the provider client and `model` the model
    settings (falling back to the agent config's optional default). Each instance has its
    own `instance_id`; several instances of one configured agent (count > 1) are independent
    and distinguishable in the database, and may even use different models.
    """

    output_model: type[T]

    def __init__(
        self,
        config: AgentConfig,
        llm: LLMClient,
        *,
        model: LLMModelConfig | None = None,
        prompt_root: Path,
        recorder: LLMCallRecorder | None = None,
        instance_id: UUID | None = None,
    ) -> None:
        self.config = config
        resolved = model or config.model
        if resolved is None:
            raise ValueError(f"agent {config.agent_id}: no model given and none configured")
        self.model = resolved
        self.instance_id = instance_id or uuid4()
        self._llm = llm
        self._recorder = recorder
        env = SandboxedEnvironment(
            loader=FileSystemLoader(prompt_root),
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )
        self._template = env.get_template(config.prompt_template)

    @property
    def agent_id(self) -> str:
        return self.config.agent_id

    @property
    def prompt_version(self) -> str:
        return self.config.prompt_version

    @abstractmethod
    def fallback_output(self, inputs: Mapping[str, Any], error: str) -> T:
        """The safe output used when the LLM fails or never returns valid output."""

    def render_prompt(self, inputs: Mapping[str, Any]) -> str:
        return self._template.render(**inputs)

    def build_request(self, inputs: Mapping[str, Any]) -> LLMRequest:
        model = self.model
        return LLMRequest(
            model=model.name,
            system=self.config.persona,
            messages=[LLMMessage(role="user", content=self.render_prompt(inputs))],
            max_tokens=model.max_tokens,
            temperature=model.temperature,
            effort=model.effort,
        )

    async def invoke(
        self,
        inputs: Mapping[str, Any],
        *,
        run_id: UUID | None = None,
        output_model: type[T] | None = None,
    ) -> AgentResult[T]:
        """Render, call the LLM, validate. `output_model` may narrow `self.output_model` for
        one call (e.g. a subclass whose validators depend on this call's inputs); invalid
        replies go through the usual repair retries."""
        try:
            request = self.build_request(inputs)
        except TemplateError as exc:
            # A broken template is a configuration bug, not an LLM failure: surface it.
            raise ValueError(f"agent {self.agent_id}: cannot render prompt: {exc}") from exc

        result = await complete_structured(
            self._llm,
            request,
            output_model or self.output_model,
            max_attempts=self.model.max_validation_attempts,
            recorder=self._recorder,
            run_id=run_id,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
        )
        if result.output is not None:
            return AgentResult(result.output, result.call_ids)
        error = result.error or "unknown LLM failure"
        return AgentResult(self.fallback_output(inputs, error), result.call_ids, error)
