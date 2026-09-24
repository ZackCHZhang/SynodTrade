"""Shared fixtures for quant_decision tests (SQLite, fake LLM; no network)."""

import shutil
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import yaml

from quant_core.config import ConfigStore
from quant_core.models import Bar, RunMode, Timeframe
from quant_database import Database, PipelineRun, Repositories

REPO_CONFIGS = Path(__file__).resolve().parents[3] / "configs"
NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)
DAY0 = datetime(2025, 1, 1, 5, 0, tzinfo=UTC)

BarsFactory = Callable[..., list[Bar]]


def bars_from_closes(
    symbol: str, closes: Sequence[float | str], start: datetime = DAY0, volume: int = 1000
) -> list[Bar]:
    out = []
    for i, c in enumerate(closes):
        close = Decimal(str(c))
        out.append(
            Bar(
                symbol=symbol,
                timeframe=Timeframe.D1,
                ts=start + timedelta(days=i),
                open=close,
                high=close + 1,
                low=max(close - 1, Decimal("0.01")),
                close=close,
                volume=Decimal(volume + i),
            )
        )
    return out


@pytest.fixture
def make_bars() -> BarsFactory:
    return bars_from_closes


@pytest.fixture
async def repos(tmp_path: Path) -> AsyncIterator[Repositories]:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'dec.db'}")
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
    """configs/ with the repo's real decision agents and prompt template."""
    root = tmp_path / "configs"
    (root / "agents" / "prompts").mkdir(parents=True)
    shutil.copy(REPO_CONFIGS / "agents" / "prompts" / "decision_v1.j2", root / "agents" / "prompts")
    for agent_id in ("value_investor", "trend_follower"):
        shutil.copy(REPO_CONFIGS / "agents" / f"{agent_id}.yaml", root / "agents")
    (root / "llm_providers.yaml").write_text(
        yaml.safe_dump({"providers": {"anthropic": {"kind": "anthropic"}}}), encoding="utf-8"
    )
    return ConfigStore(root, env={})
