"""The Alembic migrations must produce exactly the schema the ORM models describe."""

import re
import sqlite3
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from synodtrade_database import migrate
from synodtrade_database.cli import main
from synodtrade_database.models import Base


def _sync_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _async_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path}"


def test_upgrade_matches_models(tmp_path: Path) -> None:
    db_file = tmp_path / "m.db"
    migrate.upgrade(_async_url(db_file))

    engine = create_engine(_sync_url(db_file))
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    engine.dispose()
    assert diff == []


def test_downgrade_removes_everything(tmp_path: Path) -> None:
    db_file = tmp_path / "m.db"
    url = _async_url(db_file)
    migrate.upgrade(url)
    migrate.downgrade(url, "base")
    engine = create_engine(_sync_url(db_file))
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert tables == {"alembic_version"}
    migrate.upgrade(url)  # and back up again


def _version(db_file: Path) -> str | None:
    with sqlite3.connect(db_file) as conn:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return None if row is None else str(row[0])


def test_cli(tmp_path: Path) -> None:
    db_file = tmp_path / "cli.db"
    url = _async_url(db_file)
    main(["upgrade", "--url", url])
    assert _version(db_file) == "0006"
    main(["current", "--url", url])
    main(["downgrade", "--url", url, "--revision", "base"])
    assert _version(db_file) is None


def test_every_table_is_migrated() -> None:
    versions = Path(migrate.MIGRATIONS_DIR / "versions")
    source = "".join(p.read_text(encoding="utf-8") for p in versions.glob("*.py"))
    for table in Base.metadata.tables:
        assert re.search(rf"create_table\(\s*[\"']{table}[\"']", source), table


def test_foreign_tables_are_ignored_by_autogenerate(tmp_path: Path) -> None:
    """The scheduler's `apscheduler_jobs` table must never show up as a diff to drop."""
    from sqlalchemy import text

    assert not migrate.include_name("apscheduler_jobs", "table", {})
    assert migrate.include_name("orders", "table", {})
    db_file = tmp_path / "m.db"
    migrate.upgrade(_async_url(db_file))
    engine = create_engine(_sync_url(db_file))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE apscheduler_jobs (id VARCHAR PRIMARY KEY)"))
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn, opts={"compare_type": True, "include_name": migrate.include_name}
        )
        assert compare_metadata(ctx, Base.metadata) == []
    engine.dispose()
