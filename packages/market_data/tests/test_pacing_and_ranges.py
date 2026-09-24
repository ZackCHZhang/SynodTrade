from datetime import UTC, datetime, timedelta

import pytest

from quant_core.models import Timeframe
from quant_market_data.pacing import PacingLimiter
from quant_market_data.ranges import missing_ranges, plan_requests


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# ------------------------------------------------------------------ pacing


async def test_global_window_limit() -> None:
    clock = FakeClock()
    limiter = PacingLimiter(
        max_requests=3, window_s=10, per_key_max=100, clock=clock, sleep=clock.sleep
    )
    for key in "abc":
        await limiter.acquire(key)
        clock.now += 1
    assert clock.sleeps == []
    await limiter.acquire("d")  # 4th request must wait until the first leaves the window
    assert clock.sleeps == [pytest.approx(7.0)]
    assert clock.now == pytest.approx(10.0)


async def test_per_key_limit() -> None:
    clock = FakeClock()
    limiter = PacingLimiter(
        max_requests=100, per_key_max=2, per_key_window_s=2, clock=clock, sleep=clock.sleep
    )
    await limiter.acquire("265598")
    await limiter.acquire("265598")
    await limiter.acquire("other")  # a different contract is not delayed
    assert clock.sleeps == []
    await limiter.acquire("265598")
    assert clock.sleeps == [pytest.approx(2.0)]


async def test_old_requests_expire() -> None:
    clock = FakeClock()
    limiter = PacingLimiter(max_requests=1, window_s=5, clock=clock, sleep=clock.sleep)
    await limiter.acquire("a")
    clock.now = 6
    await limiter.acquire("a")
    assert clock.sleeps == []


# ------------------------------------------------------------------ ranges

NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)
YEAR = timedelta(days=365)


def test_nothing_stored_fetches_whole_window() -> None:
    assert missing_ranges(NOW - YEAR, NOW, None, Timeframe.D1) == [(NOW - YEAR, NOW)]


def test_empty_window() -> None:
    assert missing_ranges(NOW, NOW, None, Timeframe.D1) == []


def test_up_to_date_data_refetches_only_the_tail() -> None:
    first, last = NOW - YEAR, NOW - timedelta(hours=10)
    assert missing_ranges(NOW - YEAR, NOW, (first, last), Timeframe.D1) == [(last, NOW)]


def test_weekend_slack_avoids_head_refetch() -> None:
    first = NOW - YEAR + timedelta(days=3)  # window starts on a weekend, data on Monday
    ranges = missing_ranges(NOW - YEAR, NOW, (first, NOW - timedelta(days=1)), Timeframe.D1)
    assert ranges == [(NOW - timedelta(days=1), NOW)]


def test_longer_lookback_adds_head_range() -> None:
    first = NOW - timedelta(days=100)
    ranges = missing_ranges(NOW - YEAR, NOW, (first, NOW - timedelta(days=1)), Timeframe.D1)
    assert ranges[0] == (NOW - YEAR, first)
    assert len(ranges) == 2


def test_stale_data_older_than_window() -> None:
    old = (NOW - 3 * YEAR, NOW - 2 * YEAR)
    assert missing_ranges(NOW - YEAR, NOW, old, Timeframe.D1) == [(NOW - YEAR, NOW)]


def test_plan_requests_daily_chunks_newest_first() -> None:
    plan = plan_requests(NOW - timedelta(days=800), NOW, Timeframe.D1)
    assert plan == [
        (NOW, "365 D"),
        (NOW - timedelta(days=365), "365 D"),
        (NOW - timedelta(days=730), "70 D"),
    ]


def test_plan_requests_intraday_and_minimum_one_day() -> None:
    plan = plan_requests(NOW - timedelta(days=3), NOW, Timeframe.M1)
    assert [d for _, d in plan] == ["1 D", "1 D", "1 D"]
    assert plan_requests(NOW - timedelta(hours=2), NOW, Timeframe.H1) == [(NOW, "1 D")]
    assert plan_requests(NOW, NOW, Timeframe.D1) == []
