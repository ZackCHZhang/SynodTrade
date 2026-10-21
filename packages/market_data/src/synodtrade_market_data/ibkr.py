"""IBKR market data via `ib_async` (TWS / IB Gateway socket API; paper ports 4002 / 7497).

The connection is read-only: this provider never places orders. Trading uses its own
connection (a different client id) in the trading package.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from ib_async import IB, BarData, Contract, Forex, Stock, Ticker
from ib_async.ib import StartupFetch
from pydantic import ValidationError
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential
from tenacity.wait import wait_base

from synodtrade_core.config import AccountConfig
from synodtrade_core.logging import get_logger
from synodtrade_core.models import AccountSnapshot, Bar, Instrument, Position, Quote, Timeframe
from synodtrade_core.timeutil import EXCHANGE_TZ, utcnow
from synodtrade_market_data.ecb import EcbFxRates
from synodtrade_market_data.pacing import PacingLimiter
from synodtrade_market_data.provider import AccountData, MarketDataError
from synodtrade_market_data.ranges import plan_requests

log = get_logger(__name__)

BAR_SIZE = {
    Timeframe.M1: "1 min",
    Timeframe.M5: "5 mins",
    Timeframe.M15: "15 mins",
    Timeframe.H1: "1 hour",
    Timeframe.D1: "1 day",
    Timeframe.W1: "1 week",
}

# IBKR market data types: 1 live, 2 frozen, 3 delayed, 4 delayed-frozen.
# Paper accounts without a data subscription usually need 3.
DELAYED = 3
# How far IBKR's delayed US equity data lags; a delayed tick is stamped this much earlier
# than it was received, so every consumer sees its real age.
DELAYED_DATA_LAG = timedelta(minutes=15)


def price(value: float | None) -> Decimal | None:
    """IBKR uses NaN / -1 / 0 for "no price"."""
    if value is None or math.isnan(value) or value <= 0:
        return None
    return Decimal(str(value))


def size(value: float | None) -> Decimal | None:
    if value is None or math.isnan(value) or value < 0:
        return None
    return Decimal(str(value))


def bar_timestamp(value: date | datetime) -> datetime:
    """Daily/weekly bars come as dates: the bar starts at midnight exchange time."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return datetime.combine(value, time(0), tzinfo=EXCHANGE_TZ)


def bar_from_ib(symbol: str, timeframe: Timeframe, raw: BarData) -> Bar | None:
    try:
        return Bar(
            symbol=symbol,
            timeframe=timeframe,
            ts=bar_timestamp(raw.date),
            open=Decimal(str(raw.open)),
            high=Decimal(str(raw.high)),
            low=Decimal(str(raw.low)),
            close=Decimal(str(raw.close)),
            volume=Decimal(str(max(raw.volume, 0))),
        )
    except (ValidationError, ArithmeticError, ValueError) as exc:
        log.warning("ibkr.bad_bar", symbol=symbol, date=str(raw.date), error=str(exc))
        return None


def quote_from_ticker(symbol: str, ticker: Ticker) -> Quote:
    bid, ask = price(ticker.bid), price(ticker.ask)
    if bid is not None and ask is not None and bid > ask:
        bid = ask = None  # crossed/stale book: keep only `last`
    ts = ticker.time or utcnow()
    if getattr(ticker, "marketDataType", 1) in (3, 4):  # delayed / delayed-frozen
        ts -= DELAYED_DATA_LAG
    return Quote(
        symbol=symbol,
        ts=ts,
        bid=bid,
        ask=ask,
        last=price(ticker.last) or price(ticker.close),
        bid_size=size(ticker.bidSize),
        ask_size=size(ticker.askSize),
    )


class IBKRMarketDataProvider:
    name = "ibkr"

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 4002,
        client_id: int = 17,
        base_currency: str = "USD",
        market_data_type: int = DELAYED,
        use_rth: bool = True,
        what_to_show: str = "TRADES",
        connect_timeout_s: float = 10.0,
        request_timeout_s: float = 60.0,
        pacing: PacingLimiter | None = None,
        retry_wait: wait_base | None = None,
        ib: IB | None = None,
        fx_fallback: EcbFxRates | None = None,
    ) -> None:
        self.host, self.port, self.client_id = host, port, client_id
        self.base_currency = base_currency
        self.market_data_type = market_data_type
        self.use_rth = use_rth
        self.what_to_show = what_to_show
        self.connect_timeout_s = connect_timeout_s
        self.request_timeout_s = request_timeout_s
        self._pacing = pacing or PacingLimiter()
        self._retry_wait = retry_wait or wait_exponential(multiplier=2, max=30)
        self._ib = ib or IB()
        # used when IBKR has no forex data for the account (no IDEALPRO market data permission)
        self._fx_fallback = fx_fallback

    @classmethod
    def from_account(cls, account: AccountConfig, **kwargs: object) -> IBKRMarketDataProvider:
        kwargs.setdefault("fx_fallback", EcbFxRates())
        return cls(
            host=account.host,
            port=account.port,
            client_id=account.client_id,
            base_currency=account.base_currency,
            **kwargs,  # type: ignore[arg-type]
        )

    # ------------------------------------------------------------ connection

    async def connect(self) -> None:
        if self._ib.isConnected():
            return
        await self._ib.connectAsync(
            self.host,
            self.port,
            clientId=self.client_id,
            timeout=self.connect_timeout_s,
            readonly=True,
            # no orders/executions needed here (the executions request times out on
            # read-only connections and only slows connecting down)
            fetchFields=StartupFetch.POSITIONS | StartupFetch.ACCOUNT_UPDATES,
        )
        self._ib.reqMarketDataType(self.market_data_type)
        log.info("ibkr.connected", host=self.host, port=self.port, client_id=self.client_id)

    async def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()

    async def is_healthy(self) -> bool:
        if not self._ib.isConnected():
            return False
        try:
            await self._ib.reqCurrentTimeAsync()
        except Exception:
            return False
        return True

    def _require_connection(self) -> None:
        if not self._ib.isConnected():
            raise MarketDataError(f"not connected to IBKR at {self.host}:{self.port}")

    # ------------------------------------------------------------ data

    async def resolve_instrument(self, symbol: str) -> Instrument:
        self._require_connection()
        [contract] = await self._ib.qualifyContractsAsync(
            Stock(symbol.upper(), "SMART", self.base_currency)
        )
        if not isinstance(contract, Contract) or not contract.conId:
            raise MarketDataError(f"IBKR does not know the stock {symbol!r}")
        return Instrument(
            symbol=contract.symbol,
            sec_type=contract.secType,
            exchange=contract.exchange or "SMART",
            primary_exchange=contract.primaryExchange or None,
            currency=contract.currency,
            con_id=contract.conId,
        )

    def _contract(self, instrument: Instrument) -> Contract:
        if instrument.con_id is None:
            raise MarketDataError(f"{instrument.symbol} has no con_id; resolve it first")
        return Contract(conId=instrument.con_id, exchange=instrument.exchange)

    async def fetch_bars(
        self, instrument: Instrument, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        self._require_connection()
        contract = self._contract(instrument)
        bars: dict[datetime, Bar] = {}
        for chunk_end, duration in plan_requests(start, end, timeframe):
            raw = await self._historical(contract, chunk_end, duration, timeframe)
            if not raw:
                break  # nothing earlier (e.g. before the listing date)
            for item in raw:
                bar = bar_from_ib(instrument.symbol, timeframe, item)
                if bar is not None and start <= bar.ts < end:
                    bars[bar.ts] = bar
        return [bars[ts] for ts in sorted(bars)]

    async def _historical(
        self, contract: Contract, end: datetime, duration: str, timeframe: Timeframe
    ) -> list[BarData]:
        retrying = AsyncRetrying(
            retry=retry_if_exception_type((ConnectionError, TimeoutError)),
            stop=stop_after_attempt(3),
            wait=self._retry_wait,
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                await self._pacing.acquire(str(contract.conId))
                result = await self._ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime=end,
                    durationStr=duration,
                    barSizeSetting=BAR_SIZE[timeframe],
                    whatToShow=self.what_to_show,
                    useRTH=self.use_rth,
                    formatDate=2,  # intraday timestamps in UTC
                    timeout=self.request_timeout_s,
                )
                return list(result)
        raise AssertionError("unreachable")  # pragma: no cover

    async def fetch_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]:
        self._require_connection()
        if not instruments:
            return []
        by_con_id = {i.con_id: i for i in instruments}
        tickers = await self._ib.reqTickersAsync(*(self._contract(i) for i in instruments))
        quotes = []
        for t in tickers:
            if t.contract is None or t.contract.conId not in by_con_id:
                continue
            instrument = by_con_id[t.contract.conId]
            quote = quote_from_ticker(instrument.symbol, t)
            if quote.reference_price is None:
                # No streaming data (e.g. a paper account without market data sharing):
                # fall back to the latest 1-minute bar, stamped with its real (delayed) time.
                quote = await self._quote_from_bars(instrument) or quote
            quotes.append(quote)
        return quotes

    async def _quote_from_bars(self, instrument: Instrument) -> Quote | None:
        contract = self._contract(instrument)
        await self._pacing.acquire(str(contract.conId))
        bars = await self._ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr="3600 S",
            barSizeSetting="1 min",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=2,
            timeout=self.request_timeout_s,
        )
        if not bars:
            return None
        last = bars[-1]
        return Quote(
            symbol=instrument.symbol,
            ts=bar_timestamp(last.date) + timedelta(minutes=1),  # when the bar closed
            last=price(last.close),
        )

    async def fx_rate(self, from_ccy: str, to_ccy: str) -> Decimal:
        """Units of `to_ccy` per 1 `from_ccy`, from the IDEALPRO midpoint (last daily close).

        Without IBKR forex data (no IDEALPRO market data permission: IBKR answers with no bars)
        the ECB reference rate is used instead, if a fallback is configured.
        """
        if from_ccy == to_ccy:
            return Decimal(1)
        for pair, invert in ((f"{from_ccy}{to_ccy}", False), (f"{to_ccy}{from_ccy}", True)):
            [contract] = await self._ib.qualifyContractsAsync(Forex(pair))
            if not isinstance(contract, Contract) or not contract.conId:
                continue
            await self._pacing.acquire(str(contract.conId))
            bars = await self._ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr="3 D",
                barSizeSetting="1 day",
                whatToShow="MIDPOINT",
                useRTH=False,
                formatDate=2,
                timeout=self.request_timeout_s,
            )
            if bars:
                rate = Decimal(str(bars[-1].close))
                return Decimal(1) / rate if invert else rate
        if self._fx_fallback is None:
            raise MarketDataError(f"no FX rate for {from_ccy}->{to_ccy}")
        try:
            rate, day = await self._fx_fallback.rate(from_ccy, to_ccy)
        except MarketDataError as exc:
            raise MarketDataError(
                f"no FX rate for {from_ccy}->{to_ccy}: no IBKR forex data, and {exc}"
            ) from exc
        log.warning(
            "ibkr.fx_fallback",
            pair=f"{from_ccy}{to_ccy}",
            rate=str(rate),
            source="ecb",
            reference_date=day.isoformat(),
            hint="IBKR returned no forex data (IDEALPRO market data permission missing?)",
        )
        return rate

    async def fetch_account(self, account_id: str) -> AccountData:
        """Account values converted to the trading currency (`base_currency`, e.g. USD).

        IBKR reports the summary in the account's own base currency (e.g. EUR for a
        European account); budgets and US prices are in USD, so values are converted at
        the current FX midpoint.
        """
        self._require_connection()
        values = [
            v for v in await self._ib.accountSummaryAsync(account_id) if v.account == account_id
        ]
        account_ccy = next(
            (v.currency for v in values if v.tag == "NetLiquidation" and v.currency), None
        )
        if account_ccy is None:
            raise MarketDataError(f"account {account_id}: summary lacks ['NetLiquidation']")
        tags: dict[str, Decimal] = {}
        for v in values:
            if v.currency == account_ccy:
                try:
                    tags.setdefault(v.tag, Decimal(v.value))
                except ArithmeticError:
                    continue
        missing = {"NetLiquidation", "TotalCashValue", "BuyingPower"} - tags.keys()
        if missing:
            raise MarketDataError(f"account {account_id}: summary lacks {sorted(missing)}")
        rate = await self.fx_rate(account_ccy, self.base_currency)
        if account_ccy != self.base_currency:
            log.info(
                "ibkr.account_fx",
                account_currency=account_ccy,
                currency=self.base_currency,
                rate=str(rate),
            )

        def converted(tag: str) -> Decimal | None:
            value = tags.get(tag)
            return None if value is None else (value * rate).quantize(Decimal("0.01"))

        ts = utcnow()
        account = AccountSnapshot(
            account_id=account_id,
            ts=ts,
            currency=self.base_currency,
            nav=converted("NetLiquidation") or Decimal(0),
            cash=converted("TotalCashValue") or Decimal(0),
            buying_power=converted("BuyingPower") or Decimal(0),
            available_funds=converted("AvailableFunds"),
        )
        positions = [
            Position(
                account_id=account_id,
                symbol=p.contract.symbol,
                qty=Decimal(str(p.position)),
                avg_cost=Decimal(str(p.avgCost)),
                ts=ts,
            )
            for p in await self._ib.reqPositionsAsync()
            if p.account == account_id and p.contract.secType == "STK" and p.position != 0
        ]
        return AccountData(account, positions)
