"""LLM access: provider-neutral protocol, Anthropic + fake implementations, structured output."""

from synodtrade_core.llm.anthropic import AnthropicLLMClient
from synodtrade_core.llm.base import (
    BaseLLMClient,
    Effort,
    LLMClient,
    LLMError,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMRetryableError,
    LLMUsage,
)
from synodtrade_core.llm.config import (
    LLMProviderConfig,
    LLMProvidersConfig,
    ModelPrice,
    ProviderKind,
    StructuredOutputMode,
)
from synodtrade_core.llm.factory import (
    LLMClientPool,
    LLMConfigError,
    create_llm_client,
    resolve_api_key,
)
from synodtrade_core.llm.fake import FakeLLMClient
from synodtrade_core.llm.openai_compat import OpenAICompatibleLLMClient
from synodtrade_core.llm.recorder import (
    InMemoryLLMCallRecorder,
    LLMCallRecord,
    LLMCallRecorder,
    NullLLMCallRecorder,
)
from synodtrade_core.llm.schema import schema_instruction, strict_json_schema
from synodtrade_core.llm.structured import StructuredResult, complete_structured, extract_json

__all__ = [
    "AnthropicLLMClient",
    "BaseLLMClient",
    "Effort",
    "FakeLLMClient",
    "InMemoryLLMCallRecorder",
    "LLMCallRecord",
    "LLMCallRecorder",
    "LLMClient",
    "LLMClientPool",
    "LLMConfigError",
    "LLMError",
    "LLMMessage",
    "LLMProviderConfig",
    "LLMProvidersConfig",
    "LLMRequest",
    "LLMResponse",
    "LLMRetryableError",
    "LLMUsage",
    "ModelPrice",
    "NullLLMCallRecorder",
    "OpenAICompatibleLLMClient",
    "ProviderKind",
    "StructuredOutputMode",
    "StructuredResult",
    "complete_structured",
    "create_llm_client",
    "extract_json",
    "resolve_api_key",
    "schema_instruction",
    "strict_json_schema",
]
