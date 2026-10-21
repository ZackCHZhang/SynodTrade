"""APScheduler triggers driven by the real exchange calendar.

Both are picklable (they store only codes and numbers) so they can live in the database
job store. Times are computed from the calendar's UTC session opens/closes, so daylight
saving changes, holidays and early closes (e.g. the day after Thanksgiving) are handled.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import cache
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger

from synodtrade_scheduler.config import JobConfig, SchedulesConfig

_SEARCH_DAYS = 45  # sessions looked at per step; several steps cover long holidays


@cache
def calendar(code: str) -> Any:
    import exchange_calendars  # heavy (pandas): only when a trigger is evaluated

    return exchange_calendars.get_calendar(code)


def is_session(code: str, day: date) -> bool:
    import pandas as pd

    return bool(calendar(code).is_session(pd.Timestamp(day)))


class MarketRelativeTrigger(BaseTrigger):  # type: ignore[misc]
    """Fires `offset_minutes` after (or before, if negative) each session's open or close."""

    def __init__(self, anchor: str, offset_minutes: int = 0, calendar_code: str = "XNYS") -> None:
        if anchor not in ("open", "close"):
            raise ValueError("anchor must be open or close")
        self.anchor = anchor
        self.offset_minutes = offset_minutes
        self.calendar_code = calendar_code

    def fire_times(self, start: date, days: int) -> list[datetime]:
        import pandas as pd

        cal = calendar(self.calendar_code)
        last = cal.last_session
        end = min(pd.Timestamp(start + timedelta(days=days)), last)
        if pd.Timestamp(start) > end:
            return []
        times = []
        for session in cal.sessions_in_range(pd.Timestamp(start), end):
            base = (
                cal.session_open(session) if self.anchor == "open" else cal.session_close(session)
            )
            times.append((base + pd.Timedelta(minutes=self.offset_minutes)).to_pydatetime())
        return times

    def get_next_fire_time(
        self, previous_fire_time: datetime | None, now: datetime
    ) -> datetime | None:
        threshold = previous_fire_time or now
        day = threshold.date() - timedelta(days=2)  # offsets can cross midnight
        for _ in range(12):
            for t in self.fire_times(day, _SEARCH_DAYS):
                if t > threshold or (previous_fire_time is None and t == threshold):
                    return t
            day += timedelta(days=_SEARCH_DAYS)
        return None

    def __str__(self) -> str:
        sign = "+" if self.offset_minutes >= 0 else "-"
        return (
            f"market_relative[{self.calendar_code} {self.anchor}{sign}{abs(self.offset_minutes)}m]"
        )

    def __repr__(self) -> str:
        return f"<{self}>"


class TradingDayCronTrigger(BaseTrigger):  # type: ignore[misc]
    """A crontab in the exchange timezone that skips days the exchange is closed."""

    def __init__(
        self,
        expr: str,
        timezone: str = "America/New_York",
        calendar_code: str = "XNYS",
        skip_non_trading_days: bool = True,
    ) -> None:
        self.expr = expr
        self.timezone = timezone
        self.calendar_code = calendar_code
        self.skip_non_trading_days = skip_non_trading_days
        self.inner = CronTrigger.from_crontab(expr, timezone=ZoneInfo(timezone))

    def get_next_fire_time(
        self, previous_fire_time: datetime | None, now: datetime
    ) -> datetime | None:
        t: datetime | None = self.inner.get_next_fire_time(previous_fire_time, now)
        for _ in range(400):
            if t is None or not self.skip_non_trading_days:
                return t
            local_day = t.astimezone(ZoneInfo(self.timezone)).date()
            if is_session(self.calendar_code, local_day):
                return t
            t = self.inner.get_next_fire_time(t, t + timedelta(seconds=1))
        return None

    def __str__(self) -> str:
        skip = " trading days" if self.skip_non_trading_days else ""
        return f"cron[{self.expr} {self.timezone}{skip}]"

    def __repr__(self) -> str:
        return f"<{self}>"


def build_trigger(job: JobConfig, schedules: SchedulesConfig) -> BaseTrigger:
    if job.trigger == "market_relative":
        assert job.anchor is not None
        return MarketRelativeTrigger(job.anchor, job.offset_minutes, schedules.calendar)
    assert job.cron is not None
    return TradingDayCronTrigger(
        job.cron, schedules.timezone, schedules.calendar, job.skip_non_trading_days
    )


def upcoming(trigger: BaseTrigger, now: datetime, until: datetime) -> list[datetime]:
    """Fire times in (now, until], for `synodtrade-scheduler plan`."""
    times: list[datetime] = []
    t = trigger.get_next_fire_time(None, now)
    while t is not None and t <= until and len(times) < 1000:
        times.append(t)
        t = trigger.get_next_fire_time(t, t)
    return times
