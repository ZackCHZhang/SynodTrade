from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import StatementError

from synodtrade_database import DATABASE_URL_ENV, Database
from synodtrade_database.models import AccountSnapshotRow, InstrumentRow

TS = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)


def _account(**kw: object) -> AccountSnapshotRow:
    values: dict[str, object] = {
        "account_id": "DU1",
        "ts": TS,
        "currency": "USD",
        "nav": Decimal("100000.1234567891"),
        "cash": Decimal("0.1"),
        "buying_power": Decimal("0.2"),
    }
    values.update(kw)
    return AccountSnapshotRow(**values)


async def test_decimals_round_trip_exactly(db: Database) -> None:
    async with db.transaction() as s:
        s.add(_account())
    async with db.transaction() as s:
        row = (await s.execute(select(AccountSnapshotRow))).scalar_one()
    assert row.nav == Decimal("100000.1234567891")
    assert row.cash + row.buying_power == Decimal("0.3")  # would be 0.30000000000000004 as float
    assert isinstance(row.cash, Decimal)


async def test_datetimes_come_back_aware_utc(db: Database) -> None:
    berlin = timezone(timedelta(hours=2))
    async with db.transaction() as s:
        s.add(_account(ts=datetime(2026, 9, 24, 16, 0, tzinfo=berlin)))
    async with db.transaction() as s:
        row = (await s.execute(select(AccountSnapshotRow))).scalar_one()
    assert row.ts == TS
    assert row.ts.tzinfo == UTC


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"ts": datetime(2026, 1, 1)}, "naive datetime"),  # noqa: DTZ001
        ({"nav": 1.5}, "expected Decimal"),
        ({"nav": Decimal("Infinity")}, "non-finite"),
    ],
)
async def test_invalid_values_rejected(
    db: Database, override: dict[str, object], message: str
) -> None:
    with pytest.raises(StatementError, match=message):
        async with db.transaction() as s:
            s.add(_account(**override))


async def test_ping_and_dialect(db: Database) -> None:
    assert await db.ping()
    assert db.dialect in {"sqlite", "postgresql"}


async def test_ping_fails_on_unreachable_db(tmp_path: object) -> None:
    bad = Database("sqlite+aiosqlite:///Z:/definitely/missing/dir/x.db")
    assert not await bad.ping()
    await bad.dispose()


async def test_sqlite_foreign_keys_enforced(db: Database) -> None:
    async with db.transaction() as s:
        fk = (
            (await s.execute(text("PRAGMA foreign_keys"))).scalar() if db.dialect == "sqlite" else 1
        )
    assert fk == 1


async def test_nullable_decimal_and_defaults(db: Database) -> None:
    async with db.transaction() as s:
        s.add(InstrumentRow(symbol="AAPL"))
    async with db.transaction() as s:
        row = (await s.execute(select(InstrumentRow))).scalar_one()
    assert row.lot_size == Decimal(1)
    assert row.con_id is None
    assert row.updated_at.tzinfo == UTC


def test_from_env() -> None:
    db = Database.from_env({DATABASE_URL_ENV: "sqlite+aiosqlite:///:memory:"})
    assert db.dialect == "sqlite"
    with pytest.raises(RuntimeError, match=DATABASE_URL_ENV):
        Database.from_env({})


async def test_create_all_adds_columns_missing_from_older_tables(db: Database) -> None:
    if db.dialect != "sqlite":
        pytest.skip("rebuilds a table with SQLite DDL")
    async with db.transaction() as s:  # stock_selections as created before `watchlist` existed
        await s.execute(text("DROP TABLE stock_selections"))
        await s.execute(
            text(
                "CREATE TABLE stock_selections (id CHAR(32) PRIMARY KEY, run_id CHAR(32),"
                " pipeline_name VARCHAR(64), method VARCHAR(64), candidates JSON,"
                " selected JSON, holdings JSON, scores JSON, rejected JSON, created_at TEXT)"
            )
        )
        await s.execute(
            text(
                "INSERT INTO stock_selections VALUES ('a', NULL, 'p', 'm', '[]', '[]', '[]',"
                " '{}', '{}', '2026-09-24T14:00:00+00:00')"
            )
        )
    await db.create_all()
    async with db.transaction() as s:
        rows = (await s.execute(text("SELECT watchlist FROM stock_selections"))).all()
    assert [tuple(r) for r in rows] == [("[]",)]
    await db.create_all()  # idempotent
