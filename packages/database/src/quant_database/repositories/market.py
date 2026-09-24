"""Instruments, bars, quotes, account and position snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import Select, func, select

from quant_core.models import AccountSnapshot, Bar, Instrument, Position, Quote, Timeframe
from quant_database.models import (
    AccountSnapshotRow,
    InstrumentRow,
    MarketBarRow,
    PositionSnapshotRow,
    QuoteSnapshotRow,
)
from quant_database.repositories.base import (
    Repository,
    as_of_or_now,
    instrument_ids,
    row_dict,
    table_of,
    upsert_insert,
)

TIMEFRAME_DURATION = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.D1: timedelta(days=1),
    Timeframe.W1: timedelta(days=7),
}


class InstrumentRepository(Repository):
    async def upsert(self, instrument: Instrument) -> int:
        values = instrument.model_dump()
        async with self._db.transaction() as s:
            await instrument_ids(s, self._db.dialect, [instrument.symbol])
            row = (
                await s.execute(
                    select(InstrumentRow).where(InstrumentRow.symbol == values["symbol"])
                )
            ).scalar_one()
            for key, value in values.items():
                setattr(row, key, value)
            return row.id

    async def get(self, symbol: str) -> Instrument | None:
        async with self._db.transaction() as s:
            row = (
                await s.execute(select(InstrumentRow).where(InstrumentRow.symbol == symbol.upper()))
            ).scalar_one_or_none()
        if row is None:
            return None
        data = row_dict(row)
        return Instrument.model_validate({k: data[k] for k in Instrument.model_fields})

    async def list(self) -> list[Instrument]:
        async with self._db.transaction() as s:
            rows = (await s.execute(select(InstrumentRow).order_by(InstrumentRow.symbol))).scalars()
            return [
                Instrument.model_validate({k: getattr(r, k) for k in Instrument.model_fields})
                for r in rows
            ]


class BarRepository(Repository):
    """Historical bars. `ts` is the bar start; a bar is only visible "as of" a moment once it
    has completed (ts + timeframe <= as_of), so live runs never see a half-formed bar and a
    future replay mode cannot peek ahead.
    """

    async def upsert(self, bars: Sequence[Bar]) -> int:
        if not bars:
            return 0
        dialect = self._db.dialect
        async with self._db.transaction() as s:
            ids = await instrument_ids(s, dialect, (b.symbol for b in bars))
            rows = [
                {
                    "instrument_id": ids[b.symbol],
                    "timeframe": b.timeframe.value,
                    "ts": b.ts,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
                for b in bars
            ]
            stmt = upsert_insert(dialect, table_of(MarketBarRow))
            stmt = stmt.on_conflict_do_update(
                index_elements=["instrument_id", "timeframe", "ts"],
                set_={k: stmt.excluded[k] for k in ("open", "high", "low", "close", "volume")},
            )
            await s.execute(stmt, rows)
        return len(rows)

    @staticmethod
    def _query(symbol: str, timeframe: Timeframe) -> Select[tuple[MarketBarRow]]:
        return (
            select(MarketBarRow)
            .join(InstrumentRow, InstrumentRow.id == MarketBarRow.instrument_id)
            .where(
                InstrumentRow.symbol == symbol.upper(), MarketBarRow.timeframe == timeframe.value
            )
        )

    @staticmethod
    def _to_bar(row: MarketBarRow, symbol: str, timeframe: Timeframe) -> Bar:
        return Bar(
            symbol=symbol,
            timeframe=timeframe,
            ts=row.ts,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )

    async def get_latest_bars(
        self,
        symbol: str,
        n: int,
        timeframe: Timeframe = Timeframe.D1,
        as_of: datetime | None = None,
    ) -> list[Bar]:
        """The `n` most recent completed bars as of `as_of` (default now), oldest first."""
        cutoff = as_of_or_now(as_of) - TIMEFRAME_DURATION[timeframe]
        stmt = (
            self._query(symbol, timeframe)
            .where(MarketBarRow.ts <= cutoff)
            .order_by(MarketBarRow.ts.desc())
            .limit(n)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [self._to_bar(r, symbol.upper(), timeframe) for r in reversed(rows)]

    async def get_bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        """Bars with start <= ts < end, oldest first."""
        stmt = (
            self._query(symbol, timeframe)
            .where(MarketBarRow.ts >= start, MarketBarRow.ts < end)
            .order_by(MarketBarRow.ts)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [self._to_bar(r, symbol.upper(), timeframe) for r in rows]

    async def get_bar_span(
        self, symbol: str, timeframe: Timeframe
    ) -> tuple[datetime, datetime] | None:
        """(first ts, last ts) stored, for incremental updates; None if no bars."""
        stmt = (
            select(func.min(MarketBarRow.ts), func.max(MarketBarRow.ts))
            .join(InstrumentRow, InstrumentRow.id == MarketBarRow.instrument_id)
            .where(
                InstrumentRow.symbol == symbol.upper(), MarketBarRow.timeframe == timeframe.value
            )
        )
        async with self._db.transaction() as s:
            first, last = (await s.execute(stmt)).one()
        if first is None or last is None:
            return None
        return first, last


class QuoteRepository(Repository):
    async def add(self, quotes: Sequence[Quote]) -> None:
        if not quotes:
            return
        async with self._db.transaction() as s:
            ids = await instrument_ids(s, self._db.dialect, (q.symbol for q in quotes))
            s.add_all(
                QuoteSnapshotRow(
                    instrument_id=ids[q.symbol],
                    ts=q.ts,
                    bid=q.bid,
                    ask=q.ask,
                    last=q.last,
                    bid_size=q.bid_size,
                    ask_size=q.ask_size,
                )
                for q in quotes
            )

    async def get_latest_quote(self, symbol: str, as_of: datetime | None = None) -> Quote | None:
        stmt = (
            select(QuoteSnapshotRow)
            .join(InstrumentRow, InstrumentRow.id == QuoteSnapshotRow.instrument_id)
            .where(
                InstrumentRow.symbol == symbol.upper(), QuoteSnapshotRow.ts <= as_of_or_now(as_of)
            )
            .order_by(QuoteSnapshotRow.ts.desc(), QuoteSnapshotRow.id.desc())
            .limit(1)
        )
        async with self._db.transaction() as s:
            row = (await s.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return Quote(
            symbol=symbol,
            ts=row.ts,
            bid=row.bid,
            ask=row.ask,
            last=row.last,
            bid_size=row.bid_size,
            ask_size=row.ask_size,
        )


class AccountRepository(Repository):
    """Account snapshots and the positions captured at the same instant.

    A snapshot is written atomically with its positions (possibly none), so "latest positions"
    means the positions of the latest account snapshot — an empty book is distinguishable
    from missing data.
    """

    async def add_snapshot(self, account: AccountSnapshot, positions: Sequence[Position]) -> None:
        for p in positions:
            if p.account_id != account.account_id or p.ts != account.ts:
                raise ValueError("positions must share the account snapshot's account_id and ts")
        async with self._db.transaction() as s:
            ids = await instrument_ids(s, self._db.dialect, (p.symbol for p in positions))
            s.add(AccountSnapshotRow(**account.model_dump()))
            s.add_all(
                PositionSnapshotRow(
                    account_id=p.account_id,
                    instrument_id=ids[p.symbol],
                    ts=p.ts,
                    qty=p.qty,
                    avg_cost=p.avg_cost,
                    market_price=p.market_price,
                )
                for p in positions
            )

    async def get_latest_account(
        self, account_id: str, as_of: datetime | None = None
    ) -> AccountSnapshot | None:
        stmt = (
            select(AccountSnapshotRow)
            .where(
                AccountSnapshotRow.account_id == account_id,
                AccountSnapshotRow.ts <= as_of_or_now(as_of),
            )
            .order_by(AccountSnapshotRow.ts.desc(), AccountSnapshotRow.id.desc())
            .limit(1)
        )
        async with self._db.transaction() as s:
            row = (await s.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        data = row_dict(row)
        return AccountSnapshot.model_validate({k: data[k] for k in AccountSnapshot.model_fields})

    async def get_latest_positions(
        self, account_id: str, as_of: datetime | None = None
    ) -> list[Position] | None:
        """Positions at the latest snapshot; None if there is no snapshot at all."""
        account = await self.get_latest_account(account_id, as_of)
        if account is None:
            return None
        stmt = (
            select(PositionSnapshotRow, InstrumentRow.symbol)
            .join(InstrumentRow, InstrumentRow.id == PositionSnapshotRow.instrument_id)
            .where(
                PositionSnapshotRow.account_id == account_id,
                PositionSnapshotRow.ts == account.ts,
            )
            .order_by(InstrumentRow.symbol)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).tuples().all()
        return [
            Position(
                account_id=row.account_id,
                symbol=symbol,
                qty=row.qty,
                avg_cost=row.avg_cost,
                ts=row.ts,
                market_price=row.market_price,
            )
            for row, symbol in rows
        ]
