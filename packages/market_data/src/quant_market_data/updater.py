"""Incremental data updates: provider -> repositories."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from quant_core.logging import get_logger
from quant_core.models import Instrument, Timeframe
from quant_database import Repositories
from quant_market_data.provider import MarketDataProvider
from quant_market_data.ranges import missing_ranges

log = get_logger(__name__)


@dataclass(slots=True)
class UpdateReport:
    bars_written: dict[str, int] = field(default_factory=dict)  # "SYMBOL/timeframe" -> count
    quotes_written: int = 0
    positions_written: int | None = None  # None: account not updated
    errors: dict[str, str] = field(default_factory=dict)  # symbol or "account" -> message

    @property
    def ok(self) -> bool:
        return not self.errors


class DataUpdater:
    def __init__(self, provider: MarketDataProvider, repos: Repositories) -> None:
        self._provider = provider
        self._repos = repos

    @property
    def provider(self) -> MarketDataProvider:
        return self._provider

    async def sync_instrument(self, symbol: str) -> Instrument:
        """Instrument with a broker con_id, resolved once and then cached in the database."""
        stored = await self._repos.instruments.get(symbol)
        if stored is not None and stored.con_id is not None:
            return stored
        resolved = await self._provider.resolve_instrument(symbol)
        await self._repos.instruments.upsert(resolved)
        log.info("market_data.instrument_resolved", symbol=resolved.symbol, con_id=resolved.con_id)
        return resolved

    async def update_bars(
        self, instrument: Instrument, timeframe: Timeframe, lookback: timedelta, now: datetime
    ) -> int:
        span = await self._repos.bars.get_bar_span(instrument.symbol, timeframe)
        written = 0
        for start, end in missing_ranges(now - lookback, now, span, timeframe):
            bars = await self._provider.fetch_bars(instrument, timeframe, start, end)
            written += await self._repos.bars.upsert(bars)
        return written

    async def refresh_bars(
        self, symbols: Sequence[str], *, timeframe: Timeframe, lookback: timedelta, now: datetime
    ) -> dict[str, str]:
        """Bars only, for any symbols (core `BarsRefresher`, used by stock selection).
        Connects the provider if needed; returns {symbol: error} for failed symbols."""
        await self._provider.connect()
        errors: dict[str, str] = {}
        for symbol in symbols:
            try:
                instrument = await self.sync_instrument(symbol)
                await self.update_bars(instrument, timeframe, lookback, now)
            except Exception as exc:  # one bad symbol must not stop the others
                errors[symbol] = f"{type(exc).__name__}: {exc}"
                log.warning("market_data.refresh_failed", symbol=symbol, error=str(exc))
        return errors

    async def update(
        self,
        symbols: Sequence[str],
        *,
        timeframes: Sequence[Timeframe],
        lookback: timedelta,
        now: datetime,
        quotes: bool = True,
        account_id: str | None = None,
    ) -> UpdateReport:
        """Update everything, continuing past per-symbol failures (reported in `errors`)."""
        report = UpdateReport()
        instruments: list[Instrument] = []
        for symbol in symbols:
            try:
                instrument = await self.sync_instrument(symbol)
                for tf in timeframes:
                    count = await self.update_bars(instrument, tf, lookback, now)
                    report.bars_written[f"{instrument.symbol}/{tf.value}"] = count
                instruments.append(instrument)
            except Exception as exc:  # isolate one bad symbol from the rest
                report.errors[symbol] = f"{type(exc).__name__}: {exc}"
                log.error("market_data.symbol_failed", symbol=symbol, error=str(exc))

        if quotes and instruments:
            try:
                fetched = await self._provider.fetch_quotes(instruments)
                await self._repos.quotes.add(fetched)
                report.quotes_written = len(fetched)
            except Exception as exc:
                report.errors["quotes"] = f"{type(exc).__name__}: {exc}"

        if account_id is not None:
            try:
                data = await self._provider.fetch_account(account_id)
                await self._repos.accounts.add_snapshot(data.account, data.positions)
                report.positions_written = len(data.positions)
            except Exception as exc:
                report.errors["account"] = f"{type(exc).__name__}: {exc}"
        return report
