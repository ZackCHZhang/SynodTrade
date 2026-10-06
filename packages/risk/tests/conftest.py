"""Shared fixtures for quant_risk tests (SQLite, fake LLM; no network)."""

import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import yaml

from quant_core.config import ConfigStore
from quant_core.models import RunMode
from quant_database import Database, PipelineRun, Repositories

REPO_CONFIGS = Path(__file__).resolve().parents[3] / "configs"
NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)  # Thursday, NYSE open


@pytest.fixture
async def repos(tmp_path: Path) -> AsyncIterator[Repositories]:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'risk.db'}")
    await db.create_all()
    yield Repositories.create(db)
    await db.dispose()


@pytest.fixture
def new_run(repos: Repositories) -> Callable[..., Awaitable[UUID]]:
    async def create(as_of: datetime = NOW) -> UUID:
        rid = uuid4()
        await repos.runs.start_run(
            PipelineRun(
                run_id=rid,
                pipeline_name="long_term_stocks",
                mode=RunMode.DRY_RUN,
                config_hash="0" * 64,
                config={},
                as_of=as_of,
                started_at=as_of,
            )
        )
        return rid

    return create


@pytest.fixture
def store(tmp_path: Path) -> ConfigStore:
    """configs/ with the repo's real risk rules, risk agent and prompt template."""
    root = tmp_path / "configs"
    (root / "agents" / "prompts").mkdir(parents=True)
    (root / "risk").mkdir()
    shutil.copy(REPO_CONFIGS / "agents" / "prompts" / "risk_v1.j2", root / "agents" / "prompts")
    shutil.copy(REPO_CONFIGS / "agents" / "conservative_risk_officer.yaml", root / "agents")
    shutil.copy(REPO_CONFIGS / "risk" / "default.yaml", root / "risk")
    (root / "llm_providers.yaml").write_text(
        yaml.safe_dump({"providers": {"anthropic": {"kind": "anthropic"}}}), encoding="utf-8"
    )
    return ConfigStore(root, env={})


def sample_inputs(**overrides: Any) -> dict[str, Any]:
    """Every variable the risk_v1 template needs."""
    base: dict[str, Any] = {
        "symbol": "AAPL",
        "as_of": "2026-09-24T14:00+00:00",
        "original_action": "strong_buy",
        "order": {
            "side": "buy",
            "quantity": "15",
            "notional": "1,500.00",
            "position_pct": "+0.00%",
            "position_pct_after": "+15.00%",
            "pct_of_adv": "0.001%",
            "var_95_1d": "31.00",
            "loss_2atr_pct_nav": "0.45%",
        },
        "position": None,
        "portfolio": {
            "nav": "10,000.00",
            "cash_pct": "+100.00%",
            "gross_pct": "+0.00%",
            "daily_return": "+0.00%",
            "weekly_return": "+0.00%",
            "total_return": "+0.00%",
            "realized_pnl": "0.00",
            "positions": "0",
            "beta": "n/a",
        },
        "holdings": [],
        "trading": {"trades_today": "0", "max_trades_per_day": "4", "orders_30d": "0"},
        "market": {
            "last_close": "100.00",
            "price": "100.10",
            "return_1d": "+1.00%",
            "return_20d": "+5.00%",
            "volatility_20d": "+20.00%",
            "from_52w_high": "-2.00%",
            "rsi_14": "61.00",
            "atr_14_pct": "+1.50%",
            "max_gap_60d": "+2.10%",
            "max_drawdown_1y": "-12.00%",
            "spread_bps": "1.0",
            "avg_volume_20d": "50,000,000",
        },
        "benchmark": None,
        "fundamentals": None,
        "currency": {"account": "EUR", "instrument": "USD"},
        "broker_check": None,
        "selection": None,
        "history": [],
        "aggregation": {"method": "weighted_vote(min_confidence=0.6)", "score": "+0.200"},
        "decisions": [
            {
                "agent": "trend_follower",
                "action": "strong_buy",
                "confidence": "0.90",
                "reasoning": "clean uptrend",
            }
        ],
        "sentiment": [],
        "rule_hits": ["strong_buy: order value 3000.00 > limit 2000"],
    }
    return {**base, **overrides}


@pytest.fixture
def risk_inputs() -> Callable[..., dict[str, Any]]:
    return sample_inputs
