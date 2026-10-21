"""Shared fixtures for synodtrade_database tests.

Every repository test runs against SQLite (a temp file). Set SYNODTRADE_TEST_DATABASE_URL to a
throwaway PostgreSQL database (e.g. postgresql+asyncpg://quant:pw@localhost:5432/synodtrade_test)
and run `python tasks.py integration` to run the same tests against PostgreSQL as well.
"""

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from synodtrade_core.models import RunMode
from synodtrade_database import Database, PipelineRun, Repositories

TEST_PG_ENV = "SYNODTRADE_TEST_DATABASE_URL"
T0 = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)


@pytest.fixture(
    params=["sqlite", pytest.param("postgresql", marks=pytest.mark.integration)],
)
async def db(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Database]:
    if request.param == "sqlite":
        database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    else:
        url = os.environ.get(TEST_PG_ENV)
        if not url:
            pytest.skip(f"{TEST_PG_ENV} not set")
        database = Database(url)
        await database.drop_all()
    await database.create_all()
    yield database
    await database.dispose()


@pytest.fixture
def repos(db: Database) -> Repositories:
    return Repositories.create(db)


@pytest.fixture
def make_run(repos: Repositories) -> Callable[..., Awaitable[UUID]]:
    async def create(pipeline: str = "long_term_stocks", started_at: datetime = T0) -> UUID:
        run_id = uuid4()
        await repos.runs.start_run(
            PipelineRun(
                run_id=run_id,
                pipeline_name=pipeline,
                mode=RunMode.DRY_RUN,
                config_hash="0" * 64,
                config={"name": pipeline},
                as_of=started_at,
                started_at=started_at,
            )
        )
        return run_id

    return create
