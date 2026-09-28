"""Alembic environment (async). The URL comes from the Alembic config or QUANT_DATABASE_URL."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from quant_database.engine import DATABASE_URL_ENV
from quant_database.migrate import include_name
from quant_database.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise RuntimeError(f"no database URL: pass --url or set {DATABASE_URL_ENV}")
    return url


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        include_name=include_name,
        **kwargs,
    )


def run_migrations_offline() -> None:
    url = _url()
    _configure(url=url, literal_binds=True, render_as_batch=url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    # SQLite cannot ALTER most things in place; batch mode recreates tables instead.
    _configure(connection=connection, render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
