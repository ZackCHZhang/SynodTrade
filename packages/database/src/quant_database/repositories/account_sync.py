"""History of account synchronisations (see the `quant_account_sync` package)."""

from __future__ import annotations

from sqlalchemy import func, select

from quant_database.models import AccountSyncRow
from quant_database.records import AccountSync
from quant_database.repositories.base import Repository, row_dict


def _to_record(row: AccountSyncRow) -> AccountSync:
    return AccountSync.model_validate(row_dict(row))


class AccountSyncRepository(Repository):
    async def add(self, sync: AccountSync) -> AccountSync:
        data = sync.model_dump(mode="python", exclude={"id"})
        async with self._db.transaction() as s:
            row = AccountSyncRow(**data)
            s.add(row)
            await s.flush()
            return _to_record(row)

    async def recent(self, limit: int = 50, account_id: str | None = None) -> list[AccountSync]:
        stmt = select(AccountSyncRow).order_by(
            AccountSyncRow.started_at.desc(), AccountSyncRow.id.desc()
        )
        if account_id is not None:
            stmt = stmt.where(AccountSyncRow.account_id == account_id)
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt.limit(limit))).scalars().all()
        return [_to_record(r) for r in rows]

    async def latest(self) -> list[AccountSync]:
        """The most recent synchronisation of every account."""
        newest = (
            select(func.max(AccountSyncRow.id))
            .group_by(AccountSyncRow.account_id)
            .scalar_subquery()
        )
        stmt = (
            select(AccountSyncRow)
            .where(AccountSyncRow.id.in_(newest))
            .order_by(AccountSyncRow.account_id)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [_to_record(r) for r in rows]
