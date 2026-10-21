from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from synodtrade_core.agent import Agent
from synodtrade_core.agent_factory import instantiate_agents
from synodtrade_core.config import AgentRef, AgentRole, ConfigError, ConfigStore
from synodtrade_core.llm import FakeLLMClient, InMemoryLLMCallRecorder, LLMClientPool
from synodtrade_core.registry import AGENTS


class Out(BaseModel):
    ok: bool


class BaseDecision(Agent[Out]):
    output_model = Out

    def fallback_output(self, inputs: Mapping[str, Any], error: str) -> Out:
        return Out(ok=False)


class SpecialDecision(BaseDecision):
    pass


class Unrelated:
    pass


@pytest.fixture
def pool() -> LLMClientPool:
    p = LLMClientPool({}, env={})
    p.set("anthropic", FakeLLMClient())
    return p


def test_count_and_weight(configs_dir: Path, pool: LLMClientPool) -> None:
    recorder = InMemoryLLMCallRecorder()
    slots = instantiate_agents(
        [AgentRef(agent="value_investor", count=3, weight=0.5)],
        role=AgentRole.DECISION,
        default_cls=BaseDecision,
        store=ConfigStore(configs_dir, env={}),
        llm=pool,
        recorder=recorder,
    )
    assert len(slots) == 3
    assert len({s.agent.instance_id for s in slots}) == 3
    assert all(s.weight == 0.5 and type(s.agent) is BaseDecision for s in slots)
    assert slots[0].agent._recorder is recorder


def test_role_mismatch(configs_dir: Path, pool: LLMClientPool) -> None:
    with pytest.raises(ConfigError, match="expected risk"):
        instantiate_agents(
            [AgentRef(agent="value_investor")],
            role=AgentRole.RISK,
            default_cls=BaseDecision,
            store=ConfigStore(configs_dir, env={}),
            llm=pool,
        )


def _with_impl(configs_dir: Path, impl: str) -> ConfigStore:
    path = configs_dir / "agents" / "value_investor.yaml"
    path.write_text(path.read_text(encoding="utf-8") + f"impl: {impl}\n", encoding="utf-8")
    return ConfigStore(configs_dir, env={})


def test_impl_override(configs_dir: Path, pool: LLMClientPool) -> None:
    AGENTS.register("special_decision_test", SpecialDecision)
    AGENTS.register("unrelated_test", Unrelated)
    try:
        [slot] = instantiate_agents(
            [AgentRef(agent="value_investor")],
            role=AgentRole.DECISION,
            default_cls=BaseDecision,
            store=_with_impl(configs_dir, "special_decision_test"),
            llm=pool,
        )
        assert type(slot.agent) is SpecialDecision

        with pytest.raises(ConfigError, match="is not a BaseDecision"):
            instantiate_agents(
                [AgentRef(agent="value_investor")],
                role=AgentRole.DECISION,
                default_cls=BaseDecision,
                store=_with_impl(configs_dir, "unrelated_test"),
                llm=pool,
            )
    finally:
        AGENTS.unregister("special_decision_test")
        AGENTS.unregister("unrelated_test")
