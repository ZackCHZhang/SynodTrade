"""Shared fixtures for synodtrade_core tests."""

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

PIPELINE: dict[str, Any] = {
    "name": "long_term_stocks",
    "mode": "paper",
    "account": "ibkr_main",
    "universe": ["aapl", "MSFT"],
    "budget": {"max_capital": 5000},
    "sizing": {"buy_base": "available_cash"},
    "stages": [
        {"type": "data_update", "timeframes": ["1d"], "lookback_days": 365},
        {
            "type": "sentiment",
            "on_error": "skip",
            "sources": ["reddit"],
            "agents": [{"agent": "retail_mood"}],
        },
        {
            "type": "decision",
            "agents": [{"agent": "value_investor", "count": 2, "weight": 1.0}],
            "aggregation": {"method": "weighted_vote", "min_confidence": 0.6},
        },
        {"type": "risk", "rules": "default", "agents": [{"agent": "risk_officer"}]},
        {"type": "trading", "order_type": "limit", "limit_offset_bps": 5},
    ],
}

LLM_PROVIDERS = {
    "providers": {
        "anthropic": {"kind": "anthropic", "api_key_env": "ANTHROPIC_API_KEY"},
        "deepseek": {
            "kind": "openai_compatible",
            "base_url": "https://api.deepseek.com",
            "api_key_env": "DEEPSEEK_API_KEY",
            "structured_output": "json_object",
        },
    }
}

ACCOUNT = {
    "name": "ibkr_main",
    "account_id": "${IBKR_ACCOUNT}",
    "host": "${IBKR_HOST:-127.0.0.1}",
    "port": 4002,
    "client_id": 17,
}


def agent_yaml(agent_id: str, role: str) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "role": role,
        "prompt_version": "v1",
        "model": {"name": "claude-test", "max_tokens": 500},
        "persona": f"You are {agent_id}.",
        "prompt_template": "prompts/test_v1.j2",
    }


def write_yaml(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture
def configs_dir(tmp_path: Path) -> Path:
    root = tmp_path / "configs"
    write_yaml(root / "pipelines" / "long_term_stocks.yaml", PIPELINE)
    write_yaml(root / "accounts" / "ibkr_main.yaml", ACCOUNT)
    for agent_id, role in [
        ("retail_mood", "sentiment"),
        ("value_investor", "decision"),
        ("risk_officer", "risk"),
    ]:
        write_yaml(root / "agents" / f"{agent_id}.yaml", agent_yaml(agent_id, role))
    write_yaml(root / "llm_providers.yaml", LLM_PROVIDERS)
    prompt = root / "agents" / "prompts" / "test_v1.j2"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("Symbol: {{ symbol }}\nReturn JSON.\n", encoding="utf-8")
    return root


@pytest.fixture
def pipeline_data() -> dict[str, Any]:
    """A fresh, mutable copy of the reference pipeline (spec §10.1 example)."""
    return copy.deepcopy(PIPELINE)


@pytest.fixture(name="write_yaml")
def write_yaml_fixture() -> Callable[[Path, Any], Path]:
    return write_yaml


@pytest.fixture(name="agent_yaml")
def agent_yaml_fixture() -> Callable[[str, str], dict[str, Any]]:
    return agent_yaml
