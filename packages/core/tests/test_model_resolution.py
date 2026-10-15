"""The LLM model is chosen where agents are instantiated; agent configs only give defaults."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from quant_core.agent import Agent
from quant_core.agent_factory import instantiate_agents
from quant_core.config import (
    AgentConfig,
    AgentRef,
    AgentRole,
    ConfigError,
    ConfigStore,
    LLMModelConfig,
    LLMModelOverride,
    PipelineConfig,
    resolve_model,
)
from quant_core.llm import FakeLLMClient, LLMClientPool


class Out(BaseModel):
    ok: bool


class Simple(Agent[Out]):
    output_model = Out

    def fallback_output(self, inputs: Any, error: str) -> Out:
        return Out(ok=False)


def agent_config(model: dict[str, Any] | None) -> AgentConfig:
    data: dict[str, Any] = {
        "agent_id": "value_investor",
        "role": "decision",
        "prompt_version": "v1",
        "persona": "p",
        "prompt_template": "prompts/test_v1.j2",
    }
    if model is not None:
        data["model"] = model
    return AgentConfig.model_validate(data)


def test_override_only_changes_given_fields() -> None:
    cfg = agent_config({"provider": "anthropic", "name": "claude-opus-5", "max_tokens": 900})
    assert resolve_model(cfg, None) == cfg.model
    model = resolve_model(cfg, LLMModelOverride(provider="deepseek", name="deepseek-chat"))
    assert (model.provider, model.name, model.max_tokens) == ("deepseek", "deepseek-chat", 900)


def test_agent_without_default_needs_a_model_at_instantiation() -> None:
    cfg = agent_config(None)
    model = resolve_model(cfg, LLMModelOverride(provider="deepseek", name="deepseek-chat"))
    assert model.max_tokens == 2000  # LLMModelConfig default
    with pytest.raises(ValueError, match="no usable model"):
        resolve_model(cfg, None)
    with pytest.raises(ValueError, match="no usable model"):
        resolve_model(cfg, LLMModelOverride(provider="deepseek"))  # name missing


def test_override_validation() -> None:
    with pytest.raises(ValidationError):
        LLMModelOverride.model_validate({"name": "x", "colour": "red"})
    with pytest.raises(ValidationError):
        AgentRef.model_validate({"agent": "a", "model": {"max_tokens": 0}})


def test_agent_constructor_takes_the_model(configs_dir: Path) -> None:
    root = configs_dir / "agents"
    no_default = agent_config(None)
    with pytest.raises(ValueError, match="no model given"):
        Simple(no_default, FakeLLMClient(), prompt_root=root)
    model = LLMModelConfig(provider="deepseek", name="deepseek-chat", max_tokens=300)
    agent = Simple(no_default, FakeLLMClient(), model=model, prompt_root=root)
    request = agent.build_request({"symbol": "AAPL"})
    assert (request.model, request.max_tokens) == ("deepseek-chat", 300)


def test_instances_of_one_agent_can_use_different_providers(configs_dir: Path) -> None:
    claude, deepseek = FakeLLMClient(), FakeLLMClient()
    pool = LLMClientPool({}, env={})
    pool.set("anthropic", claude)
    pool.set("deepseek", deepseek)
    slots = instantiate_agents(
        [
            AgentRef(agent="value_investor"),  # agent config default (claude-test)
            AgentRef(
                agent="value_investor",
                model=LLMModelOverride(provider="deepseek", name="deepseek-chat"),
            ),
        ],
        role=AgentRole.DECISION,
        default_cls=Simple,
        store=ConfigStore(configs_dir, env={}),
        llm=pool,
    )
    first, second = (s.agent for s in slots)
    assert (first.model.provider, first.model.name) == ("anthropic", "claude-test")
    assert (second.model.provider, second.model.name) == ("deepseek", "deepseek-chat")
    assert first._llm is claude
    assert second._llm is deepseek


def test_missing_model_is_a_config_error(configs_dir: Path) -> None:
    path = configs_dir / "agents" / "value_investor.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    del data["model"]
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    store = ConfigStore(configs_dir, env={"IBKR_ACCOUNT": "DU1"})
    with pytest.raises(ConfigError, match="no usable model"):
        instantiate_agents(
            [AgentRef(agent="value_investor")],
            role=AgentRole.DECISION,
            default_cls=Simple,
            store=store,
            llm=LLMClientPool({}, env={}),
        )
    with pytest.raises(ConfigError, match="stage decision: agent value_investor: no usable model"):
        store.validate_pipeline("long_term_stocks")


def pipeline_data(**extra: Any) -> dict[str, Any]:
    return {
        "name": "p",
        "account": "a",
        "universe": ["AAPL"],
        "budget": {"max_capital": 1000},
        "stages": [
            {
                "type": "decision",
                "agents": [
                    {"agent": "trend_follower"},
                    {"agent": "value_investor", "model": {"name": "own-model", "max_tokens": 50}},
                ],
            }
        ],
        **extra,
    }


def test_pipeline_default_model_fills_agent_refs() -> None:
    cfg = PipelineConfig.model_validate(
        pipeline_data(
            default_model={"provider": "openrouter", "name": "x/model", "max_tokens": 4000}
        )
    )
    stage = cfg.stage("decision")
    assert stage is not None
    first, second = stage.agents
    assert first.model == LLMModelOverride(provider="openrouter", name="x/model", max_tokens=4000)
    # A reference's own fields win, field by field.
    assert second.model == LLMModelOverride(provider="openrouter", name="own-model", max_tokens=50)
    assert cfg.default_model is not None
    assert cfg.default_model.name == "x/model"


def test_pipeline_without_default_model_is_unchanged() -> None:
    stage = PipelineConfig.model_validate(pipeline_data()).stage("decision")
    assert stage is not None
    assert stage.agents[0].model is None
