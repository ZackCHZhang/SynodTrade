"""AnthropicLLMClient against a stub SDK object — no network."""

from typing import Any

import anthropic
import httpx2
import pytest
from anthropic.types import Message
from tenacity import wait_none

from quant_core.llm import AnthropicLLMClient, LLMError, LLMMessage, LLMRequest

REQ = LLMRequest(
    model="claude-x",
    system="persona",
    messages=[LLMMessage(role="user", content="hi")],
    max_tokens=300,
)
HTTP_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def make_message(text: str = '{"a": 1}', stop_reason: str = "end_turn") -> Message:
    return Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-x",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "text", "text": text},
            ],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 3},
        }
    )


def status_error(cls: type[anthropic.APIStatusError], code: int) -> anthropic.APIStatusError:
    return cls(f"error {code}", response=httpx2.Response(code, request=HTTP_REQUEST), body=None)


class StubMessages:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Message:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, Message)
        return outcome


class StubSDK:
    def __init__(self, outcomes: list[Any]) -> None:
        self.messages = StubMessages(outcomes)


def make_client(outcomes: list[Any], **kw: Any) -> tuple[AnthropicLLMClient, StubMessages]:
    sdk = StubSDK(outcomes)
    client = AnthropicLLMClient(sdk_client=sdk, wait=wait_none(), **kw)  # type: ignore[arg-type]
    return client, sdk.messages


def test_build_params_minimal() -> None:
    params = make_client([])[0].build_params(REQ)
    assert params == {
        "model": "claude-x",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": "hi"}],
        "system": "persona",
    }


def test_build_params_full() -> None:
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    req = REQ.model_copy(update={"effort": "low", "json_schema": schema, "temperature": 0.2})
    client, _ = make_client([], extra_body={"vendor_flag": True})
    params = client.build_params(req)
    assert params["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": schema},
    }
    assert params["extra_body"] == {"vendor_flag": True, "temperature": 0.2}


async def test_parses_text_blocks_and_usage() -> None:
    client, stub = make_client([make_message()])
    resp = await client.complete(REQ)
    assert resp.text == '{"a": 1}'
    assert resp.stop_reason == "end_turn"
    assert resp.usage.input_tokens == 10
    assert resp.usage.cache_read_input_tokens == 3
    assert resp.raw["id"] == "msg_1"
    assert client.provider == "anthropic"
    assert client.kind == "anthropic"
    assert stub.calls[0]["model"] == "claude-x"


@pytest.mark.parametrize(
    "error",
    [
        status_error(anthropic.RateLimitError, 429),
        status_error(anthropic.InternalServerError, 500),
        status_error(anthropic.OverloadedError, 529),
        anthropic.APIConnectionError(request=HTTP_REQUEST),
        anthropic.APITimeoutError(request=HTTP_REQUEST),
    ],
)
async def test_transient_errors_are_retried(error: Exception) -> None:
    client, stub = make_client([error, make_message()], max_attempts=2)
    resp = await client.complete(REQ)
    assert resp.text
    assert len(stub.calls) == 2


@pytest.mark.parametrize(
    "error",
    [
        status_error(anthropic.BadRequestError, 400),
        status_error(anthropic.AuthenticationError, 401),
        status_error(anthropic.NotFoundError, 404),
    ],
)
async def test_client_errors_are_not_retried(error: Exception) -> None:
    client, stub = make_client([error, make_message()], max_attempts=3)
    with pytest.raises(LLMError, match="HTTP 4"):
        await client.complete(REQ)
    assert len(stub.calls) == 1


def test_constructor_passes_key_and_url_to_sdk() -> None:
    client = AnthropicLLMClient(
        api_key="sk-test-secret",
        base_url="https://api.deepseek.com/anthropic",
        name="deepseek_anthropic",
        extra_headers={"X-Team": "quant"},
        timeout_s=7,
    )
    sdk = client._client
    assert sdk.api_key == "sk-test-secret"
    assert str(sdk.base_url).startswith("https://api.deepseek.com/anthropic")
    assert sdk.max_retries == 0
    assert sdk.default_headers["X-Team"] == "quant"
    assert client.provider == "deepseek_anthropic"
    assert "sk-test-secret" not in repr(client)


async def test_aclose_closes_sdk_client() -> None:
    client = AnthropicLLMClient(api_key="k")
    await client.aclose()
    assert client._client.is_closed()
