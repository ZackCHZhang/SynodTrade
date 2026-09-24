"""Shared fixtures for quant_market_data tests (SQLite, fake provider; no network)."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from quant_database import Database, Repositories


@pytest.fixture
async def repos(tmp_path: Path) -> AsyncIterator[Repositories]:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'md.db'}")
    await db.create_all()
    yield Repositories.create(db)
    await db.dispose()
