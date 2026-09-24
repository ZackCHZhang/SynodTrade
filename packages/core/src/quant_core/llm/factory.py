"""Build LLM clients from provider configs.

    pool = LLMClientPool(store.llm_providers())
    client = pool.get(agent_config.model.provider)   # e.g. "anthropic" or "deepseek"

One client per provider is shared by every agent that uses it, so the provider's
`max_concurrency` limit applies across all of them.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import openai
from tenacity.wait import wait_base

from quant_core.llm.anthropic import AnthropicLLMClient
from quant_core.llm.base import BaseLLMClient, LLMClient
from quant_core.llm.config import LLMProviderConfig, LLMProvidersConfig, ProviderKind
from quant_core.llm.openai_compat import OpenAICompatibleLLMClient


class LLMConfigError(ValueError):
    """A provider is unknown, or its API key / settings are missing or invalid."""


def resolve_api_key(name: str, config: LLMProviderConfig, env: Mapping[str, str]) -> str | None:
    if config.api_key_env is None:
        return None  # let the SDK use its own default credential lookup
    key = env.get(config.api_key_env)
    if not key:
        raise LLMConfigError(
            f"LLM provider {name!r}: environment variable {config.api_key_env} is not set"
        )
    return key


def create_llm_client(
    name: str,
    config: LLMProviderConfig,
    *,
    env: Mapping[str, str] | None = None,
    wait: wait_base | None = None,
) -> BaseLLMClient:
    api_key = resolve_api_key(name, config, os.environ if env is None else env)
    if config.kind is ProviderKind.ANTHROPIC:
        return AnthropicLLMClient(
            api_key=api_key,
            base_url=config.base_url,
            name=name,
            extra_headers=config.extra_headers,
            extra_body=config.extra_body,
            max_concurrency=config.max_concurrency,
            max_attempts=config.max_attempts,
            timeout_s=config.timeout_s,
            wait=wait,
        )
    try:
        return OpenAICompatibleLLMClient(
            api_key=api_key,
            base_url=config.base_url,
            name=name,
            structured_output=config.structured_output,
            max_tokens_param=config.max_tokens_param,
            extra_headers=config.extra_headers,
            extra_body=config.extra_body,
            max_concurrency=config.max_concurrency,
            max_attempts=config.max_attempts,
            timeout_s=config.timeout_s,
            wait=wait,
        )
    except openai.OpenAIError as exc:  # e.g. no key given and OPENAI_API_KEY unset
        raise LLMConfigError(f"LLM provider {name!r}: {exc}") from exc


class LLMClientPool:
    """Lazily creates and caches one client per configured provider name."""

    def __init__(
        self,
        providers: LLMProvidersConfig | Mapping[str, LLMProviderConfig],
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._configs = dict(
            providers.providers if isinstance(providers, LLMProvidersConfig) else providers
        )
        self._env = env
        self._clients: dict[str, LLMClient] = {}

    def names(self) -> list[str]:
        return sorted(set(self._configs) | set(self._clients))

    def set(self, name: str, client: LLMClient) -> None:
        """Use `client` for `name`, e.g. a FakeLLMClient in tests or dry runs."""
        self._clients[name] = client

    def get(self, name: str) -> LLMClient:
        if name not in self._clients:
            config = self._configs.get(name)
            if config is None:
                known = ", ".join(self.names()) or "none"
                raise LLMConfigError(f"unknown LLM provider {name!r} (known: {known})")
            self._clients[name] = create_llm_client(name, config, env=self._env)
        return self._clients[name]

    def check(self, names: list[str]) -> None:
        """Fail fast at startup: every named provider exists and has its API key."""
        env = os.environ if self._env is None else self._env
        problems: list[str] = []
        for name in sorted(set(names)):
            if name in self._clients:
                continue
            config = self._configs.get(name)
            if config is None:
                problems.append(f"unknown LLM provider {name!r}")
                continue
            try:
                resolve_api_key(name, config, env)
            except LLMConfigError as exc:
                problems.append(str(exc))
        if problems:
            raise LLMConfigError("; ".join(problems))

    async def aclose(self) -> None:
        for client in self._clients.values():
            if isinstance(client, BaseLLMClient):
                await client.aclose()
        self._clients.clear()
