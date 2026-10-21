"""Exchange sessions: is the market open, and where do the trading day/week start."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from functools import cache
from typing import Any, Protocol, runtime_checkable

from synodtrade_core.timeutil import EXCHANGE_TZ


@runtime_checkable
class MarketClock(Protocol):
    def is_open(self, ts: datetime) -> bool: ...


@cache
def _calendar(code: str) -> Any:
    import exchange_calendars  # heavy import (pandas); only when a real calendar is used

    return exchange_calendars.get_calendar(code)


class ExchangeCalendarClock:
    """Regular trading hours of a real exchange calendar (holidays, half days included)."""

    def __init__(self, calendar: str = "XNYS") -> None:
        self.calendar = calendar

    def is_open(self, ts: datetime) -> bool:
        import pandas as pd

        return bool(_calendar(self.calendar).is_open_on_minute(pd.Timestamp(ts)))


class AlwaysOpenClock:
    """For dry runs and tests that should not depend on the time of day."""

    def is_open(self, ts: datetime) -> bool:
        return True


def trading_day_start(ts: datetime) -> datetime:
    """Midnight in the exchange timezone of `ts`'s trading day, as UTC."""
    local = ts.astimezone(EXCHANGE_TZ)
    return datetime.combine(local.date(), time(0), tzinfo=EXCHANGE_TZ).astimezone(UTC)


def trading_week_start(ts: datetime) -> datetime:
    """Monday midnight (exchange timezone) of `ts`'s week, as UTC."""
    local = ts.astimezone(EXCHANGE_TZ)
    monday = local.date() - timedelta(days=local.weekday())
    return datetime.combine(monday, time(0), tzinfo=EXCHANGE_TZ).astimezone(UTC)
