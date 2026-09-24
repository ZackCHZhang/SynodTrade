from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field

from quant_core.agent import Agent
from quant_core.config import AgentConfig, ConfigStore
from quant_core.llm import FakeLLMClient, InMemoryLLMCallRecorder, LLMError
from quant_core.models import Action


class Opinion(BaseModel):
    action: Action
    confidence: float = Field(ge=0, le=1)
    reasoning: str


class OpinionAgent(Agent[Opinion]):
    output_model = Opinion

    def fallback_output(self, inputs: Mapping[str, Any], error: str) -> Opinion:
        return Opinion(action=Action.HOLD, confidence=0.0, reasoning=f"fallback: {error}")


@pytest.fixture
def agent_config(configs_dir: Path) -> AgentConfig:
    return ConfigStore(configs_dir, env={}).agent("value_investor")


def make_agent(cfg: AgentConfig, configs_dir: Path, llm: FakeLLMClient, **kw: Any) -> OpinionAgent:
    return OpinionAgent(cfg, llm, prompt_root=configs_dir / "agents", **kw)


def test_render_and_build_request(agent_config: AgentConfig, configs_dir: Path) -> None:
    agent = make_agent(agent_config, configs_dir, FakeLLMClient())
    req = agent.build_request({"symbol": "AAPL"})
    assert req.system == "You are value_investor."
    assert req.messages[0].content == "Symbol: AAPL\nReturn JSON.\n"
    assert req.model == "claude-test"
    assert req.max_tokens == 500
    assert req.temperature is None
    assert agent.agent_id == "value_investor"
    assert agent.prompt_version == "v1"


def test_instances_have_distinct_ids(agent_config: AgentConfig, configs_dir: Path) -> None:
    a = make_agent(agent_config, configs_dir, FakeLLMClient())
    b = make_agent(agent_config, configs_dir, FakeLLMClient())
    fixed = uuid4()
    c = make_agent(agent_config, configs_dir, FakeLLMClient(), instance_id=fixed)
    assert a.instance_id != b.instance_id
    assert c.instance_id == fixed


async def test_invoke_success(agent_config: AgentConfig, configs_dir: Path) -> None:
    rec = InMemoryLLMCallRecorder()
    fake = FakeLLMClient(['{"action": "buy", "confidence": 0.8, "reasoning": "cheap"}'])
    agent = make_agent(agent_config, configs_dir, fake, recorder=rec)
    run_id = uuid4()
    result = await agent.invoke({"symbol": "AAPL"}, run_id=run_id)
    assert not result.fallback_used
    assert result.output.action is Action.BUY
    assert result.call_ids == [rec.calls[0].id]
    assert rec.calls[0].instance_id == agent.instance_id
    assert rec.calls[0].run_id == run_id


async def test_invoke_falls_back_to_hold_after_invalid_output(
    agent_config: AgentConfig, configs_dir: Path
) -> None:
    fake = FakeLLMClient(default='{"action": "moon", "confidence": 2}')
    agent = make_agent(agent_config, configs_dir, fake)
    result = await agent.invoke({"symbol": "AAPL"})
    assert result.fallback_used
    assert result.output.action is Action.HOLD
    assert len(fake.requests) == agent.model.max_validation_attempts
    assert len(result.call_ids) == 3


async def test_invoke_falls_back_when_llm_unavailable(
    agent_config: AgentConfig, configs_dir: Path
) -> None:
    agent = make_agent(agent_config, configs_dir, FakeLLMClient([LLMError("down")]))
    result = await agent.invoke({"symbol": "AAPL"})
    assert result.output.action is Action.HOLD
    assert result.error is not None
    assert "down" in result.error


async def test_missing_template_variable_is_a_config_error(
    agent_config: AgentConfig, configs_dir: Path
) -> None:
    fake = FakeLLMClient()
    agent = make_agent(agent_config, configs_dir, fake)
    with pytest.raises(ValueError, match="cannot render prompt"):
        await agent.invoke({})
    assert fake.requests == []


def test_template_is_sandboxed(agent_config: AgentConfig, configs_dir: Path) -> None:
    (configs_dir / "agents" / "prompts" / "evil.j2").write_text(
        "{{ symbol.__class__.__mro__ }}", encoding="utf-8"
    )
    cfg = agent_config.model_copy(update={"prompt_template": "prompts/evil.j2"})
    agent = make_agent(cfg, configs_dir, FakeLLMClient())
    with pytest.raises(Exception, match=r"unsafe|not safely"):
        agent.render_prompt({"symbol": "AAPL"})
