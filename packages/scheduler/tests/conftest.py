"""Shared fixtures for synodtrade_scheduler tests (real exchange calendar, no network)."""

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from synodtrade_core.config import ConfigStore
from synodtrade_database import Database

REPO_CONFIGS = Path(__file__).resolve().parents[3] / "configs"
ENV = {"IBKR_ACCOUNT": "DU1234567", "ANTHROPIC_API_KEY": "test-key"}


@pytest.fixture
def configs(tmp_path: Path) -> Path:
    target = tmp_path / "configs"
    shutil.copytree(REPO_CONFIGS, target)
    return target


@pytest.fixture
def store(configs: Path) -> ConfigStore:
    return ConfigStore(configs, env=ENV)


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'sched.db'}")
    await database.create_all()
    yield database
    await database.dispose()
