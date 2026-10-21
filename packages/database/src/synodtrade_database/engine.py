"""Async engine / session management."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import Connection, event, inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.schema import CreateColumn

from synodtrade_database.models import Base

DATABASE_URL_ENV = "SYNODTRADE_DATABASE_URL"


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _add_missing_columns(conn: Connection) -> None:
    existing_tables = set(inspect(conn).get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {c["name"] for c in inspect(conn).get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            if not column.nullable and column.server_default is None:
                raise RuntimeError(
                    f"{table.name}.{column.name} is missing and has no server default; "
                    "run the Alembic migrations or recreate this database"
                )
            ddl = CreateColumn(column).compile(dialect=conn.dialect)
            conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {ddl}"))


class Database:
    """Owns the engine. Use `transaction()` for a session that commits on success."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(url, echo=echo)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **kwargs: Any) -> Database:
        env = os.environ if env is None else env
        url = env.get(DATABASE_URL_ENV)
        if not url:
            raise RuntimeError(f"{DATABASE_URL_ENV} is not set")
        return cls(url, **kwargs)

    @property
    def dialect(self) -> str:
        return self.engine.dialect.name

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        async with self._sessions.begin() as session:
            yield session

    async def create_all(self) -> None:
        """Create tables directly from the ORM (tests/dev). Production uses Alembic.

        Plain `metadata.create_all` skips existing tables, so a dev database made before a
        column was added would break on every query; missing columns are added here too.
        """
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_add_missing_columns)

    async def drop_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def ping(self) -> bool:
        """Health check used by the scheduler before starting a run."""
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            return False
        return True

    async def dispose(self) -> None:
        await self.engine.dispose()
