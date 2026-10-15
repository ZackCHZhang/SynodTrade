import pytest

from quant_core.llm import (
    AnthropicLLMClient,
    FakeLLMClient,
    LLMClientPool,
    LLMConfigError,
    LLMProviderConfig,
    LLMProvidersConfig,
    ModelPrice,
    OpenAICompatibleLLMClient,
    ProviderKind,
    StructuredOutputMode,
    create_llm_client,
)

PROVIDERS = LLMProvidersConfig.model_validate(
    {
        "providers": {
            "anthropic": {"kind": "anthropic", "api_key_env": "ANTHROPIC_API_KEY"},
            "deepseek": {
                "kind": "openai_compatible",
                "base_url": "https://api.deepseek.com",
                "api_key_env": "DEEPSEEK_API_KEY",
                "structured_output": "json_object",
                "max_concurrency": 2,
                "timeout_s": 30,
            },
            "local": {
                "kind": "openai_compatible",
                "base_url": "http://localhost:11434/v1",
                "api_key_env": "OLLAMA_API_KEY",
                "structured_output": "prompt",
            },
        }
    }
)
ENV = {"ANTHROPIC_API_KEY": "sk-ant", "DEEPSEEK_API_KEY": "sk-ds", "OLLAMA_API_KEY": "ollama"}


def test_create_anthropic_client() -> None:
    client = create_llm_client("anthropic", PROVIDERS.providers["anthropic"], env=ENV)
    assert isinstance(client, AnthropicLLMClient)
    assert client.provider == "anthropic"
    assert client._client.api_key == "sk-ant"


def test_create_deepseek_client() -> None:
    client = create_llm_client("deepseek", PROVIDERS.providers["deepseek"], env=ENV)
    assert isinstance(client, OpenAICompatibleLLMClient)
    assert client.provider == "deepseek"
    assert client.base_url == "https://api.deepseek.com"
    assert client._client.api_key == "sk-ds"
    assert client._client.timeout == 30
    assert client._structured_output is StructuredOutputMode.JSON_OBJECT


def test_anthropic_compatible_endpoint() -> None:
    # e.g. DeepSeek also serves the Anthropic Messages API at /anthropic
    cfg = LLMProviderConfig(
        kind=ProviderKind.ANTHROPIC,
        base_url="https://api.deepseek.com/anthropic",
        api_key_env="DEEPSEEK_API_KEY",
    )
    client = create_llm_client("deepseek_anthropic", cfg, env=ENV)
    assert isinstance(client, AnthropicLLMClient)
    assert str(client._client.base_url).startswith("https://api.deepseek.com/anthropic")


def test_missing_api_key_env() -> None:
    with pytest.raises(LLMConfigError, match="DEEPSEEK_API_KEY is not set"):
        create_llm_client("deepseek", PROVIDERS.providers["deepseek"], env={})


def test_openai_without_key_env_uses_sdk_default(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = LLMProviderConfig(kind=ProviderKind.OPENAI_COMPATIBLE)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMConfigError, match="'openai'"):
        create_llm_client("openai", cfg, env={})
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-sdk-env")
    client = create_llm_client("openai", cfg, env={})
    assert isinstance(client, OpenAICompatibleLLMClient)
    assert client._client.api_key == "sk-from-sdk-env"


# ------------------------------------------------------------------ pool


def test_pool_caches_one_client_per_provider() -> None:
    pool = LLMClientPool(PROVIDERS, env=ENV)
    first = pool.get("deepseek")
    assert pool.get("deepseek") is first
    assert pool.get("anthropic") is not first
    assert pool.names() == ["anthropic", "deepseek", "local"]


def test_pool_unknown_provider() -> None:
    pool = LLMClientPool(PROVIDERS.providers, env=ENV)
    with pytest.raises(LLMConfigError, match=r"unknown LLM provider 'grok' \(known: anthropic"):
        pool.get("grok")


def test_pool_accepts_injected_clients() -> None:
    pool = LLMClientPool(PROVIDERS, env={})
    fake = FakeLLMClient()
    pool.set("deepseek", fake)
    pool.set("offline", fake)
    assert pool.get("deepseek") is fake  # no key needed once injected
    assert "offline" in pool.names()
    pool.check(["deepseek", "offline"])


def test_pool_check_reports_all_problems() -> None:
    pool = LLMClientPool(PROVIDERS, env={"ANTHROPIC_API_KEY": "k"})
    pool.check(["anthropic"])
    with pytest.raises(LLMConfigError) as info:
        pool.check(["anthropic", "deepseek", "ghost"])
    assert "DEEPSEEK_API_KEY is not set" in str(info.value)
    assert "unknown LLM provider 'ghost'" in str(info.value)


async def test_pool_aclose() -> None:
    pool = LLMClientPool(PROVIDERS, env=ENV)
    client = pool.get("local")
    assert isinstance(client, OpenAICompatibleLLMClient)
    pool.set("fake", FakeLLMClient())
    await pool.aclose()
    assert client._client.is_closed()
    assert pool.get("local") is not client  # recreated on next use


def test_model_price_cost_by_provider_kind() -> None:
    price = ModelPrice(input=2, output=10, cache_read=0.2)
    # OpenAI-compatible prompt counts include cache hits: 1M prompt of which 0.4M cached.
    openai = price.cost(
        ProviderKind.OPENAI_COMPATIBLE,
        input_tokens=1_000_000,
        output_tokens=100_000,
        cache_read_tokens=400_000,
    )
    assert openai == pytest.approx(0.6 * 2 + 0.1 * 10 + 0.4 * 0.2)
    # Anthropic reports cache reads on top of input_tokens.
    anthropic = price.cost(
        ProviderKind.ANTHROPIC,
        input_tokens=600_000,
        output_tokens=100_000,
        cache_read_tokens=400_000,
    )
    assert anthropic == pytest.approx(openai)
    # Without cache prices, cached tokens are billed like input.
    plain = ModelPrice(input=1, output=1)
    assert plain.cost(
        ProviderKind.ANTHROPIC, input_tokens=0, output_tokens=0, cache_write_tokens=1_000_000
    ) == pytest.approx(1)
