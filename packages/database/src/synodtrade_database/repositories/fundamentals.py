"""Company fundamentals snapshots (one row per refresh; reads take the latest as of a time)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select

from synodtrade_core.models import Fundamentals
from synodtrade_database.models import FundamentalsSnapshotRow
from synodtrade_database.repositories.base import Repository, as_of_or_now


class FundamentalsRepository(Repository):
    async def add(self, snapshots: Sequence[Fundamentals]) -> None:
        if not snapshots:
            return
        async with self._db.transaction() as s:
            s.add_all(
                FundamentalsSnapshotRow(
                    symbol=f.symbol,
                    as_of=f.as_of,
                    source=f.source,
                    available=f.available,
                    period_end=f.period_end.isoformat() if f.period_end else None,
                    data=f.model_dump(mode="json"),
                )
                for f in snapshots
            )

    async def get_latest(self, symbol: str, as_of: datetime | None = None) -> Fundamentals | None:
        """The most recent snapshot taken at or before `as_of` (default now)."""
        stmt = (
            select(FundamentalsSnapshotRow)
            .where(
                FundamentalsSnapshotRow.symbol == symbol.upper(),
                FundamentalsSnapshotRow.as_of <= as_of_or_now(as_of),
            )
            .order_by(FundamentalsSnapshotRow.as_of.desc(), FundamentalsSnapshotRow.id.desc())
            .limit(1)
        )
        async with self._db.transaction() as s:
            row = (await s.execute(stmt)).scalar_one_or_none()
        return Fundamentals.model_validate(row.data) if row is not None else None

    async def get_latest_many(
        self, symbols: Sequence[str], as_of: datetime | None = None
    ) -> dict[str, Fundamentals]:
        out: dict[str, Fundamentals] = {}
        for symbol in dict.fromkeys(s.upper() for s in symbols):
            found = await self.get_latest(symbol, as_of)
            if found is not None:
                out[symbol] = found
        return out
