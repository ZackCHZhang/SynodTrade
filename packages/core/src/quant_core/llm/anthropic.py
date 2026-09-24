"""Anthropic (Claude) implementation of `LLMClient`.

`api_key` / `base_url` are passed in at construction (see `quant_core.llm.factory`); a
different `base_url` points it at any Anthropic-compatible endpoint. With `api_key=None`
the SDK resolves credentials from the environment (ANTHROPIC_API_KEY, `ant auth login`...).
SDK-level retries are disabled so `BaseLLMClient` owns the single retry policy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import anthropic
from tenacity.wait import wait_base

from quant_core.llm.base import (
    BaseLLMClient,
    LLMError,
    LLMRequest,
    LLMResponse,
    LLMRetryableError,
    LLMUsage,
    is_retryable_status,
)


class AnthropicLLMClient(BaseLLMClient):
    kind = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        name: str | None = None,
        extra_headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, Any] | None = None,
        max_concurrency: int = 4,
        max_attempts: int = 4,
        timeout_s: float = 120.0,
        wait: wait_base | None = None,
        sdk_client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        super().__init__(
            name=name,
            base_url=base_url,
            max_concurrency=max_concurrency,
            max_attempts=max_attempts,
            timeout_s=timeout_s,
            wait=wait,
        )
        self._extra_body = dict(extra_body or {})
        self._client = sdk_client or anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            default_headers=extra_headers,
            max_retries=0,
            timeout=timeout_s,
        )

    async def aclose(self) -> None:
        await self._client.close()

    def build_params(self, request: LLMRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": [m.model_dump() for m in request.messages],
        }
        if request.system:
            params["system"] = request.system
        output_config: dict[str, Any] = {}
        if request.effort:
            output_config["effort"] = request.effort
        if request.json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": request.json_schema}
        if output_config:
            params["output_config"] = output_config
        extra_body = dict(self._extra_body)
        if request.temperature is not None:
            # Not a typed SDK parameter any more; only older models (e.g. Haiku 4.5) accept it.
            extra_body["temperature"] = request.temperature
        if extra_body:
            params["extra_body"] = extra_body
        return params

    async def _send(self, request: LLMRequest) -> LLMResponse:
        try:
            message = await self._client.messages.create(**self.build_params(request))
        except anthropic.APIConnectionError as exc:  # includes APITimeoutError
            raise LLMRetryableError(f"connection error: {exc}") from exc
        except anthropic.APIStatusError as exc:
            detail = f"HTTP {exc.status_code}: {exc.message}"
            if is_retryable_status(exc.status_code):
                raise LLMRetryableError(detail) from exc
            raise LLMError(detail) from exc

        text = "".join(block.text for block in message.content if block.type == "text")
        usage = message.usage
        return LLMResponse(
            text=text,
            model=message.model,
            stop_reason=message.stop_reason,
            usage=LLMUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_input_tokens=usage.cache_read_input_tokens or 0,
                cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
            ),
            # Set by the SDK on HTTP responses; absent on locally constructed messages.
            request_id=getattr(message, "_request_id", None),
            raw=message.to_dict(),
        )
