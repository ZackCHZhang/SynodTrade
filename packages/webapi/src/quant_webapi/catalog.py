"""What the web editor needs to know about configs/: file kinds, option models and JSON schemas.

The option models are the very classes the stages validate with, so the editor's forms and
validation can never drift from what a run accepts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from quant_core.config import (
    CANONICAL_STAGE_ORDER,
    STAGE_AGENT_ROLE,
    AccountConfig,
    AgentConfig,
    AgentRole,
    LLMModelOverride,
    LLMProviderConfig,
    PipelineConfig,
)
from quant_core.models import RunMode, Timeframe
from quant_core.registry import AGENTS, CANDIDATE_SOURCES, SENTIMENT_SOURCES, STAGES
from quant_decision import DecisionOptions
from quant_market_data import DataUpdateOptions
from quant_risk import RiskStageOptions
from quant_risk.config import RiskRulesConfig
from quant_scheduler import JobConfig, SchedulesConfig
from quant_selection import IBKRScannerOptions, SelectionOptions, StaticSourceOptions
from quant_sentiment import SentimentOptions
from quant_sentiment.sources.ibkr_news import IBKRNewsOptions
from quant_sentiment.sources.reddit import RedditOptions
from quant_sentiment.sources.stocktwits import StocktwitsOptions
from quant_trading import TradingOptions

SLUG = r"^[a-z][a-z0-9_]*$"
PROMPT_NAME = r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$"


@dataclass(frozen=True, slots=True)
class ConfigKind:
    """One kind of file under configs/.

    `folder` kinds hold many files (`<folder>/<name><ext>`); `file` kinds are one file whose
    name is the kind itself. `key` is the field that must equal the file name.
    """

    name: str
    label: str
    folder: str | None = None
    file: str | None = None
    ext: str = ".yaml"
    key: str | None = None
    name_pattern: str = SLUG
    yaml: bool = True

    @property
    def single(self) -> bool:
        return self.file is not None


KINDS: dict[str, ConfigKind] = {
    k.name: k
    for k in (
        ConfigKind("pipelines", "流水线", folder="pipelines", key="name"),
        ConfigKind("agents", "Agent", folder="agents", key="agent_id"),
        ConfigKind(
            "prompts",
            "提示词模板",
            folder="agents/prompts",
            ext=".j2",
            name_pattern=PROMPT_NAME,
            yaml=False,
        ),
        ConfigKind("accounts", "账户", folder="accounts", key="name"),
        ConfigKind("risk", "风控规则", folder="risk", key="name"),
        ConfigKind("llm_providers", "LLM 供应商", file="llm_providers.yaml"),
        ConfigKind("schedules", "调度", file="schedules.yaml"),
    )
}

# Top-level schema per kind (what a whole file validates against).
KIND_MODELS: dict[str, type[BaseModel]] = {
    "pipelines": PipelineConfig,
    "agents": AgentConfig,
    "accounts": AccountConfig,
    "risk": RiskRulesConfig,
    "schedules": SchedulesConfig,
}

# Stage options, validated from the stage's full mapping (common keys + its own keys).
STAGE_OPTIONS: dict[str, type[BaseModel]] = {
    "selection": SelectionOptions,
    "data_update": DataUpdateOptions,
    "sentiment": SentimentOptions,
    "decision": DecisionOptions,
    "risk": RiskStageOptions,
    "trading": TradingOptions,
}
STAGE_COMMON_KEYS = ("type", "enabled", "on_error", "agents")

CANDIDATE_SOURCE_OPTIONS: dict[str, type[BaseModel]] = {
    "ibkr_scanner": IBKRScannerOptions,
    "static": StaticSourceOptions,
}
SENTIMENT_SOURCE_OPTIONS: dict[str, type[BaseModel]] = {
    "reddit": RedditOptions,
    "stocktwits": StocktwitsOptions,
    "ibkr_news": IBKRNewsOptions,
}


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema(mode="validation")


def catalog() -> dict[str, Any]:
    """Everything the editor's forms are generated from."""
    return {
        "kinds": [
            {
                "name": k.name,
                "label": k.label,
                "single": k.single,
                "ext": k.ext,
                "yaml": k.yaml,
                "key": k.key,
                "name_pattern": k.name_pattern,
            }
            for k in KINDS.values()
        ],
        "stage_order": list(CANONICAL_STAGE_ORDER),
        "stage_roles": {stage: role.value for stage, role in STAGE_AGENT_ROLE.items()},
        "agent_roles": [r.value for r in AgentRole],
        "run_modes": [m.value for m in RunMode],
        "timeframes": [t.value for t in Timeframe],
        "registry": {
            "stages": STAGES.names(),
            "agents": AGENTS.names(),
            "sentiment_sources": SENTIMENT_SOURCES.names(),
            "candidate_sources": CANDIDATE_SOURCES.names(),
        },
        "schemas": {
            "pipeline": _schema(PipelineConfig),
            "agent": _schema(AgentConfig),
            "account": _schema(AccountConfig),
            "risk": _schema(RiskRulesConfig),
            "llm_provider": _schema(LLMProviderConfig),
            "llm_model": _schema(LLMModelOverride),
            "schedules": _schema(SchedulesConfig),
            "job": _schema(JobConfig),
            "stages": {name: _schema(model) for name, model in STAGE_OPTIONS.items()},
            "candidate_sources": {
                name: _schema(model) for name, model in CANDIDATE_SOURCE_OPTIONS.items()
            },
            "sentiment_sources": {
                name: _schema(model) for name, model in SENTIMENT_SOURCE_OPTIONS.items()
            },
        },
        "stage_common_keys": list(STAGE_COMMON_KEYS),
    }
