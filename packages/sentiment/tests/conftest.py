"""Shared fixtures for synodtrade_sentiment tests (SQLite, fake sources, fake LLM; no network)."""

import shutil
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import yaml

from synodtrade_core.config import ConfigStore
from synodtrade_core.models import RunMode, SentimentItem
from synodtrade_database import Database, PipelineRun, Repositories

REPO_CONFIGS = Path(__file__).resolve().parents[3] / "configs"
NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)


def post(
    ext: str,
    symbol: str = "AAPL",
    *,
    text: str | None = None,
    score: int = 10,
    hours_ago: float = 1,
    source: str = "reddit",
    author: str | None = "trader1",
) -> SentimentItem:
    return SentimentItem(
        source=source,
        external_id=ext,
        symbol=symbol,
        text=text if text is not None else f"Thoughts on ${symbol}? post {ext} is bullish",
        created_at=NOW - timedelta(hours=hours_ago),
        author=author,
        score=score,
    )


PostFactory = Callable[..., SentimentItem]


@pytest.fixture
def make_post() -> PostFactory:
    return post


@pytest.fixture
async def repos(tmp_path: Path) -> AsyncIterator[Repositories]:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'sent.db'}")
    await db.create_all()
    yield Repositories.create(db)
    await db.dispose()


@pytest.fixture
async def run_id(repos: Repositories) -> UUID:
    rid = uuid4()
    await repos.runs.start_run(
        PipelineRun(
            run_id=rid,
            pipeline_name="p",
            mode=RunMode.DRY_RUN,
            config_hash="0" * 64,
            config={},
            as_of=NOW,
            started_at=NOW,
        )
    )
    return rid


@pytest.fixture
def store(tmp_path: Path) -> ConfigStore:
    """A configs dir with sentiment agents using the repo's real prompt template."""
    root = tmp_path / "configs"
    (root / "agents" / "prompts").mkdir(parents=True)
    shutil.copy(
        REPO_CONFIGS / "agents" / "prompts" / "sentiment_v1.j2", root / "agents" / "prompts"
    )
    (root / "llm_providers.yaml").write_text(
        yaml.safe_dump({"providers": {"anthropic": {"kind": "anthropic"}}}), encoding="utf-8"
    )
    for agent_id in ("retail_mood", "event_extractor"):
        cfg = yaml.safe_load((REPO_CONFIGS / "agents" / f"{agent_id}.yaml").read_text("utf-8"))
        (root / "agents" / f"{agent_id}.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return ConfigStore(root, env={})
