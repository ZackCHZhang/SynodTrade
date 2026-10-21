"""Shared fixtures for synodtrade_selection tests (SQLite, fake LLM; no network)."""

import shutil
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import yaml

from synodtrade_core.config import ConfigStore
from synodtrade_core.models import Bar, RunMode, Timeframe
from synodtrade_database import Database, PipelineRun, Repositories

REPO_CONFIGS = Path(__file__).resolve().parents[3] / "configs"
NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)
DAY0 = datetime(2025, 9, 1, 4, 0, tzinfo=UTC)
PIPELINE = "stock_picker"


def bars_from_closes(
    symbol: str,
    closes: Sequence[float],
    *,
    start: datetime = DAY0,
    volume: int = 1_000_000,
) -> list[Bar]:
    """One daily bar per calendar day from `start` (all completed before NOW)."""
    out = []
    for i, c in enumerate(closes):
        close = Decimal(str(round(c, 2)))
        out.append(
            Bar(
                symbol=symbol,
                timeframe=Timeframe.D1,
                ts=start + timedelta(days=i),
                open=close,
                high=close + 1,
                low=max(close - 1, Decimal("0.01")),
                close=close,
                volume=Decimal(volume),
            )
        )
    return out


@pytest.fixture
def make_bars() -> Callable[..., list[Bar]]:
    return bars_from_closes


@pytest.fixture
async def repos(tmp_path: Path) -> AsyncIterator[Repositories]:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'sel.db'}")
    await db.create_all()
    yield Repositories.create(db)
    await db.dispose()


@pytest.fixture
def new_run(repos: Repositories) -> Callable[..., object]:
    async def create(as_of: datetime = NOW) -> UUID:
        rid = uuid4()
        await repos.runs.start_run(
            PipelineRun(
                run_id=rid,
                pipeline_name=PIPELINE,
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
    """configs/ with the repo's real selection agents and prompt template."""
    root = tmp_path / "configs"
    (root / "agents" / "prompts").mkdir(parents=True)
    shutil.copy(
        REPO_CONFIGS / "agents" / "prompts" / "selection_v1.j2", root / "agents" / "prompts"
    )
    for agent_id in ("momentum_screener", "defensive_screener", "value_investor"):
        shutil.copy(REPO_CONFIGS / "agents" / f"{agent_id}.yaml", root / "agents")
    shutil.copy(REPO_CONFIGS / "agents" / "prompts" / "decision_v1.j2", root / "agents" / "prompts")
    (root / "llm_providers.yaml").write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "anthropic": {"kind": "anthropic"},
                    "deepseek": {
                        "kind": "openai_compatible",
                        "base_url": "https://api.deepseek.com",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return ConfigStore(root, env={})
