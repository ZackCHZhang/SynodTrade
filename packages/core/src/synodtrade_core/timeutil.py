"""Timezone rules: every datetime is tz-aware; storage and models use UTC.

Exchange schedules are defined in America/New_York; human-facing logs also show Europe/Berlin.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, AwareDatetime

EXCHANGE_TZ = ZoneInfo("America/New_York")
DISPLAY_TZ = ZoneInfo("Europe/Berlin")


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_utc(value: datetime) -> datetime:
    """Convert an aware datetime to UTC; naive datetimes are a programming error."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"naive datetime not allowed: {value!r}")
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(to_utc)]
"""Pydantic field type: rejects naive datetimes and normalises to UTC."""
