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


class ModelPrice(BaseModel):
    """List price of one model in USD per million tokens. Used only for reporting what the
    LLM calls cost (e.g. the benchmark); it never affects what a run does."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cache_read: float | None = Field(default=None, ge=0)  # None: billed like `input`
    cache_write: float | None = Field(default=None, ge=0)  # None: billed like `input`

    def cost(
        self,
        kind: ProviderKind,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        """USD for one call (or summed calls) as the client recorded its usage.

        Anthropic reports cache reads/writes separately from `input_tokens`; OpenAI-compatible
        APIs include cache hits in their prompt token count, so they are taken out here.
        """
        uncached = input_tokens
        if kind is ProviderKind.OPENAI_COMPATIBLE:
            uncached = max(0, input_tokens - cache_read_tokens - cache_write_tokens)
        read = self.input if self.cache_read is None else self.cache_read
        write = self.input if self.cache_write is None else self.cache_write
        total = (
            uncached * self.input
            + output_tokens * self.output
            + cache_read_tokens * read
            + cache_write_tokens * write
        )
        return total / 1_000_000


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
    # Optional list prices by model name (as written in the agent/pipeline config), for cost
    # reporting only. Models without a price are reported with tokens but no cost.
    prices: dict[str, ModelPrice] = Field(default_factory=dict)

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
