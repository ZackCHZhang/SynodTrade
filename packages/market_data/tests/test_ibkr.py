"""IBKRMarketDataProvider against a stub `IB` object — no gateway, no network."""

import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from ib_async import AccountValue, BarData, Contract, Position, Stock, Ticker
from tenacity import wait_none

from quant_core.config import AccountConfig
from quant_core.models import Instrument, Timeframe
from quant_market_data import IBKRMarketDataProvider, MarketDataError, PacingLimiter
from quant_market_data.ecb import EcbFxRates
from quant_market_data.ibkr import bar_from_ib, bar_timestamp, price, quote_from_ticker

D = Decimal
NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)
AAPL = Instrument(symbol="AAPL", con_id=265598, primary_exchange="NASDAQ")


def daily(d: date, close: float = 100.0) -> BarData:
    return BarData(
        date=d,
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=1000,
        average=close,
        barCount=10,
    )


class StubIB:
    def __init__(self) -> None:
        self.connected = False
        self.calls: list[tuple[str, Any]] = []
        self.history: list[Any] = []  # one entry (list or exception) per historical request
        self.qualified: list[Any] = []
        self.tickers: list[Ticker] = []
        self.summary: list[AccountValue] = []
        self.positions: list[Position] = []
        self.time_fails = False

    def isConnected(self) -> bool:  # noqa: N802 - mirrors ib_async
        return self.connected

    async def connectAsync(self, host: str, port: int, **kw: Any) -> None:  # noqa: N802
        self.calls.append(("connect", (host, port, kw)))
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def reqMarketDataType(self, kind: int) -> None:  # noqa: N802
        self.calls.append(("market_data_type", kind))

    async def reqCurrentTimeAsync(self) -> datetime:  # noqa: N802
        if self.time_fails:
            raise ConnectionError("gone")
        return NOW

    async def qualifyContractsAsync(self, *contracts: Contract) -> list[Any]:  # noqa: N802
        self.calls.append(("qualify", contracts[0].symbol))
        return self.qualified

    async def reqHistoricalDataAsync(self, contract: Contract, **kw: Any) -> list[BarData]:  # noqa: N802
        self.calls.append(("history", (contract.conId, kw)))
        outcome = self.history.pop(0) if self.history else []
        if isinstance(outcome, Exception):
            raise outcome
        return list(outcome)

    async def reqTickersAsync(self, *contracts: Contract) -> list[Ticker]:  # noqa: N802
        return self.tickers

    async def accountSummaryAsync(self, account: str) -> list[AccountValue]:  # noqa: N802
        return self.summary

    async def reqPositionsAsync(self) -> list[Position]:  # noqa: N802
        return self.positions


def ticker(contract: Contract, **fields: Any) -> Ticker:
    """ib_async's Ticker.__post_init__ resets price fields, so set them afterwards
    (which is also how ib_async itself fills tickers)."""
    t = Ticker(contract=contract)
    for key, value in fields.items():
        setattr(t, key, value)
    return t


def make_provider(ib: StubIB, **kw: Any) -> IBKRMarketDataProvider:
    ib.connected = True
    return IBKRMarketDataProvider(
        ib=ib,  # type: ignore[arg-type]
        pacing=PacingLimiter(max_requests=1000, per_key_max=1000),
        retry_wait=wait_none(),
        **kw,
    )


# ------------------------------------------------------------------ conversions


@pytest.mark.parametrize("value", [None, math.nan, -1.0, 0.0])
def test_missing_prices(value: float | None) -> None:
    assert price(value) is None


def test_price_is_exact_decimal() -> None:
    assert price(187.12) == D("187.12")


def test_daily_bar_starts_at_exchange_midnight() -> None:
    ts = bar_timestamp(date(2026, 9, 23))
    assert ts == datetime(2026, 9, 23, 4, 0, tzinfo=UTC)  # 00:00 New York (EDT)
    intraday = datetime(2026, 9, 23, 13, 30, tzinfo=UTC)
    assert bar_timestamp(intraday) == intraday
    assert bar_timestamp(intraday.replace(tzinfo=None)) == intraday


def test_bad_bars_are_skipped() -> None:
    bad = BarData(date=date(2026, 9, 23), open=10, high=5, low=1, close=9, volume=1)
    assert bar_from_ib("AAPL", Timeframe.D1, bad) is None
    negative_volume = daily(date(2026, 9, 23))
    negative_volume.volume = -1
    bar = bar_from_ib("AAPL", Timeframe.D1, negative_volume)
    assert bar is not None
    assert bar.volume == 0


def test_quote_from_ticker() -> None:
    t = ticker(
        Stock("AAPL"),
        time=NOW,
        bid=99.5,
        ask=100.5,
        last=math.nan,
        close=99.0,
        bidSize=300,
        askSize=math.nan,
    )
    q = quote_from_ticker("AAPL", t)
    assert (q.bid, q.ask, q.last) == (D("99.5"), D("100.5"), D("99.0"))
    assert q.bid_size == D(300)
    assert q.ask_size is None
    crossed = quote_from_ticker("AAPL", ticker(Stock("AAPL"), bid=101, ask=100, last=100))
    assert crossed.bid is None
    assert crossed.ask is None
    assert crossed.ts.tzinfo is not None
    assert q.ts == NOW  # live data (marketDataType 1): stamped when received


def test_delayed_ticks_carry_their_real_age() -> None:
    """Delayed data arrives ~15 min late: stamping it with the receipt time made stale
    prices look live, and limit orders priced from them did not fill."""
    delayed = ticker(Stock("AAPL"), time=NOW, bid=99.5, ask=100.5, marketDataType=3)
    assert quote_from_ticker("AAPL", delayed).ts == NOW - timedelta(minutes=15)
    frozen = ticker(Stock("AAPL"), time=NOW, last=100, marketDataType=4)
    assert quote_from_ticker("AAPL", frozen).ts == NOW - timedelta(minutes=15)


# ------------------------------------------------------------------ connection


async def test_connect_is_read_only_and_sets_data_type() -> None:
    ib = StubIB()
    provider = IBKRMarketDataProvider(ib=ib, port=4002, client_id=9)  # type: ignore[arg-type]
    assert not await provider.is_healthy()
    await provider.connect()
    await provider.connect()  # no second connection
    connects = [c for c in ib.calls if c[0] == "connect"]
    assert len(connects) == 1
    assert connects[0][1][2]["readonly"] is True
    assert connects[0][1][2]["clientId"] == 9
    assert ("market_data_type", 3) in ib.calls
    assert await provider.is_healthy()
    ib.time_fails = True
    assert not await provider.is_healthy()
    await provider.disconnect()
    assert not ib.connected


def test_from_account_config() -> None:
    cfg = AccountConfig(name="ibkr_main", account_id="DU1", port=4002, client_id=21)
    provider = IBKRMarketDataProvider.from_account(cfg, market_data_type=1)
    assert (provider.port, provider.client_id, provider.market_data_type) == (4002, 21, 1)


async def test_requires_connection() -> None:
    provider = IBKRMarketDataProvider(ib=StubIB())  # type: ignore[arg-type]
    with pytest.raises(MarketDataError, match="not connected"):
        await provider.fetch_quotes([AAPL])


# ------------------------------------------------------------------ instruments


async def test_resolve_instrument() -> None:
    ib = StubIB()
    contract = Stock("AAPL", "SMART", "USD")
    contract.conId, contract.primaryExchange = 265598, "NASDAQ"
    ib.qualified = [contract]
    inst = await make_provider(ib).resolve_instrument("aapl")
    assert inst == Instrument(symbol="AAPL", con_id=265598, primary_exchange="NASDAQ")
    assert ("qualify", "AAPL") in ib.calls


async def test_resolve_unknown_symbol() -> None:
    ib = StubIB()
    ib.qualified = [None]
    with pytest.raises(MarketDataError, match="does not know"):
        await make_provider(ib).resolve_instrument("NOPE")


async def test_bars_need_con_id() -> None:
    with pytest.raises(MarketDataError, match="no con_id"):
        await make_provider(StubIB()).fetch_bars(Instrument(symbol="X"), Timeframe.D1, NOW, NOW)


# ------------------------------------------------------------------ bars


async def test_fetch_bars_chunks_dedupes_and_filters() -> None:
    ib = StubIB()
    start = NOW - timedelta(days=500)
    newest = [daily(date(2026, 9, 22), 110), daily(date(2026, 9, 23), 111)]
    older = [
        daily(date(2025, 5, 1), 90),
        daily(date(2025, 9, 23), 95),
        daily(date(2025, 9, 23), 95),
    ]  # duplicate across chunk boundary
    ib.history = [newest, older]
    bars = await make_provider(ib).fetch_bars(AAPL, Timeframe.D1, start, NOW)
    assert [b.close for b in bars] == [D(95), D(110), D(111)]  # 2025-05-01 < start
    requests = [c[1] for c in ib.calls if c[0] == "history"]
    assert [r[1]["durationStr"] for r in requests] == ["365 D", "135 D"]
    assert all(r[0] == 265598 for r in requests)
    assert requests[0][1]["barSizeSetting"] == "1 day"
    assert requests[0][1]["useRTH"] is True
    assert requests[0][1]["formatDate"] == 2


async def test_fetch_bars_excludes_out_of_range() -> None:
    ib = StubIB()
    ib.history = [[daily(date(2026, 9, 1)), daily(date(2026, 9, 23))]]
    start = datetime(2026, 9, 10, tzinfo=UTC)
    bars = await make_provider(ib).fetch_bars(AAPL, Timeframe.D1, start, NOW)
    assert [b.ts.day for b in bars] == [23]


async def test_fetch_bars_stops_when_no_earlier_data() -> None:
    ib = StubIB()
    ib.history = [[daily(date(2026, 9, 23))], []]
    await make_provider(ib).fetch_bars(AAPL, Timeframe.D1, NOW - timedelta(days=1500), NOW)
    assert len([c for c in ib.calls if c[0] == "history"]) == 2  # not 5


async def test_fetch_bars_retries_timeouts() -> None:
    ib = StubIB()
    ib.history = [TimeoutError(), [daily(date(2026, 9, 23))]]
    bars = await make_provider(ib).fetch_bars(AAPL, Timeframe.D1, NOW - timedelta(days=5), NOW)
    assert len(bars) == 1


async def test_fetch_bars_uses_pacing_limiter() -> None:
    keys: list[str] = []

    class RecordingLimiter(PacingLimiter):
        async def acquire(self, key: str, *, small_bars: bool = False) -> None:
            keys.append(key)

    ib = StubIB()
    ib.connected = True
    ib.history = [[daily(date(2026, 9, 23))], [daily(date(2025, 9, 1))]]
    provider = IBKRMarketDataProvider(ib=ib, pacing=RecordingLimiter())  # type: ignore[arg-type]
    await provider.fetch_bars(AAPL, Timeframe.D1, NOW - timedelta(days=400), NOW)
    assert keys == ["265598", "265598"]


# ------------------------------------------------------------------ quotes and account


async def test_fetch_quotes_maps_by_con_id() -> None:
    ib = StubIB()
    contract = Contract(conId=265598)
    ib.tickers = [
        ticker(contract, time=NOW, bid=1.0, ask=2.0),
        ticker(Contract(conId=999), time=NOW, last=5.0),  # not requested
    ]
    provider = make_provider(ib)
    quotes = await provider.fetch_quotes([AAPL])
    assert [(q.symbol, q.mid) for q in quotes] == [("AAPL", D("1.5"))]
    assert await provider.fetch_quotes([]) == []


def _value(tag: str, value: str, currency: str = "USD", account: str = "DU1") -> AccountValue:
    return AccountValue(account=account, tag=tag, value=value, currency=currency, modelCode="")


async def test_fetch_account() -> None:
    ib = StubIB()
    ib.summary = [
        _value("NetLiquidation", "100123.45"),
        _value("TotalCashValue", "50000.5"),
        _value("BuyingPower", "200000"),
        _value("AvailableFunds", "48000"),
        _value("NetLiquidation", "1", account="DU2"),  # other account
        _value("AccountType", "INDIVIDUAL", currency=""),
        _value("TotalCashValue", "n/a", currency="BASE"),  # unparsable, ignored
    ]
    ib.positions = [
        Position(account="DU1", contract=Stock("AAPL"), position=10.0, avgCost=187.5),
        Position(
            account="DU1", contract=Contract(symbol="ES", secType="FUT"), position=1, avgCost=1
        ),
        Position(account="DU1", contract=Stock("MSFT"), position=0.0, avgCost=0),
        Position(account="DU2", contract=Stock("NVDA"), position=5.0, avgCost=100),
    ]
    data = await make_provider(ib).fetch_account("DU1")
    assert data.account.nav == D("100123.45")
    assert data.account.cash == D("50000.5")
    assert data.account.available_funds == D(48000)
    assert [(p.symbol, p.qty, p.avg_cost) for p in data.positions] == [("AAPL", D(10), D("187.5"))]
    assert data.positions[0].ts == data.account.ts


async def test_fetch_account_missing_tags() -> None:
    ib = StubIB()
    ib.summary = [_value("NetLiquidation", "1")]
    with pytest.raises(MarketDataError, match="BuyingPower"):
        await make_provider(ib).fetch_account("DU1")


class FxStubIB(StubIB):
    """Qualifies forex pairs from a table (None: IBKR has no such pair)."""

    def __init__(self, pairs: dict[str, int | None]) -> None:
        super().__init__()
        self.pairs = pairs

    async def qualifyContractsAsync(self, *contracts: Contract) -> list[Any]:  # noqa: N802
        c = contracts[0]
        pair = f"{c.symbol}{c.currency}"
        self.calls.append(("qualify", pair))
        con_id = self.pairs.get(pair)
        if con_id is None:
            return [None]
        c.conId = con_id
        return [c]


def fx_bar(rate: float) -> BarData:
    return BarData(
        date=date(2026, 9, 30),
        open=rate,
        high=rate,
        low=rate,
        close=rate,
        volume=0,
        average=rate,
        barCount=0,
    )


async def test_fetch_account_converts_eur_to_usd() -> None:
    ib = FxStubIB({"EURUSD": 12087792})
    ib.summary = [
        _value("NetLiquidation", "1000000", currency="EUR"),
        _value("TotalCashValue", "900000", currency="EUR"),
        _value("BuyingPower", "4000000", currency="EUR"),
        _value("AvailableFunds", "800000", currency="EUR"),
    ]
    ib.history = [[fx_bar(1.1358)]]
    data = await make_provider(ib).fetch_account("DU1")
    assert data.account.currency == "USD"
    assert data.account.nav == D("1135800.00")
    assert data.account.cash == D("1022220.00")
    assert data.account.available_funds == D("908640.00")
    fx_request = next(c[1] for c in ib.calls if c[0] == "history")
    assert fx_request[1]["whatToShow"] == "MIDPOINT"


async def test_fx_rate_uses_the_inverse_pair_when_needed() -> None:
    ib = FxStubIB({"JPYUSD": None, "USDJPY": 15016})
    ib.history = [[fx_bar(150.0)]]
    provider = make_provider(ib)
    assert await provider.fx_rate("JPY", "USD") == D(1) / D("150.0")
    assert await provider.fx_rate("USD", "USD") == D(1)
    with pytest.raises(MarketDataError, match="no FX rate for XXX->USD"):
        await make_provider(FxStubIB({})).fx_rate("XXX", "USD")


class StubFallback:
    def __init__(self, rate: D | None) -> None:
        self.value = rate
        self.calls: list[tuple[str, str]] = []

    async def rate(self, from_ccy: str, to_ccy: str) -> tuple[D, date]:
        self.calls.append((from_ccy, to_ccy))
        if self.value is None:
            raise MarketDataError("ECB FX rates: no rate for XXX")
        return self.value, date(2026, 10, 7)


async def test_fx_rate_falls_back_when_ibkr_has_no_forex_data() -> None:
    # without IDEALPRO market data permissions IBKR qualifies the pair but returns no bars
    ib = FxStubIB({"EURUSD": 12087792, "USDEUR": None})
    ib.history = [[]]
    fallback = StubFallback(D("1.1358"))
    provider = make_provider(ib, fx_fallback=fallback)
    assert await provider.fx_rate("EUR", "USD") == D("1.1358")
    assert fallback.calls == [("EUR", "USD")]


async def test_fx_rate_prefers_ibkr_over_the_fallback() -> None:
    ib = FxStubIB({"EURUSD": 12087792})
    ib.history = [[fx_bar(1.14)]]
    fallback = StubFallback(D("9"))
    assert await make_provider(ib, fx_fallback=fallback).fx_rate("EUR", "USD") == D("1.14")
    assert fallback.calls == []


async def test_fx_rate_error_names_both_sources() -> None:
    provider = make_provider(FxStubIB({}), fx_fallback=StubFallback(None))
    with pytest.raises(MarketDataError, match="no IBKR forex data, and ECB FX rates"):
        await provider.fx_rate("XXX", "USD")


def test_from_account_enables_the_ecb_fallback() -> None:
    cfg = AccountConfig(name="ibkr_main", account_id="DU1", port=4002, client_id=21)
    assert isinstance(IBKRMarketDataProvider.from_account(cfg)._fx_fallback, EcbFxRates)


async def test_fetch_account_without_net_liquidation() -> None:
    ib = StubIB()
    ib.summary = [_value("TotalCashValue", "1")]
    with pytest.raises(MarketDataError, match="NetLiquidation"):
        await make_provider(ib).fetch_account("DU1")


async def test_quotes_fall_back_to_the_latest_minute_bar() -> None:
    ib = StubIB()
    empty = ticker(Contract(conId=265598), time=NOW)  # no bid/ask/last at all
    ib.tickers = [empty]
    minute = datetime(2026, 9, 30, 14, 52, tzinfo=UTC)
    ib.history = [
        [
            BarData(
                date=minute,
                open=338.7,
                high=338.9,
                low=338.6,
                close=338.8,
                volume=100,
                average=338.8,
                barCount=5,
            )
        ]
    ]
    [quote] = await make_provider(ib).fetch_quotes([AAPL])
    assert quote.last == D("338.8")
    assert quote.bid is None
    assert quote.ts == minute + timedelta(minutes=1)  # honest (delayed) timestamp
    request = next(c[1] for c in ib.calls if c[0] == "history")[1]
    assert (request["barSizeSetting"], request["whatToShow"]) == ("1 min", "TRADES")

    ib.tickers, ib.history = [empty], [[]]  # no bars either: keep the empty quote
    [nothing] = await make_provider(ib).fetch_quotes([AAPL])
    assert nothing.reference_price is None
