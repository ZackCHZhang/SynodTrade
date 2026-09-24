"""LLM provider configuration (configs/llm_providers.yaml).

Each named provider says which client class to use and where to reach it. API keys are never
written in config: `api_key_env` names the environment variable that holds the key, and the
factory reads it and passes it to the client constructor.

    providers:
      anthropic:
        kind: anthropic
        api_key_env: ANTHROPIC_API_KEY
      deepseek:
        kind: openai_compatible
        base_url: https://api.deepseek.com
        api_key_env: DEEPSEEK_API_KEY
        structured_output: json_object
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProviderKind(StrEnum):
    ANTHROPIC = "anthropic"  # Anthropic Messages API (also Anthropic-compatible endpoints)
    OPENAI_COMPATIBLE = "openai_compatible"  # OpenAI Chat Completions API and compatibles


class StructuredOutputMode(StrEnum):
    """How an OpenAI-compatible provider is asked for JSON (Anthropic always uses a schema)."""

    JSON_SCHEMA = "json_schema"  # response_format json_schema (OpenAI and some compatibles)
    JSON_OBJECT = "json_object"  # response_format json_object + schema in the prompt (DeepSeek)
    PROMPT = "prompt"  # schema in the prompt only, for providers without JSON mode


class LLMProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ProviderKind
    base_url: str | None = None  # None: the SDK's default endpoint
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    max_concurrency: int = Field(default=4, ge=1)
    max_attempts: int = Field(default=4, ge=1)
    timeout_s: float = Field(default=120.0, gt=0)
    structured_output: StructuredOutputMode = StructuredOutputMode.JSON_SCHEMA
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    extra_headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)  # vendor-specific request fields

    @field_validator("base_url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError(f"base_url must start with http:// or https://, got {value!r}")
        return value


class LLMProvidersConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    providers: dict[str, LLMProviderConfig] = Field(min_length=1)

    @field_validator("providers")
    @classmethod
    def _check_names(cls, value: dict[str, LLMProviderConfig]) -> dict[str, LLMProviderConfig]:
        bad = [name for name in value if not name.replace("_", "").isalnum() or not name.islower()]
        if bad:
            raise ValueError(f"provider names must be lower_snake_case: {bad}")
        return value
