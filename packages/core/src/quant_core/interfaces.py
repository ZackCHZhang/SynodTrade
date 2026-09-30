"""Protocols implemented by other packages."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from quant_core.models import Candidate, PipelineContext, SentimentItem, Timeframe


@runtime_checkable
class Stage(Protocol):
    """One pipeline step. Reads earlier outputs from the context and appends its own."""

    name: str

    async def run(self, ctx: PipelineContext) -> PipelineContext: ...


@runtime_checkable
class SentimentSource(Protocol):
    name: str

    async def fetch(self, symbols: Sequence[str], since: datetime) -> list[SentimentItem]: ...


@runtime_checkable
class CandidateSource(Protocol):
    """Proposes symbols for the selection stage (a fixed list, a market scanner...)."""

    name: str

    async def fetch(self, as_of: datetime) -> list[Candidate]: ...


@runtime_checkable
class BarsRefresher(Protocol):
    """Brings stored bars of arbitrary symbols up to date (implemented by market data), so
    stages outside the market data package can ask for bars of symbols not in the universe."""

    async def refresh_bars(
        self, symbols: Sequence[str], *, timeframe: Timeframe, lookback: timedelta, now: datetime
    ) -> dict[str, str]:
        """Returns {symbol: error} for the symbols that could not be updated."""
        ...
