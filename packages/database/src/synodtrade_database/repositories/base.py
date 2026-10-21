"""Shared helpers for repositories."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Table, inspect, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from synodtrade_core.timeutil import utcnow
from synodtrade_database.engine import Database
from synodtrade_database.models import Base, InstrumentRow


class Repository:
    def __init__(self, db: Database) -> None:
        self._db = db


def upsert_insert(dialect: str, table: Table) -> Any:
    """INSERT supporting `on_conflict_do_nothing/do_update` for the supported dialects.

    The only place with dialect-specific SQL; everything else is portable Core/ORM.
    """
    if dialect == "postgresql":
        return postgresql.insert(table)
    if dialect == "sqlite":
        return sqlite.insert(table)
    raise NotImplementedError(f"upserts are not implemented for dialect {dialect!r}")


def table_of(model: type[Base]) -> Table:
    table = model.__table__
    assert isinstance(table, Table)
    return table


def row_dict(row: Base) -> dict[str, Any]:
    """Mapped attribute name -> value for an ORM row."""
    return {attr.key: getattr(row, attr.key) for attr in inspect(row).mapper.column_attrs}


def uuid_list(values: Iterable[UUID]) -> list[str]:
    return [str(v) for v in values]


def as_of_or_now(as_of: datetime | None) -> datetime:
    return as_of if as_of is not None else utcnow()


async def instrument_ids(
    session: AsyncSession, dialect: str, symbols: Iterable[str], *, create: bool = True
) -> dict[str, int]:
    """Map symbols to instrument ids, creating bare instruments for unknown symbols."""
    wanted = sorted({s.upper() for s in symbols})
    if not wanted:
        return {}
    if create:
        stmt = upsert_insert(dialect, table_of(InstrumentRow)).on_conflict_do_nothing(
            index_elements=["symbol"]
        )
        await session.execute(stmt, [{"symbol": s, "updated_at": utcnow()} for s in wanted])
    rows = await session.execute(
        select(InstrumentRow.symbol, InstrumentRow.id).where(InstrumentRow.symbol.in_(wanted))
    )
    return {symbol: id_ for symbol, id_ in rows.tuples()}
