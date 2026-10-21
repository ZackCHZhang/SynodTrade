"""Per-pipeline watchlists: stocks followed across runs, fed by stock selection or by hand."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime, timedelta

from sqlalchemy import select

from synodtrade_core.models import WatchlistEntry
from synodtrade_database.models import WatchlistRow
from synodtrade_database.repositories.base import Repository, as_of_or_now, row_dict

_FIELDS = tuple(WatchlistEntry.model_fields)


def _entry(row: WatchlistRow) -> WatchlistEntry:
    data = row_dict(row)
    return WatchlistEntry.model_validate({k: data[k] for k in _FIELDS})


class WatchlistRepository(Repository):
    async def get_all(self, pipeline_name: str) -> list[WatchlistEntry]:
        """Every entry of a pipeline (also removed ones), most recently active first."""
        stmt = select(WatchlistRow).where(WatchlistRow.pipeline_name == pipeline_name)
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return sorted(
            (_entry(r) for r in rows),
            key=lambda e: (not e.active, -e.last_seen.timestamp(), e.symbol),
        )

    async def get_active(
        self, pipeline_name: str, as_of: datetime | None = None
    ) -> list[WatchlistEntry]:
        """Entries on the list at `as_of` (default now), pinned first, then by recency."""
        cutoff = as_of_or_now(as_of)
        entries = [
            e
            for e in await self.get_all(pipeline_name)
            if e.added_at <= cutoff and (e.removed_at is None or e.removed_at > cutoff)
        ]
        return sorted(entries, key=lambda e: (not e.pinned, -e.last_seen.timestamp(), e.symbol))

    async def record_selection(
        self,
        pipeline_name: str,
        picks: Sequence[tuple[str, float | None, str | None]],
        at: datetime,
    ) -> list[str]:
        """Add or refresh the picked symbols `(symbol, score, reason)`; returns new ones."""
        added: list[str] = []
        async with self._db.transaction() as s:
            for symbol, score, reason in picks:
                symbol = symbol.upper()
                row = (
                    await s.execute(
                        select(WatchlistRow).where(
                            WatchlistRow.pipeline_name == pipeline_name,
                            WatchlistRow.symbol == symbol,
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    row = WatchlistRow(pipeline_name=pipeline_name, symbol=symbol, added_at=at)
                    s.add(row)
                    row.times_selected = 0
                    row.pinned = False
                    added.append(symbol)
                elif row.removed_at is not None:  # back on the list: a fresh entry
                    row.added_at, row.times_selected = at, 0
                    row.removed_at = row.removed_reason = None
                    added.append(symbol)
                row.last_selected_at = at
                row.times_selected += 1
                row.last_score = score
                row.last_reason = reason
                row.updated_at = at
        return added

    async def expire(
        self,
        pipeline_name: str,
        at: datetime,
        *,
        max_age: timedelta,
        max_size: int | None = None,
        keep: Collection[str] = (),
    ) -> list[str]:
        """Remove entries not picked within `max_age`, then the stalest ones beyond
        `max_size`. Pinned entries and `keep` (e.g. held stocks) always stay."""
        protected = {s.upper() for s in keep}
        active = await self.get_active(pipeline_name, at)
        removable = [e for e in active if not e.pinned and e.symbol not in protected]
        reasons = {e.symbol: f"not selected for {max_age.days} days" for e in removable
                   if e.last_seen < at - max_age}  # fmt: skip
        if max_size is not None:
            remaining = [e for e in active if e.symbol not in reasons]
            excess = len(remaining) - max_size
            if excess > 0:
                stalest = sorted(
                    (e for e in removable if e.symbol not in reasons), key=lambda e: e.last_seen
                )
                for e in stalest[:excess]:
                    reasons[e.symbol] = f"list full (max {max_size})"
        for symbol, reason in reasons.items():
            await self.remove(pipeline_name, symbol, at, reason)
        return sorted(reasons)

    async def add(
        self,
        pipeline_name: str,
        symbol: str,
        at: datetime,
        *,
        pinned: bool = False,
        note: str | None = None,
    ) -> WatchlistEntry:
        """Add by hand (or update pin/note of an existing entry)."""
        symbol = symbol.strip().upper()
        async with self._db.transaction() as s:
            row = (
                await s.execute(
                    select(WatchlistRow).where(
                        WatchlistRow.pipeline_name == pipeline_name, WatchlistRow.symbol == symbol
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = WatchlistRow(
                    pipeline_name=pipeline_name, symbol=symbol, added_at=at, times_selected=0
                )
                s.add(row)
            elif row.removed_at is not None:
                row.added_at, row.times_selected, row.last_selected_at = at, 0, None
                row.removed_at = row.removed_reason = None
            row.pinned = pinned
            if note is not None:
                row.note = note or None
            row.updated_at = at
            await s.flush()
            return _entry(row)

    async def remove(
        self, pipeline_name: str, symbol: str, at: datetime, reason: str = "removed by hand"
    ) -> bool:
        async with self._db.transaction() as s:
            row = (
                await s.execute(
                    select(WatchlistRow).where(
                        WatchlistRow.pipeline_name == pipeline_name,
                        WatchlistRow.symbol == symbol.upper(),
                        WatchlistRow.removed_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return False
            row.removed_at, row.removed_reason, row.pinned = at, reason, False
            row.updated_at = at
            return True
