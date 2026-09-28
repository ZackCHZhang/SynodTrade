"""Shared fixtures for quant_pipeline tests: the repo's real configs, SQLite, fakes only."""

import shutil
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from quant_core.config import ConfigStore
from quant_core.llm import FakeLLMClient, LLMClientPool, LLMRequest
from quant_core.models import SentimentItem
from quant_database import Database
from quant_pipeline import offline_market_data, schema_reply
from quant_risk import AlwaysOpenClock
from quant_sentiment.sources import FakeSentimentSource
from quant_trading import SimulatedBroker

REPO_CONFIGS = Path(__file__).resolve().parents[3] / "configs"
AS_OF = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)  # Thursday 10:00 New York
ENV = {"IBKR_ACCOUNT": "DU1234567", "ANTHROPIC_API_KEY": "test-key"}
UNIVERSE = ["AAPL", "MSFT", "GOOGL", "NVDA"]

Fakes = Callable[..., dict[str, Any]]


@pytest.fixture
def configs(tmp_path: Path) -> Path:
    """A private copy of the repo's configs/ (tests may edit it)."""
    target = tmp_path / "configs"
    shutil.copytree(REPO_CONFIGS, target)
    return target


@pytest.fixture
def store(configs: Path) -> ConfigStore:
    return ConfigStore(configs, env=ENV)


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'pipeline.db'}")
    await database.create_all()
    yield database
    await database.dispose()


def bullish_llm(request: LLMRequest) -> str:
    """Every decision agent says buy with high confidence; risk officers approve."""
    return schema_reply(request, decision_action="buy", decision_confidence=0.9)


def aapl_posts() -> list[SentimentItem]:
    return [
        SentimentItem(
            source="reddit",
            external_id=f"p{i}",
            symbol="AAPL",
            text=f"$AAPL looks strong after earnings, take {i}",
            created_at=AS_OF - timedelta(hours=i + 1),
            author=f"user{i}",
            score=10 * i,
        )
        for i in range(3)
    ]


@pytest.fixture
def fakes() -> Fakes:
    """Service overrides that make a full run possible without network or keys."""

    def make(
        *,
        llm: Callable[[LLMRequest], str] = bullish_llm,
        broker: Any = None,
        sources: dict[str, Any] | None = None,
        market_data: Any = None,
    ) -> dict[str, Any]:
        pool = LLMClientPool({}, env={})
        pool.set("anthropic", FakeLLMClient(default=llm))
        default_sources = {
            "reddit": FakeSentimentSource("reddit", aapl_posts()),
            "stocktwits": FakeSentimentSource("stocktwits"),
            "ibkr_news": FakeSentimentSource("ibkr_news"),
        }
        return {
            "llm": pool,
            "market_data": market_data or offline_market_data(UNIVERSE, AS_OF),
            "sentiment_sources": default_sources if sources is None else sources,
            "broker": broker or SimulatedBroker(commission=Decimal(1)),
            "market_clock": AlwaysOpenClock(),
        }

    return make
