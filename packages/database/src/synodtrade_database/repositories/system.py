"""Operational flags such as the global kill switch."""

from __future__ import annotations

from sqlalchemy import select

from synodtrade_core.timeutil import utcnow
from synodtrade_database.models import SystemFlagRow
from synodtrade_database.repositories.base import Repository

KILL_SWITCH = "kill_switch"


class FlagRepository(Repository):
    async def is_enabled(self, key: str) -> bool:
        async with self._db.transaction() as s:
            row = await s.get(SystemFlagRow, key)
        return bool(row and row.enabled)

    async def set(self, key: str, enabled: bool, reason: str | None = None) -> None:
        async with self._db.transaction() as s:
            row = await s.get(SystemFlagRow, key)
            if row is None:
                s.add(SystemFlagRow(key=key, enabled=enabled, reason=reason, updated_at=utcnow()))
            else:
                row.enabled = enabled
                row.reason = reason
                row.updated_at = utcnow()

    async def get_reason(self, key: str) -> str | None:
        async with self._db.transaction() as s:
            return (
                await s.execute(select(SystemFlagRow.reason).where(SystemFlagRow.key == key))
            ).scalar_one_or_none()

    async def kill_switch_active(self) -> bool:
        return await self.is_enabled(KILL_SWITCH)
