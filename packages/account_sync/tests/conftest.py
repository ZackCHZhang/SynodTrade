"""Shared fixtures for quant_account_sync tests: SQLite and the repo's configs (no network)."""

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from quant_core.config import ConfigStore
from quant_database import Database, Repositories

REPO_CONFIGS = Path(__file__).resolve().parents[3] / "configs"
ENV = {"IBKR_ACCOUNT": "DU1234567", "ANTHROPIC_API_KEY": "k", "DEEPSEEK_API_KEY": "k"}


@pytest.fixture
def configs(tmp_path: Path) -> Path:
    target = tmp_path / "configs"
    shutil.copytree(REPO_CONFIGS, target, ignore=shutil.ignore_patterns(".web_backups"))
    return target


@pytest.fixture
def store(configs: Path) -> ConfigStore:
    return ConfigStore(configs, env=ENV)


@pytest.fixture
async def repos(tmp_path: Path) -> AsyncIterator[Repositories]:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'sync.db'}")
    await db.create_all()
    yield Repositories.create(db)
    await db.dispose()
