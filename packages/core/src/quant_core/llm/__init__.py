"""LLM access: provider-neutral protocol, Anthropic + fake implementations, structured output."""

from quant_core.llm.anthropic import AnthropicLLMClient
from quant_core.llm.base import (
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
from quant_core.llm.config import (
    LLMProviderConfig,
    LLMProvidersConfig,
    ModelPrice,
    ProviderKind,
    StructuredOutputMode,
)
from quant_core.llm.factory import (
    LLMClientPool,
    LLMConfigError,
    create_llm_client,
    resolve_api_key,
)
from quant_core.llm.fake import FakeLLMClient
from quant_core.llm.openai_compat import OpenAICompatibleLLMClient
from quant_core.llm.recorder import (
    InMemoryLLMCallRecorder,
    LLMCallRecord,
    LLMCallRecorder,
    NullLLMCallRecorder,
)
from quant_core.llm.schema import schema_instruction, strict_json_schema
from quant_core.llm.structured import StructuredResult, complete_structured, extract_json

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
