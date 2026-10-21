from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from synodtrade_core.models import AccountSnapshot, Bar, Instrument, Position, Quote, Timeframe
from synodtrade_database import Repositories

D = Decimal
DAY0 = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)  # a daily bar "starts" at NY midnight


def daily_bars(symbol: str, n: int, start: datetime = DAY0, close0: int = 100) -> list[Bar]:
    return [
        Bar(
            symbol=symbol,
            timeframe=Timeframe.D1,
            ts=start + timedelta(days=i),
            open=D(close0 + i),
            high=D(close0 + i + 2),
            low=D(close0 + i - 1),
            close=D(close0 + i + 1),
            volume=D(1000 + i),
        )
        for i in range(n)
    ]


# ------------------------------------------------------------------ instruments


async def test_instrument_upsert_and_get(repos: Repositories) -> None:
    assert await repos.instruments.get("AAPL") is None
    first_id = await repos.instruments.upsert(Instrument(symbol="aapl", con_id=265598))
    again_id = await repos.instruments.upsert(
        Instrument(symbol="AAPL", con_id=265598, primary_exchange="NASDAQ")
    )
    assert first_id == again_id
    inst = await repos.instruments.get("aapl")
    assert inst == Instrument(symbol="AAPL", con_id=265598, primary_exchange="NASDAQ")
    await repos.instruments.upsert(Instrument(symbol="MSFT"))
    assert [i.symbol for i in await repos.instruments.list()] == ["AAPL", "MSFT"]


# ------------------------------------------------------------------ bars


async def test_bars_upsert_is_idempotent_and_updates(repos: Repositories) -> None:
    bars = daily_bars("AAPL", 5)
    assert await repos.bars.upsert(bars) == 5
    assert await repos.bars.upsert(bars) == 5  # same keys: no duplicates
    corrected = bars[-1].model_copy(update={"close": D("104.5")})
    await repos.bars.upsert([corrected])
    got = await repos.bars.get_latest_bars("AAPL", 10, as_of=DAY0 + timedelta(days=30))
    assert len(got) == 5
    assert got[-1].close == D("104.5")
    assert await repos.bars.upsert([]) == 0


async def test_get_latest_bars_order_limit_and_symbol_isolation(repos: Repositories) -> None:
    await repos.bars.upsert(daily_bars("AAPL", 10) + daily_bars("MSFT", 3, close0=300))
    as_of = DAY0 + timedelta(days=30)
    got = await repos.bars.get_latest_bars("aapl", 3, as_of=as_of)
    assert [b.ts for b in got] == [DAY0 + timedelta(days=d) for d in (7, 8, 9)]  # oldest first
    assert all(b.symbol == "AAPL" for b in got)
    assert len(await repos.bars.get_latest_bars("MSFT", 10, as_of=as_of)) == 3
    assert await repos.bars.get_latest_bars("NVDA", 10, as_of=as_of) == []
    assert await repos.bars.get_latest_bars("AAPL", 10, Timeframe.H1, as_of=as_of) == []


async def test_bars_only_visible_once_complete(repos: Repositories) -> None:
    """No look-ahead: during day 5 the day-5 bar is still forming and must be hidden."""
    await repos.bars.upsert(daily_bars("AAPL", 6))
    during_day5 = DAY0 + timedelta(days=5, hours=14)
    got = await repos.bars.get_latest_bars("AAPL", 10, as_of=during_day5)
    assert got[-1].ts == DAY0 + timedelta(days=4)
    at_close = DAY0 + timedelta(days=6)
    assert (await repos.bars.get_latest_bars("AAPL", 10, as_of=at_close))[
        -1
    ].ts == DAY0 + timedelta(days=5)


async def test_get_bars_range_and_span(repos: Repositories) -> None:
    assert await repos.bars.get_bar_span("AAPL", Timeframe.D1) is None
    await repos.bars.upsert(daily_bars("AAPL", 10))
    got = await repos.bars.get_bars(
        "AAPL", Timeframe.D1, DAY0 + timedelta(days=2), DAY0 + timedelta(days=5)
    )
    assert [b.ts.day for b in got] == [3, 4, 5]
    assert got[0].open == D(102)
    span = await repos.bars.get_bar_span("AAPL", Timeframe.D1)
    assert span == (DAY0, DAY0 + timedelta(days=9))
    assert span[0].tzinfo == UTC


# ------------------------------------------------------------------ quotes


async def test_latest_quote_respects_as_of(repos: Repositories) -> None:
    t = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)
    await repos.quotes.add(
        [
            Quote(symbol="AAPL", ts=t, bid=D("99.9"), ask=D("100.1")),
            Quote(symbol="AAPL", ts=t + timedelta(minutes=5), bid=D("101"), ask=D("101.2")),
            Quote(symbol="MSFT", ts=t, last=D(400)),
        ]
    )
    await repos.quotes.add([])
    latest = await repos.quotes.get_latest_quote("AAPL", as_of=t + timedelta(hours=1))
    assert latest is not None
    assert latest.bid == D(101)
    earlier = await repos.quotes.get_latest_quote("AAPL", as_of=t + timedelta(minutes=1))
    assert earlier is not None
    assert earlier.mid == D(100)
    assert await repos.quotes.get_latest_quote("AAPL", as_of=t - timedelta(seconds=1)) is None
    msft = await repos.quotes.get_latest_quote("msft", as_of=t)
    assert msft is not None
    assert msft.last == D(400)
    assert msft.bid is None


# ------------------------------------------------------------------ accounts


def snapshot(ts: datetime, cash: str = "1000") -> AccountSnapshot:
    return AccountSnapshot(
        account_id="DU1", ts=ts, nav=D("5000"), cash=D(cash), buying_power=D("2000")
    )


def position(ts: datetime, symbol: str, qty: str) -> Position:
    return Position(account_id="DU1", symbol=symbol, qty=D(qty), avg_cost=D("10.5"), ts=ts)


async def test_account_snapshots_and_positions(repos: Repositories) -> None:
    t1 = datetime(2026, 9, 23, 14, 0, tzinfo=UTC)
    t2 = t1 + timedelta(days=1)
    assert await repos.accounts.get_latest_account("DU1") is None
    assert await repos.accounts.get_latest_positions("DU1") is None

    await repos.accounts.add_snapshot(
        snapshot(t1), [position(t1, "AAPL", "3"), position(t1, "MSFT", "1")]
    )
    await repos.accounts.add_snapshot(snapshot(t2, cash="1500"), [position(t2, "AAPL", "5")])

    latest = await repos.accounts.get_latest_account("DU1", as_of=t2)
    assert latest is not None
    assert latest.cash == D(1500)
    positions = await repos.accounts.get_latest_positions("DU1", as_of=t2)
    assert positions == [position(t2, "AAPL", "5")]
    earlier = await repos.accounts.get_latest_positions("DU1", as_of=t1 + timedelta(hours=1))
    assert earlier is not None
    assert [p.symbol for p in earlier] == ["AAPL", "MSFT"]


async def test_empty_book_is_not_confused_with_older_snapshot(repos: Repositories) -> None:
    t1 = datetime(2026, 9, 23, 14, 0, tzinfo=UTC)
    t2 = t1 + timedelta(days=1)
    await repos.accounts.add_snapshot(snapshot(t1), [position(t1, "AAPL", "3")])
    await repos.accounts.add_snapshot(snapshot(t2), [])
    assert await repos.accounts.get_latest_positions("DU1", as_of=t2) == []


async def test_positions_must_match_snapshot(repos: Repositories) -> None:
    t1 = datetime(2026, 9, 23, 14, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="share the account snapshot"):
        await repos.accounts.add_snapshot(
            snapshot(t1), [position(t1 + timedelta(seconds=1), "AAPL", "1")]
        )
