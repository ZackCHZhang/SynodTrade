"""Deterministic in-process LLM for tests and dry runs. Never touches the network."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable

from quant_core.llm.base import LLMRequest, LLMResponse, LLMUsage

FakeReply = str | Exception | Callable[[LLMRequest], str]


class FakeLLMClient:
    """Replies from a scripted queue, then from `default` (a fixed string or a function of
    the request). Exceptions in the script are raised, to simulate provider failures.
    Every request is kept in `requests` for assertions.
    """

    provider = "fake"
    kind = "fake"

    def __init__(
        self,
        script: Iterable[FakeReply] = (),
        *,
        default: FakeReply | None = None,
        stop_reason: str = "end_turn",
    ) -> None:
        self._script: deque[FakeReply] = deque(script)
        self._default = default
        self._stop_reason = stop_reason
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self._script:
            reply = self._script.popleft()
        elif self._default is not None:
            reply = self._default
        else:
            raise AssertionError("FakeLLMClient script exhausted and no default set")

        if isinstance(reply, Exception):
            raise reply
        text = reply(request) if callable(reply) else reply
        prompt_chars = sum(len(m.content) for m in request.messages) + len(request.system or "")
        return LLMResponse(
            text=text,
            model=request.model,
            stop_reason=self._stop_reason,
            usage=LLMUsage(input_tokens=prompt_chars // 4, output_tokens=len(text) // 4),
            raw={"fake": True, "text": text},
        )
