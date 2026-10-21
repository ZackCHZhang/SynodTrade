import asyncio
import json
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field
from tenacity import wait_none

from synodtrade_core.llm import (
    BaseLLMClient,
    FakeLLMClient,
    InMemoryLLMCallRecorder,
    LLMError,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMRetryableError,
    complete_structured,
    extract_json,
    strict_json_schema,
)


class Inner(BaseModel):
    tag: str = Field(max_length=10)


class Out(BaseModel):
    action: str
    confidence: float = Field(ge=0, le=1)
    items: list[Inner] = Field(default_factory=list, max_length=3)


REQ = LLMRequest(
    model="m", messages=[LLMMessage(role="user", content="hi")], max_tokens=100, system="sys"
)
GOOD = '{"action": "buy", "confidence": 0.7}'


# ------------------------------------------------------------------ schema


def test_strict_schema_removes_unsupported_and_closes_objects() -> None:
    schema = strict_json_schema(Out)
    dumped = json.dumps(schema)
    for key in ('"minimum"', '"maximum"', '"maxLength"', '"maxItems"'):
        assert key not in dumped
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Inner"]["additionalProperties"] is False
    assert "minimum=0" in schema["properties"]["confidence"]["description"]
    assert "maxLength=10" in schema["$defs"]["Inner"]["properties"]["tag"]["description"]


def test_strict_schema_drops_unknown_formats() -> None:
    class M(BaseModel):
        pattern_field: str = Field(pattern="^a")
        when: str = Field(json_schema_extra={"format": "date-time"})
        custom: str = Field(json_schema_extra={"format": "weird"})

    props = strict_json_schema(M)["properties"]
    assert props["when"]["format"] == "date-time"
    assert "format" not in props["custom"]
    assert "pattern" not in props["pattern_field"]


# ------------------------------------------------------------------ extract_json


@pytest.mark.parametrize(
    "text",
    [
        GOOD,
        f"```json\n{GOOD}\n```",
        f"Here you go:\n```\n{GOOD}\n```\nthanks",
        f"Sure! {GOOD} Hope this helps.",
    ],
)
def test_extract_json(text: str) -> None:
    assert json.loads(extract_json(text)) == json.loads(GOOD)


def test_extract_json_without_object() -> None:
    with pytest.raises(ValueError, match="no JSON"):
        extract_json("nothing here")


# ------------------------------------------------------------------ structured


async def test_structured_success_first_try() -> None:
    fake = FakeLLMClient([GOOD])
    rec = InMemoryLLMCallRecorder()
    run_id, inst = uuid4(), uuid4()
    result = await complete_structured(
        fake, REQ, Out, recorder=rec, run_id=run_id, instance_id=inst, agent_id="a"
    )
    assert result.ok
    assert result.output == Out(action="buy", confidence=0.7)
    assert result.attempts == 1
    assert fake.requests[0].json_schema == strict_json_schema(Out)
    [call] = rec.calls
    assert call.id == result.call_ids[0]
    assert (call.run_id, call.instance_id, call.agent_id) == (run_id, inst, "a")
    assert call.response_text == GOOD
    assert call.error is None
    assert call.request["system"] == "sys"
    assert call.usage is not None


async def test_structured_repairs_invalid_output() -> None:
    fake = FakeLLMClient(['{"action": "buy", "confidence": 7}', GOOD])
    rec = InMemoryLLMCallRecorder()
    result = await complete_structured(fake, REQ, Out, recorder=rec)
    assert result.ok
    assert result.attempts == 2
    second = fake.requests[1].messages
    assert [m.role for m in second] == ["user", "assistant", "user"]
    assert "less than or equal to 1" in second[2].content
    assert rec.calls[0].error is not None
    assert rec.calls[1].error is None


async def test_structured_gives_up_after_max_attempts() -> None:
    fake = FakeLLMClient(default="not json at all")
    rec = InMemoryLLMCallRecorder()
    result = await complete_structured(fake, REQ, Out, max_attempts=3, recorder=rec)
    assert not result.ok
    assert result.attempts == 3
    assert len(rec.calls) == 3
    assert result.error is not None
    assert "no JSON" in result.error


async def test_structured_bad_stop_reason_is_retried_without_repair_turn() -> None:
    fake = FakeLLMClient([GOOD], stop_reason="refusal")
    fake._script.append(GOOD)
    result = await complete_structured(fake, REQ, Out, max_attempts=2)
    assert not result.ok
    assert result.error == "stop_reason=refusal"
    assert len(fake.requests[1].messages) == 1


async def test_structured_transport_error_returns_error() -> None:
    fake = FakeLLMClient([LLMError("HTTP 401: bad key")])
    rec = InMemoryLLMCallRecorder()
    result = await complete_structured(fake, REQ, Out, recorder=rec)
    assert not result.ok
    assert result.error == "LLMError: HTTP 401: bad key"
    assert rec.calls[0].error == result.error
    assert rec.calls[0].response_text is None


async def test_fake_client_default_callable_and_exhaustion() -> None:
    fake = FakeLLMClient(default=lambda req: req.messages[-1].content.upper())
    resp = await fake.complete(REQ)
    assert resp.text == "HI"
    assert resp.raw["fake"] is True
    with pytest.raises(AssertionError, match="exhausted"):
        await FakeLLMClient().complete(REQ)


# ------------------------------------------------------------------ BaseLLMClient


class Scripted(BaseLLMClient):
    provider = "scripted"

    def __init__(self, outcomes: list[Any], **kw: Any) -> None:
        super().__init__(wait=wait_none(), **kw)
        self.outcomes = outcomes
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def _send(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            outcome = self.outcomes.pop(0) if self.outcomes else "ok"
            if isinstance(outcome, float):
                await asyncio.sleep(outcome)
                outcome = "slow"
            if isinstance(outcome, Exception):
                raise outcome
            await asyncio.sleep(0.01)
            return LLMResponse(text=outcome, model=request.model)
        finally:
            self.active -= 1


async def test_base_client_retries_retryable_errors() -> None:
    client = Scripted([LLMRetryableError("429"), LLMRetryableError("503"), "done"], max_attempts=3)
    resp = await client.complete(REQ)
    assert resp.text == "done"
    assert client.calls == 3
    assert resp.latency_ms > 0


async def test_base_client_gives_up() -> None:
    client = Scripted([LLMRetryableError("a"), LLMRetryableError("b")], max_attempts=2)
    with pytest.raises(LLMRetryableError, match="b"):
        await client.complete(REQ)


async def test_base_client_does_not_retry_fatal_errors() -> None:
    client = Scripted([LLMError("400")], max_attempts=5)
    with pytest.raises(LLMError, match="400"):
        await client.complete(REQ)
    assert client.calls == 1


async def test_base_client_timeout_is_retryable() -> None:
    client = Scripted([5.0, "fast"], max_attempts=2, timeout_s=0.05)
    resp = await client.complete(REQ)
    assert resp.text == "fast"
    assert client.calls == 2


async def test_base_client_concurrency_limit() -> None:
    client = Scripted([], max_concurrency=2)
    await asyncio.gather(*(client.complete(REQ) for _ in range(6)))
    assert client.calls == 6
    assert client.max_active == 2


def test_base_client_validates_settings() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        Scripted([], max_concurrency=0)
