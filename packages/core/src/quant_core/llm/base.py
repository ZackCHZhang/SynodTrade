"""Provider-neutral LLM request/response types and the retrying base client."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)
from tenacity.wait import wait_base

Effort = Literal["low", "medium", "high", "xhigh", "max"]

_RETRYABLE_STATUS = frozenset({408, 409, 429})


def is_retryable_status(status_code: int) -> bool:
    """HTTP statuses worth retrying: timeouts, conflicts, rate limits and server errors."""
    return status_code in _RETRYABLE_STATUS or status_code >= 500


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LLMMessage(_Frozen):
    role: Literal["user", "assistant"]
    content: str


class LLMUsage(_Frozen):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class LLMRequest(_Frozen):
    model: str
    messages: list[LLMMessage]
    max_tokens: int = Field(gt=0)
    system: str | None = None
    temperature: float | None = None  # rejected by current Claude models; leave None there
    effort: Effort | None = None
    json_schema: dict[str, Any] | None = None  # constrain the reply to this JSON schema

    def audit_dict(self) -> dict[str, Any]:
        """What gets persisted for audit (never contains credentials)."""
        return self.model_dump(mode="json")


class LLMResponse(_Frozen):
    text: str
    model: str
    stop_reason: str | None = None
    usage: LLMUsage = Field(default_factory=LLMUsage)
    latency_ms: float = 0.0
    request_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class LLMError(Exception):
    """Non-retryable LLM failure (bad request, auth, refusal...)."""


class LLMRetryableError(LLMError):
    """Transient failure (rate limit, overload, network, timeout)."""


@runtime_checkable
class LLMClient(Protocol):
    provider: str  # provider name as configured, e.g. "anthropic", "deepseek"

    async def complete(self, request: LLMRequest) -> LLMResponse: ...


class BaseLLMClient(ABC):
    """Adds a concurrency cap, per-attempt timeout and retry with backoff to `_send`.

    Subclasses translate provider errors into `LLMRetryableError` / `LLMError`.
    """

    kind: str = "base"  # client type, e.g. "anthropic", "openai_compatible"

    def __init__(
        self,
        *,
        name: str | None = None,
        base_url: str | None = None,
        max_concurrency: int = 4,
        max_attempts: int = 4,
        timeout_s: float = 120.0,
        wait: wait_base | None = None,
    ) -> None:
        if max_concurrency < 1 or max_attempts < 1:
            raise ValueError("max_concurrency and max_attempts must be >= 1")
        self.provider = name or self.kind  # configured provider name, used in audit records
        self.base_url = base_url
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_attempts = max_attempts
        self._timeout_s = timeout_s
        self._wait = wait if wait is not None else wait_exponential_jitter(initial=1, max=30)

    def __repr__(self) -> str:
        # Deliberately excludes credentials.
        return f"{type(self).__name__}(provider={self.provider!r}, base_url={self.base_url!r})"

    @abstractmethod
    async def _send(self, request: LLMRequest) -> LLMResponse: ...

    async def aclose(self) -> None:  # noqa: B027 - optional hook, no-op by default
        """Release network resources held by the underlying SDK client."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        retrying = AsyncRetrying(
            retry=retry_if_exception_type(LLMRetryableError),
            stop=stop_after_attempt(self._max_attempts),
            wait=self._wait,
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                return await self._attempt(request)
        raise AssertionError("unreachable")  # pragma: no cover

    async def _attempt(self, request: LLMRequest) -> LLMResponse:
        async with self._semaphore:
            started = time.perf_counter()
            try:
                async with asyncio.timeout(self._timeout_s):
                    response = await self._send(request)
            except TimeoutError as exc:
                raise LLMRetryableError(f"LLM call timed out after {self._timeout_s}s") from exc
            latency_ms = (time.perf_counter() - started) * 1000
        return response.model_copy(update={"latency_ms": latency_ms})
