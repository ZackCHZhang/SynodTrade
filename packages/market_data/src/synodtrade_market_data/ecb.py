"""Euro foreign exchange reference rates of the European Central Bank (free, no API key).

Fallback FX source for accounts without IBKR forex market data permissions (IDEALPRO), e.g. a
paper account whose live account does not share a forex subscription. The ECB publishes about
30 currencies against the euro once per working day (around 16:00 CET); cross rates such as
JPY->USD are derived through the euro.
"""

from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from synodtrade_market_data.provider import MarketDataError

ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


def parse_ecb_daily(xml_text: str) -> tuple[date, dict[str, Decimal]]:
    """(reference date, units of each currency per 1 EUR; EUR itself is 1) from the daily XML."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise MarketDataError(f"ECB FX rates: invalid XML ({exc})") from exc
    day: date | None = None
    rates: dict[str, Decimal] = {"EUR": Decimal(1)}
    for el in root.iter():
        if "time" in el.attrib:
            day = date.fromisoformat(el.attrib["time"])
        if "currency" in el.attrib and "rate" in el.attrib:
            try:
                rate = Decimal(el.attrib["rate"])
            except InvalidOperation:
                continue
            if rate > 0:
                rates[el.attrib["currency"].upper()] = rate
    if day is None or len(rates) == 1:
        raise MarketDataError("ECB FX rates: no rates in the response")
    return day, rates


class EcbFxRates:
    """ECB reference rates, downloaded at most once per `ttl_s`."""

    def __init__(
        self,
        url: str = ECB_DAILY_URL,
        *,
        timeout_s: float = 15.0,
        ttl_s: float = 3600.0,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url = url
        self.timeout_s = timeout_s
        self.ttl_s = ttl_s
        self._client = client
        self._clock = clock
        self._lock = asyncio.Lock()
        self._cached: tuple[float, date, dict[str, Decimal]] | None = None

    async def rates(self) -> tuple[date, dict[str, Decimal]]:
        async with self._lock:
            if self._cached is not None and self._clock() - self._cached[0] < self.ttl_s:
                return self._cached[1], self._cached[2]
            day, rates = parse_ecb_daily(await self._download())
            self._cached = (self._clock(), day, rates)
            return day, rates

    async def _download(self) -> str:
        try:
            if self._client is not None:
                response = await self._client.get(self.url, timeout=self.timeout_s)
            else:
                async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                    response = await client.get(self.url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MarketDataError(f"ECB FX rates: {type(exc).__name__}: {exc}") from exc
        return response.text

    async def rate(self, from_ccy: str, to_ccy: str) -> tuple[Decimal, date]:
        """(units of `to_ccy` per 1 `from_ccy`, the ECB reference date)."""
        day, rates = await self.rates()
        missing = sorted({from_ccy, to_ccy} - rates.keys())
        if missing:
            raise MarketDataError(f"ECB FX rates: no rate for {', '.join(missing)}")
        return rates[to_ccy] / rates[from_ccy], day
