"""The configs/ shipped in the repo must always load. Agents are added in phases 5-7."""

from itertools import pairwise
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


def test_model_arena_pipelines_differ_only_in_the_model() -> None:
    """The arena compares LLMs, so within one arena family (arena_<model>, the multi-agent
    pipeline, and arena_solo_<model>, one agent per stage) everything but name, account and
    model must be identical, and both families must cover the same models."""
    store = ConfigStore(REPO_CONFIGS, env=ENV)
    names = [n for n in store.list("pipelines") if n.startswith("arena_")]
    families = {
        "arena_solo_": [n for n in names if n.startswith("arena_solo_")],
        "arena_": [n for n in names if not n.startswith("arena_solo_")],
    }

    def comparable(name: str) -> dict[str, object]:
        data = store.pipeline(name).model_dump(mode="json")
        for key in ("name", "account", "default_model"):
            data.pop(key)
        for stage in data["stages"]:
            for ref in stage.get("agents", []):
                ref.pop("model")  # filled in from default_model
        return data

    accounts, client_ids = set(), set()
    family_models = []
    for prefix, family in families.items():
        assert len(family) >= 2, prefix
        reference = comparable(family[0])
        models = set()
        for name in family:
            pipeline = store.pipeline(name)
            assert comparable(name) == reference, f"{name} differs from the others"
            assert pipeline.default_model is not None
            models.add(pipeline.default_model.name)
            account = store.account(pipeline.account)
            accounts.add(account.name)
            client_ids.add(account.client_id)
            for stage in pipeline.stages:
                for ref in stage.agents:
                    assert ref.model is not None
                    assert ref.model.name == pipeline.default_model.name
        assert len(models) == len(family)
        family_models.append(models)
    assert family_models[0] == family_models[1]  # solo and multi-agent arena: same models
    assert {len(s.agents) for s in store.pipeline(families["arena_solo_"][0]).stages} <= {0, 1}
    assert len(accounts) == len(client_ids) == len(names)
    # Each account uses client_id .. client_id + 4 (data, trading, news, -, account sync).
    ordered = sorted(client_ids)
    assert all(b - a >= 5 for a, b in pairwise(ordered))


def test_repo_prices_cover_the_arena_models() -> None:
    store = ConfigStore(REPO_CONFIGS, env=ENV)
    providers = store.llm_providers().providers
    for name in store.list("pipelines"):
        model = store.pipeline(name).default_model
        if name.startswith("arena_") and model is not None and model.provider is not None:
            assert model.name in providers[model.provider].prices, f"{name}: no price"
