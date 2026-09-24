"""Instantiate the agents a stage references (`agents: [{agent, count, weight}]`)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from quant_core.agent import Agent
from quant_core.config import AgentRef, AgentRole, ConfigError, ConfigStore, resolve_model
from quant_core.llm import LLMCallRecorder, LLMClientPool
from quant_core.registry import AGENTS


@dataclass(frozen=True, slots=True)
class AgentSlot[A: Agent[Any]]:
    agent: A
    weight: float


def instantiate_agents[A: Agent[Any]](
    refs: Sequence[AgentRef],
    *,
    role: AgentRole,
    default_cls: type[A],
    store: ConfigStore,
    llm: LLMClientPool,
    recorder: LLMCallRecorder | None = None,
) -> list[AgentSlot[A]]:
    """`count` independent instances per reference, each with its own instance UUID.

    The model is the reference's `model` applied over the agent config's optional default,
    and the LLM client is the pool's client for that model's provider.
    The class is `default_cls`, unless the agent config names another registered
    implementation via `impl` (which must subclass `default_cls`).
    """
    slots: list[AgentSlot[A]] = []
    for ref in refs:
        config = store.agent(ref.agent)
        if config.role is not role:
            raise ConfigError(f"agent {config.agent_id} has role {config.role}, expected {role}")
        cls: type[A] = default_cls
        if config.impl is not None:
            impl = AGENTS.get(config.impl)
            if not (isinstance(impl, type) and issubclass(impl, default_cls)):
                raise ConfigError(
                    f"agent {config.agent_id}: impl {config.impl!r} is not a {default_cls.__name__}"
                )
            cls = impl
        try:
            model = resolve_model(config, ref.model)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        client = llm.get(model.provider)
        for _ in range(ref.count):
            agent = cls(
                config, client, model=model, prompt_root=store.agents_dir, recorder=recorder
            )
            slots.append(AgentSlot(agent, ref.weight))
    return slots
