"""OpenAICompatibleLLMClient (DeepSeek, OpenAI, ...) against a stub SDK — no network."""

import json
from typing import Any

import httpx2
import openai
import pytest
from openai.types.chat import ChatCompletion
from pydantic import BaseModel
from tenacity import wait_none

from quant_core.llm import (
    FakeLLMClient,
    LLMError,
    LLMMessage,
    LLMRequest,
    OpenAICompatibleLLMClient,
    StructuredOutputMode,
    complete_structured,
    strict_json_schema,
)

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "additionalProperties": False}
REQ = LLMRequest(
    model="deepseek-chat",
    system="persona",
    messages=[LLMMessage(role="user", content="hi")],
    max_tokens=300,
)
HTTP_REQUEST = httpx2.Request("POST", "https://api.deepseek.com/chat/completions")


def completion(
    content: str | None = '{"a": 1}', finish_reason: str = "stop", usage: Any = "default"
) -> ChatCompletion:
    data: dict[str, Any] = {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ],
    }
    if usage == "default":
        data["usage"] = {
            "prompt_tokens": 20,
            "completion_tokens": 4,
            "total_tokens": 24,
            "prompt_cache_hit_tokens": 16,  # DeepSeek-specific field
        }
    elif usage is not None:
        data["usage"] = usage
    return ChatCompletion.model_validate(data)


class StubCompletions:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> ChatCompletion:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, ChatCompletion)
        return outcome


class StubSDK:
    def __init__(self, outcomes: list[Any]) -> None:
        self.completions = StubCompletions(outcomes)
        self.chat = self


def make_client(
    outcomes: list[Any], **kw: Any
) -> tuple[OpenAICompatibleLLMClient, StubCompletions]:
    sdk = StubSDK(outcomes)
    client = OpenAICompatibleLLMClient(
        sdk_client=sdk,  # type: ignore[arg-type]
        name="deepseek",
        wait=wait_none(),
        **kw,
    )
    return client, sdk.completions


def status_error(cls: type[openai.APIStatusError], code: int) -> openai.APIStatusError:
    return cls(f"error {code}", response=httpx2.Response(code, request=HTTP_REQUEST), body=None)


# ------------------------------------------------------------------ request building


def test_plain_request() -> None:
    client, _ = make_client([])
    params = client.build_params(REQ)
    assert params == {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "persona"},
            {"role": "user", "content": "hi"},
        ],
        "max_tokens": 300,
    }


def test_json_schema_mode() -> None:
    client, _ = make_client([], structured_output=StructuredOutputMode.JSON_SCHEMA)
    params = client.build_params(REQ.model_copy(update={"json_schema": SCHEMA}))
    assert params["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "output", "schema": SCHEMA, "strict": False},
    }
    assert params["messages"][0]["content"] == "persona"  # schema not repeated in prompt


def test_json_object_mode_puts_schema_in_system_prompt() -> None:
    client, _ = make_client([], structured_output=StructuredOutputMode.JSON_OBJECT)
    params = client.build_params(REQ.model_copy(update={"json_schema": SCHEMA}))
    assert params["response_format"] == {"type": "json_object"}
    system = params["messages"][0]["content"]
    assert system.startswith("persona\n\n")
    assert "JSON" in system  # DeepSeek requires the word "json" in the prompt
    assert json.dumps(SCHEMA, sort_keys=True) in system


def test_prompt_mode_has_no_response_format() -> None:
    client, _ = make_client([], structured_output=StructuredOutputMode.PROMPT)
    req = REQ.model_copy(update={"json_schema": SCHEMA, "system": None})
    params = client.build_params(req)
    assert "response_format" not in params
    assert params["messages"][0]["role"] == "system"
    assert params["messages"][0]["content"].startswith("Reply with a single JSON object")


def test_optional_params() -> None:
    client, _ = make_client(
        [], max_tokens_param="max_completion_tokens", extra_body={"thinking": {"type": "off"}}
    )
    req = REQ.model_copy(update={"temperature": 0.3, "effort": "low", "system": None})
    params = client.build_params(req)
    assert params["max_completion_tokens"] == 300
    assert "max_tokens" not in params
    assert params["temperature"] == 0.3
    assert params["reasoning_effort"] == "low"
    assert params["extra_body"] == {"thinking": {"type": "off"}}
    assert params["messages"] == [{"role": "user", "content": "hi"}]


# ------------------------------------------------------------------ responses


async def test_parses_response_and_deepseek_cache_usage() -> None:
    client, stub = make_client([completion()])
    resp = await client.complete(REQ)
    assert resp.text == '{"a": 1}'
    assert resp.stop_reason == "end_turn"
    assert resp.usage.input_tokens == 20
    assert resp.usage.output_tokens == 4
    assert resp.usage.cache_read_input_tokens == 16
    assert resp.raw["id"] == "cmpl-1"
    assert client.provider == "deepseek"
    assert client.kind == "openai_compatible"
    assert stub.calls[0]["model"] == "deepseek-chat"


async def test_openai_cache_usage_and_missing_usage() -> None:
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "total_tokens": 12,
        "prompt_tokens_details": {"cached_tokens": 8},
    }
    client, _ = make_client([completion(usage=usage), completion(content=None, usage=None)])
    first = await client.complete(REQ)
    assert first.usage.cache_read_input_tokens == 8
    second = await client.complete(REQ)
    assert second.text == ""
    assert second.usage.input_tokens == 0


@pytest.mark.parametrize(
    ("finish", "stop"),
    [("length", "max_tokens"), ("content_filter", "refusal"), ("tool_calls", "tool_use")],
)
async def test_finish_reasons_are_normalised(finish: str, stop: str) -> None:
    client, _ = make_client([completion(finish_reason=finish)])
    assert (await client.complete(REQ)).stop_reason == stop


async def test_no_choices_is_an_error() -> None:
    empty = completion().model_copy(update={"choices": []})
    client, _ = make_client([empty])
    with pytest.raises(LLMError, match="no choices"):
        await client.complete(REQ)


@pytest.mark.parametrize(
    "error",
    [
        status_error(openai.RateLimitError, 429),
        status_error(openai.InternalServerError, 503),
        openai.APIConnectionError(request=HTTP_REQUEST),
        openai.APITimeoutError(request=HTTP_REQUEST),
    ],
)
async def test_transient_errors_are_retried(error: Exception) -> None:
    client, stub = make_client([error, completion()], max_attempts=2)
    assert (await client.complete(REQ)).text
    assert len(stub.calls) == 2


@pytest.mark.parametrize(
    "error",
    [status_error(openai.AuthenticationError, 401), status_error(openai.BadRequestError, 400)],
)
async def test_client_errors_are_not_retried(error: Exception) -> None:
    client, stub = make_client([error, completion()], max_attempts=3)
    with pytest.raises(LLMError, match="HTTP 4"):
        await client.complete(REQ)
    assert len(stub.calls) == 1


async def test_structured_output_end_to_end_with_fenced_reply() -> None:
    class Out(BaseModel):
        a: int

    fenced = '```json\n{"a": 7}\n```'
    client, stub = make_client(
        [completion(content=fenced)], structured_output=StructuredOutputMode.JSON_OBJECT
    )
    result = await complete_structured(client, REQ, Out)
    assert result.output == Out(a=7)
    assert (
        json.dumps(strict_json_schema(Out), sort_keys=True)
        in stub.calls[0]["messages"][0]["content"]
    )


# ------------------------------------------------------------------ construction


async def test_constructor_passes_key_and_url_to_sdk() -> None:
    client = OpenAICompatibleLLMClient(
        api_key="sk-deepseek-secret",
        base_url="https://api.deepseek.com",
        name="deepseek",
        extra_headers={"X-Team": "quant"},
    )
    sdk = client._client
    assert sdk.api_key == "sk-deepseek-secret"
    assert str(sdk.base_url).startswith("https://api.deepseek.com")
    assert sdk.max_retries == 0
    assert sdk.default_headers["X-Team"] == "quant"
    assert "sk-deepseek-secret" not in repr(client)
    assert "deepseek" in repr(client)
    await client.aclose()
    assert sdk.is_closed()


def test_fake_client_kind() -> None:
    assert FakeLLMClient().kind == "fake"
