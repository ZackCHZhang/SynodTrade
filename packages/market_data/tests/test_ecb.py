"""ECB reference rates: parsing, cross rates through the euro, caching and errors."""

from datetime import date
from decimal import Decimal

import httpx
import pytest

from synodtrade_market_data.ecb import EcbFxRates, parse_ecb_daily
from synodtrade_market_data.provider import MarketDataError

D = Decimal

DAILY = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
    xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube>
    <Cube time="2026-10-07">
      <Cube currency="USD" rate="1.1358"/>
      <Cube currency="JPY" rate="170.40"/>
      <Cube currency="GBP" rate="0.8521"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


def ecb(handler: httpx.MockTransport, **kw: object) -> EcbFxRates:
    return EcbFxRates(client=httpx.AsyncClient(transport=handler), **kw)  # type: ignore[arg-type]


def test_parse() -> None:
    day, rates = parse_ecb_daily(DAILY)
    assert day == date(2026, 10, 7)
    assert rates == {"EUR": D(1), "USD": D("1.1358"), "JPY": D("170.40"), "GBP": D("0.8521")}


@pytest.mark.parametrize("bad", ["not xml", "<Envelope><Cube/></Envelope>"])
def test_parse_rejects_responses_without_rates(bad: str) -> None:
    with pytest.raises(MarketDataError, match="ECB FX rates"):
        parse_ecb_daily(bad)


async def test_rates_direct_inverse_and_cross() -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=DAILY)

    rates = ecb(httpx.MockTransport(handle))
    assert await rates.rate("EUR", "USD") == (D("1.1358"), date(2026, 10, 7))
    assert (await rates.rate("USD", "EUR"))[0] == D(1) / D("1.1358")
    assert (await rates.rate("JPY", "USD"))[0] == D("1.1358") / D("170.40")
    assert len(calls) == 1  # cached within the TTL
    with pytest.raises(MarketDataError, match="no rate for XXX"):
        await rates.rate("XXX", "USD")


async def test_cache_expires() -> None:
    now = [0.0]
    calls: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, text=DAILY)

    rates = ecb(httpx.MockTransport(handle), ttl_s=60.0, clock=lambda: now[0])
    await rates.rate("EUR", "USD")
    now[0] = 61.0
    await rates.rate("EUR", "USD")
    assert len(calls) == 2


async def test_http_errors_become_market_data_errors() -> None:
    rates = ecb(httpx.MockTransport(lambda r: httpx.Response(503, text="down")))
    with pytest.raises(MarketDataError, match="ECB FX rates: HTTPStatusError"):
        await rates.rate("EUR", "USD")
