"""Programmatic Alembic access; migrations ship inside this package."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Tables that share the database but are not ours (e.g. the scheduler's job store):
# autogenerate must never propose creating or dropping them.
FOREIGN_TABLES = frozenset({"apscheduler_jobs"})


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    return not (type_ == "table" and name in FOREIGN_TABLES)


def alembic_config(url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if url:
        # ConfigParser interpolation: a literal % in a password must be doubled.
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade(url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str | None = None, revision: str = "-1") -> None:
    command.downgrade(alembic_config(url), revision)


def current(url: str | None = None) -> None:
    command.current(alembic_config(url), verbose=True)


def revision(message: str, url: str | None = None, autogenerate: bool = True) -> None:
    command.revision(alembic_config(url), message=message, autogenerate=autogenerate)
