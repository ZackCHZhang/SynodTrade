"""OpenAI Chat Completions implementation of `LLMClient`.

Works with any OpenAI-compatible endpoint by passing `base_url` + `api_key` at construction:
DeepSeek (https://api.deepseek.com), OpenAI, Qwen/DashScope, Moonshot, vLLM, Ollama, ...

Providers differ in JSON support, so `structured_output` picks the mechanism; whatever the
mode, the reply is validated by Pydantic in `complete_structured`. Finish reasons are mapped
onto the Anthropic-style stop reasons the rest of the code uses.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import openai
from tenacity.wait import wait_base

from synodtrade_core.llm.base import (
    BaseLLMClient,
    LLMError,
    LLMRequest,
    LLMResponse,
    LLMRetryableError,
    LLMUsage,
    is_retryable_status,
)
from synodtrade_core.llm.config import StructuredOutputMode
from synodtrade_core.llm.schema import schema_instruction

_FINISH_TO_STOP = {
    "stop": "end_turn",
    "length": "max_tokens",
    "content_filter": "refusal",
    "tool_calls": "tool_use",
}


class OpenAICompatibleLLMClient(BaseLLMClient):
    kind = "openai_compatible"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        name: str | None = None,
        structured_output: StructuredOutputMode = StructuredOutputMode.JSON_SCHEMA,
        max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens",
        extra_headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, Any] | None = None,
        max_concurrency: int = 4,
        max_attempts: int = 4,
        timeout_s: float = 120.0,
        wait: wait_base | None = None,
        sdk_client: openai.AsyncOpenAI | None = None,
    ) -> None:
        super().__init__(
            name=name,
            base_url=base_url,
            max_concurrency=max_concurrency,
            max_attempts=max_attempts,
            timeout_s=timeout_s,
            wait=wait,
        )
        self._structured_output = structured_output
        self._max_tokens_param = max_tokens_param
        self._extra_body = dict(extra_body or {})
        self._client = sdk_client or openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=extra_headers,
            max_retries=0,
            timeout=timeout_s,
        )

    async def aclose(self) -> None:
        await self._client.close()

    def build_params(self, request: LLMRequest) -> dict[str, Any]:
        schema = request.json_schema
        system = request.system or ""
        if schema is not None and self._structured_output is not StructuredOutputMode.JSON_SCHEMA:
            system = f"{system}\n\n{schema_instruction(schema)}".strip()

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages += [m.model_dump() for m in request.messages]

        params: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            self._max_tokens_param: request.max_tokens,
        }
        if request.temperature is not None:
            params["temperature"] = request.temperature
        if request.effort is not None:
            params["reasoning_effort"] = request.effort
        if schema is not None:
            if self._structured_output is StructuredOutputMode.JSON_SCHEMA:
                # strict=False: strict mode demands every property be required, while our
                # models have optional fields. Pydantic validates the reply either way.
                params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "output", "schema": schema, "strict": False},
                }
            elif self._structured_output is StructuredOutputMode.JSON_OBJECT:
                params["response_format"] = {"type": "json_object"}
        if self._extra_body:
            params["extra_body"] = dict(self._extra_body)
        return params

    async def _send(self, request: LLMRequest) -> LLMResponse:
        try:
            completion = await self._client.chat.completions.create(**self.build_params(request))
        except openai.APIConnectionError as exc:  # includes APITimeoutError
            raise LLMRetryableError(f"connection error: {exc}") from exc
        except openai.APIStatusError as exc:
            detail = f"HTTP {exc.status_code}: {exc.message}"
            if is_retryable_status(exc.status_code):
                raise LLMRetryableError(detail) from exc
            raise LLMError(detail) from exc

        if not completion.choices:
            raise LLMError("response contained no choices")
        choice = completion.choices[0]
        usage = completion.usage
        cached = 0
        if usage is not None:
            details = usage.prompt_tokens_details
            # OpenAI reports cache hits in prompt_tokens_details; DeepSeek in its own field.
            openai_cached = details.cached_tokens if details else None
            cached = int(openai_cached or getattr(usage, "prompt_cache_hit_tokens", 0) or 0)
        return LLMResponse(
            text=choice.message.content or "",
            model=completion.model,
            stop_reason=_FINISH_TO_STOP.get(choice.finish_reason, choice.finish_reason),
            usage=LLMUsage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                cache_read_input_tokens=cached,
            ),
            request_id=getattr(completion, "_request_id", None),
            raw=completion.to_dict(),
        )
