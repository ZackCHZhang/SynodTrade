"""Portable column types.

- `DecimalType`: exact decimals. PostgreSQL NUMERIC; on SQLite a string, because SQLite's
  NUMERIC affinity silently converts to float. Consequence: never do arithmetic or ordering on
  decimal columns in SQL; load rows and compute in Python with Decimal.
- `UtcDateTime`: rejects naive datetimes, stores UTC, always returns aware UTC datetimes
  (SQLite has no timezone support, so the zone is re-attached on read).
- `JSONType`: JSON, stored as JSONB on PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Dialect, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator, TypeEngine

JSONType = JSON().with_variant(JSONB(), "postgresql")

# SQLite only auto-increments INTEGER PRIMARY KEY columns.
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


class DecimalType(TypeDecorator[Decimal]):
    impl = Numeric(28, 10)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(64))
        return dialect.type_descriptor(Numeric(28, 10, asdecimal=True))

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise TypeError(f"expected Decimal, got {type(value).__name__}")
        if not value.is_finite():
            raise ValueError(f"non-finite decimal not allowed: {value}")
        return str(value) if dialect.name == "sqlite" else value

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return value if isinstance(value, Decimal) else Decimal(str(value))


class UtcDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"naive datetime not allowed in the database: {value!r}")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
