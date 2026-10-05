"""Fixtures for quant_webapi: a copy of the repo configs, temporary SQLite databases and an
in-process client (no network; the app runs in TestClient's event loop)."""

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from quant_webapi.app import WebSettings, create_app

REPO_CONFIGS = Path(__file__).resolve().parents[3] / "configs"
ENV = {"IBKR_ACCOUNT": "DU1234567", "ANTHROPIC_API_KEY": "test-key", "DEEPSEEK_API_KEY": "k"}


@pytest.fixture
def configs(tmp_path: Path) -> Path:
    target = tmp_path / "configs"
    shutil.copytree(REPO_CONFIGS, target, ignore=shutil.ignore_patterns(".web_backups"))
    return target


def _client(tmp_path: Path, configs: Path, overrides: dict[str, Any] | None = None) -> TestClient:
    settings = WebSettings(
        configs=configs,
        db_url=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}",
        offline_db_url=f"sqlite+aiosqlite:///{tmp_path / 'offline.db'}",
        env=ENV,
        create_tables=True,
        configure_logs=False,
        overrides=overrides or {},
    )
    return TestClient(create_app(settings))


ClientFactory = Callable[[dict[str, Any]], TestClient]


@pytest.fixture
def make_client(tmp_path: Path, configs: Path) -> ClientFactory:
    """A client whose pipeline runs use the given service overrides."""
    return lambda overrides: _client(tmp_path, configs, overrides)


@pytest.fixture
def client(tmp_path: Path, configs: Path) -> Iterator[TestClient]:
    with _client(tmp_path, configs) as c:
        yield c
