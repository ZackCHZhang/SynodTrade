"""Which bar ranges to fetch, and how to split them into IBKR-sized requests."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from quant_core.models import Timeframe
from quant_database.repositories import TIMEFRAME_DURATION

# Longest span requested per historical data call (kept within IBKR's limits per bar size).
MAX_REQUEST_DAYS = {
    Timeframe.M1: 1,
    Timeframe.M5: 7,
    Timeframe.M15: 14,
    Timeframe.H1: 30,
    Timeframe.D1: 365,
    Timeframe.W1: 365,
}


def missing_ranges(
    desired_start: datetime,
    end: datetime,
    span: tuple[datetime, datetime] | None,
    timeframe: Timeframe,
) -> list[tuple[datetime, datetime]]:
    """Ranges to download so the database covers [desired_start, end).

    - Nothing stored: the whole window.
    - Head: only if stored data starts clearly after `desired_start`. A few days of slack
      absorb weekends/holidays, so a window starting on a Saturday doesn't refetch daily.
    - Tail: from the last stored bar (inclusive — it may have been a still-forming bar
      when stored) up to `end`.
    Gaps in the middle are not detected; they would need an exchange calendar.
    """
    if end <= desired_start:
        return []
    if span is None:
        return [(desired_start, end)]
    first, last = span
    ranges: list[tuple[datetime, datetime]] = []
    slack = max(timedelta(days=4), 2 * TIMEFRAME_DURATION[timeframe])
    if first - desired_start > slack:
        ranges.append((desired_start, first))
    tail_start = max(last, desired_start)
    if end > tail_start:
        ranges.append((tail_start, end))
    return ranges


def plan_requests(
    start: datetime, end: datetime, timeframe: Timeframe
) -> list[tuple[datetime, str]]:
    """Split [start, end) into (end_datetime, duration) requests, newest first."""
    max_days = MAX_REQUEST_DAYS[timeframe]
    requests: list[tuple[datetime, str]] = []
    chunk_end = end
    while chunk_end > start:
        chunk_start = max(start, chunk_end - timedelta(days=max_days))
        days = max(1, math.ceil((chunk_end - chunk_start) / timedelta(days=1)))
        requests.append((chunk_end, f"{days} D"))
        chunk_end = chunk_start
    return requests
