"""In-memory market data for tests and dry runs. Never touches the network."""

from __future__ import annotations

import csv
import json
import random
import zlib
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from quant_core.models import AccountSnapshot, Bar, Instrument, Position, Quote, Timeframe
from quant_core.timeutil import EXCHANGE_TZ, utcnow
from quant_market_data.provider import AccountData, MarketDataError

CENT = Decimal("0.01")


def generate_daily_bars(
    symbol: str,
    start: date,
    days: int,
    *,
    start_price: Decimal = Decimal(100),
    daily_vol: float = 0.015,
    drift: float = 0.0003,
    seed: int | None = None,
) -> list[Bar]:
    """Deterministic random-walk daily bars on weekdays (seeded by symbol by default)."""
    rng = random.Random(seed if seed is not None else zlib.crc32(symbol.encode()))

    def scaled(value: Decimal, change: float) -> Decimal:
        return max(CENT, (value * Decimal(str(1 + change))).quantize(CENT))

    bars: list[Bar] = []
    close = start_price
    day = start
    while len(bars) < days:
        if day.weekday() < 5:
            open_ = close
            close = scaled(open_, rng.gauss(drift, daily_vol))
            high = scaled(max(open_, close), abs(rng.gauss(0, daily_vol / 2)))
            low = scaled(min(open_, close), -abs(rng.gauss(0, daily_vol / 2)))
            bars.append(
                Bar(
                    symbol=symbol,
                    timeframe=Timeframe.D1,
                    ts=datetime.combine(day, time(0), tzinfo=EXCHANGE_TZ),
                    open=open_,
                    high=max(high, open_, close),
                    low=min(low, open_, close),
                    close=close,
                    volume=Decimal(rng.randint(1_000_000, 50_000_000)),
                )
            )
        day += timedelta(days=1)
    return bars


class FakeMarketDataProvider:
    """Serves the bars/quotes/account it was given; records every call in `calls`.

    Symbols in `fail_symbols` raise MarketDataError, to test error handling.
    """

    name = "fake"

    def __init__(
        self,
        bars: Iterable[Bar] = (),
        *,
        quotes: Iterable[Quote] = (),
        account: AccountData | None = None,
        instruments: Mapping[str, Instrument] | None = None,
        fail_symbols: Iterable[str] = (),
        healthy: bool = True,
    ) -> None:
        self._bars: dict[tuple[str, Timeframe], list[Bar]] = {}
        for bar in bars:
            self._bars.setdefault((bar.symbol, bar.timeframe), []).append(bar)
        for series in self._bars.values():
            series.sort(key=lambda b: b.ts)
        self._quotes = {q.symbol: q for q in quotes}
        self._account = account
        self._instruments = dict(instruments or {})
        self._fail = {s.upper() for s in fail_symbols}
        self._healthy = healthy
        self.connected = False
        self.calls: list[tuple[str, str]] = []

    @classmethod
    def from_fixture_dir(cls, path: Path, **kwargs: object) -> FakeMarketDataProvider:
        """Load `bars/<SYMBOL>_<timeframe>.csv` (ts,open,high,low,close,volume),
        optional `quotes.json` (list of Quote) and `account.json` ({account, positions}).
        """
        bars: list[Bar] = []
        for csv_path in sorted((path / "bars").glob("*.csv")):
            symbol, timeframe = csv_path.stem.rsplit("_", 1)
            with csv_path.open(encoding="utf-8", newline="") as fh:
                bars += [
                    Bar.model_validate({**row, "symbol": symbol, "timeframe": timeframe})
                    for row in csv.DictReader(fh)
                ]
        quotes: list[Quote] = []
        if (path / "quotes.json").exists():
            raw = json.loads((path / "quotes.json").read_text(encoding="utf-8"))
            quotes = [Quote.model_validate(q) for q in raw]
        account = None
        if (path / "account.json").exists():
            raw = json.loads((path / "account.json").read_text(encoding="utf-8"))
            account = AccountData(
                AccountSnapshot.model_validate(raw["account"]),
                [Position.model_validate(p) for p in raw.get("positions", [])],
            )
        return cls(bars, quotes=quotes, account=account, **kwargs)  # type: ignore[arg-type]

    def _check(self, symbol: str, call: str) -> None:
        self.calls.append((call, symbol))
        if symbol.upper() in self._fail:
            raise MarketDataError(f"simulated failure for {symbol}")

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def is_healthy(self) -> bool:
        return self._healthy

    async def resolve_instrument(self, symbol: str) -> Instrument:
        self._check(symbol, "resolve_instrument")
        symbol = symbol.upper()
        return self._instruments.get(symbol) or Instrument(
            symbol=symbol, con_id=zlib.crc32(symbol.encode()) % 10_000_000 + 1
        )

    async def fetch_bars(
        self, instrument: Instrument, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        self._check(instrument.symbol, "fetch_bars")
        series = self._bars.get((instrument.symbol, timeframe), [])
        return [b for b in series if start <= b.ts < end]

    async def fetch_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]:
        quotes = []
        for inst in instruments:
            self._check(inst.symbol, "fetch_quotes")
            quote = self._quotes.get(inst.symbol)
            if quote is None:
                series = self._bars.get((inst.symbol, Timeframe.D1))
                if series:  # derive a quote from the last close
                    quote = Quote(symbol=inst.symbol, ts=utcnow(), last=series[-1].close)
            if quote is not None:
                quotes.append(quote)
        return quotes

    async def fetch_account(self, account_id: str) -> AccountData:
        self._check(account_id, "fetch_account")
        if self._account is not None:
            return self._account
        return AccountData(
            AccountSnapshot(
                account_id=account_id,
                ts=utcnow(),
                nav=Decimal(100_000),
                cash=Decimal(100_000),
                buying_power=Decimal(100_000),
            )
        )
