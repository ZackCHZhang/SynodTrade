"""Structured (JSON) completion with Pydantic validation and repair retries."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from uuid import UUID

from pydantic import BaseModel, ValidationError

from quant_core.llm.base import LLMClient, LLMError, LLMMessage, LLMRequest
from quant_core.llm.recorder import LLMCallRecord, LLMCallRecorder, NullLLMCallRecorder
from quant_core.llm.schema import strict_json_schema

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_BAD_STOP_REASONS = frozenset({"refusal", "max_tokens"})


@dataclass(frozen=True, slots=True)
class StructuredResult[T: BaseModel]:
    output: T | None
    attempts: int
    call_ids: list[UUID] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.output is not None


def extract_json(text: str) -> str:
    """Pull the JSON object out of a reply that may be wrapped in prose or a code fence."""
    text = text.strip()
    if match := _FENCE.search(text):
        text = match.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object found in response")
    return text[start : end + 1]


def _repair_prompt(error: str) -> str:
    return (
        "Your previous reply could not be used because it did not match the required JSON "
        f"schema:\n{error}\nReply again with only a corrected JSON object."
    )


async def complete_structured[T: BaseModel](
    client: LLMClient,
    request: LLMRequest,
    output_model: type[T],
    *,
    max_attempts: int = 3,
    recorder: LLMCallRecorder | None = None,
    run_id: UUID | None = None,
    instance_id: UUID | None = None,
    agent_id: str | None = None,
) -> StructuredResult[T]:
    """Ask for JSON matching `output_model`; on invalid output, show the model its error and
    retry up to `max_attempts` times. Never raises for LLM failures: returns `error` instead.
    Transport-level retries (rate limits, timeouts) happen inside the client.
    """
    recorder = recorder or NullLLMCallRecorder()
    messages = list(request.messages)
    call_ids: list[UUID] = []
    last_error = "no attempts made"
    schema = strict_json_schema(output_model)

    for attempt in range(1, max_attempts + 1):
        req = request.model_copy(update={"messages": list(messages), "json_schema": schema})
        base = LLMCallRecord(
            run_id=run_id,
            instance_id=instance_id,
            agent_id=agent_id,
            provider=client.provider,
            model=req.model,
            attempt=attempt,
            request=req.audit_dict(),
        )
        try:
            resp = await client.complete(req)
        except LLMError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            record = base.model_copy(update={"error": last_error})
            await recorder.record(record)
            call_ids.append(record.id)
            return StructuredResult(None, attempt, call_ids, last_error)

        error: str | None = None
        output: T | None = None
        if resp.stop_reason in _BAD_STOP_REASONS:
            error = f"stop_reason={resp.stop_reason}"
        else:
            try:
                output = output_model.model_validate_json(extract_json(resp.text))
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                error = str(exc)

        record = base.model_copy(
            update={
                "response_text": resp.text,
                "raw_response": resp.raw,
                "stop_reason": resp.stop_reason,
                "usage": resp.usage,
                "latency_ms": resp.latency_ms,
                "error": error,
            }
        )
        await recorder.record(record)
        call_ids.append(record.id)

        if output is not None:
            return StructuredResult(output, attempt, call_ids)
        last_error = error or "invalid output"
        if resp.stop_reason not in _BAD_STOP_REASONS:
            messages += [
                LLMMessage(role="assistant", content=resp.text),
                LLMMessage(role="user", content=_repair_prompt(last_error)),
            ]

    return StructuredResult(None, max_attempts, call_ids, last_error)
