"""Shared fixtures for quant_trading tests (SQLite, simulated brokers; no network)."""

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from quant_core.models import Bar, Quote, RunMode, Timeframe
from quant_database import Database, PipelineRun, Repositories

NOW = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)  # a Thursday, not today's wall-clock date
D = Decimal


@pytest.fixture
async def repos(tmp_path: Path) -> AsyncIterator[Repositories]:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'trade.db'}")
    await db.create_all()
    yield Repositories.create(db)
    await db.dispose()


@pytest.fixture
def new_run(repos: Repositories) -> Callable[..., Awaitable[UUID]]:
    async def create(as_of: datetime = NOW, mode: RunMode = RunMode.DRY_RUN) -> UUID:
        rid = uuid4()
        await repos.runs.start_run(
            PipelineRun(
                run_id=rid,
                pipeline_name="long_term_stocks",
                mode=mode,
                config_hash="0" * 64,
                config={},
                as_of=as_of,
                started_at=as_of,
            )
        )
        return rid

    return create


@pytest.fixture
def seed_market(repos: Repositories) -> Callable[..., Awaitable[None]]:
    """Daily bars (last completed yesterday) and optional fresh quotes."""

    async def seed(
        prices: dict[str, str], quotes: dict[str, tuple[str, str]] | None = None
    ) -> None:
        yesterday = datetime(2026, 9, 30, 4, 0, tzinfo=UTC)
        bars = [
            Bar(
                symbol=s,
                timeframe=Timeframe.D1,
                ts=yesterday - timedelta(days=i),
                open=D(p),
                high=D(p) + 1,
                low=D(p) - 1,
                close=D(p),
                volume=D(1_000_000),
            )
            for s, p in prices.items()
            for i in range(5)
        ]
        await repos.bars.upsert(bars)
        await repos.quotes.add(
            [
                Quote(symbol=s, ts=NOW - timedelta(minutes=1), bid=D(b), ask=D(a))
                for s, (b, a) in (quotes or {}).items()
            ]
        )

    return seed
