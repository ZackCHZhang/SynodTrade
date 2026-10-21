"""Audit trail of every LLM call. `synodtrade_database` provides the persistent implementation."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from synodtrade_core.llm.base import LLMUsage
from synodtrade_core.timeutil import UtcDatetime, utcnow


class LLMCallRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID | None = None
    instance_id: UUID | None = None
    agent_id: str | None = None
    provider: str
    model: str
    attempt: int  # 1-based validation attempt within one structured invocation
    request: dict[str, Any]
    response_text: str | None = None
    raw_response: dict[str, Any] | None = None
    stop_reason: str | None = None
    usage: LLMUsage | None = None
    latency_ms: float | None = None
    error: str | None = None
    created_at: UtcDatetime = Field(default_factory=utcnow)


class LLMCallRecorder(Protocol):
    async def record(self, call: LLMCallRecord) -> None: ...


class InMemoryLLMCallRecorder:
    def __init__(self) -> None:
        self.calls: list[LLMCallRecord] = []

    async def record(self, call: LLMCallRecord) -> None:
        self.calls.append(call)


class NullLLMCallRecorder:
    async def record(self, call: LLMCallRecord) -> None:
        return None
