"""The configs/ shipped in the repo must always load. Agents are added in phases 5-7."""

from pathlib import Path

import pytest

from quant_core.config import ConfigStore, resolve_model
from quant_core.models import RunMode

REPO_CONFIGS = Path(__file__).resolve().parents[3] / "configs"
ENV = {"IBKR_ACCOUNT": "DU0000000"}


def test_repo_pipelines_load() -> None:
    store = ConfigStore(REPO_CONFIGS, env=ENV)
    names = store.list("pipelines")
    assert "long_term_stocks" in names
    for name in names:
        pipeline = store.pipeline(name)
        assert pipeline.mode is not RunMode.LIVE, "never commit a live pipeline config"
        store.account(pipeline.account)


def test_repo_account_defaults_to_paper_port() -> None:
    account = ConfigStore(REPO_CONFIGS, env=ENV).account("ibkr_main")
    assert account.port == 4002
    assert account.account_id == "DU0000000"


def test_repo_llm_providers() -> None:
    providers = ConfigStore(REPO_CONFIGS, env=ENV).llm_providers().providers
    assert {"anthropic", "deepseek"} <= set(providers)
    for name, provider in providers.items():
        assert provider.api_key_env, f"provider {name} should name its API key variable"


@pytest.mark.parametrize("stage_type", ["sentiment", "decision", "risk"])
def test_repo_agents_of_implemented_stages_load(stage_type: str) -> None:
    store = ConfigStore(REPO_CONFIGS, env=ENV)
    providers = store.llm_providers().providers
    for name in store.list("pipelines"):
        stage = store.pipeline(name).stage(stage_type)
        if stage is None:
            continue
        for ref in stage.agents:
            agent = store.agent(ref.agent)
            assert agent.role.value == stage_type
            model = resolve_model(agent, ref.model)  # chosen at instantiation
            assert model.provider in providers
            assert model.temperature is None  # rejected by current Claude models


def test_repo_pipelines_fully_valid() -> None:
    """Every agent every pipeline references exists, has the right role and a model."""
    store = ConfigStore(REPO_CONFIGS, env=ENV)
    for name in store.list("pipelines"):
        store.validate_pipeline(name)
