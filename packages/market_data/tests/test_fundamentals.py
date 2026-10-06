"""SEC EDGAR fundamentals: point-in-time math, Form 4 parsing, client, updater, stage."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest

from quant_core.config import PipelineConfig, StageConfig
from quant_core.models import Fundamentals, PipelineContext, RunMode, Timeframe
from quant_core.services import Services
from quant_database import Repositories
from quant_market_data import (
    FakeFundamentalsRefresher,
    FakeMarketDataProvider,
    FundamentalsUpdater,
    SecEdgarClient,
    SecEdgarError,
    build_data_update_stage,
    compute_fundamentals,
    generate_daily_bars,
)
from quant_market_data.fundamentals import (
    insider_activity,
    load_facts,
    parse_form4,
    quarter,
    ttm,
)
from quant_market_data.sec_edgar import SecEdgarOptions, sec_ticker

NOW = datetime(2026, 10, 5, 14, 0, tzinfo=UTC)
FY_START = date(2025, 1, 1)  # calendar fiscal years for readability


def fact(start: str | None, end: str, val: float, filed: str) -> dict[str, Any]:
    out: dict[str, Any] = {"end": end, "val": val, "filed": filed, "form": "10-Q"}
    if start is not None:
        out["start"] = start
    return out


def flow(values: dict[tuple[str, str], tuple[float, str]]) -> list[dict[str, Any]]:
    return [fact(s, e, v, f) for (s, e), (v, f) in values.items()]


# Revenue: FY2024 = 400 (Q4 2024 = 110), FY2025 = 480; 2026 quarters reported as 3-month and
# year-to-date facts, like a real 10-Q.
REVENUE = flow({
    ("2024-01-01", "2024-12-31"): (400, "2025-02-10"),
    ("2024-01-01", "2024-06-30"): (190, "2024-08-01"),
    ("2024-01-01", "2024-09-30"): (290, "2024-11-01"),
    ("2025-01-01", "2025-03-31"): (110, "2025-05-01"),
    ("2025-01-01", "2025-06-30"): (230, "2025-08-01"),
    ("2025-04-01", "2025-06-30"): (120, "2025-08-01"),
    ("2025-01-01", "2025-09-30"): (355, "2025-11-01"),
    ("2025-01-01", "2025-12-31"): (480, "2026-02-10"),
    ("2026-01-01", "2026-03-31"): (130, "2026-05-01"),
    ("2026-01-01", "2026-06-30"): (270, "2026-08-01"),
    ("2026-04-01", "2026-06-30"): (140, "2026-08-01"),
})  # fmt: skip
NET_INCOME = flow({
    ("2024-01-01", "2024-12-31"): (40, "2025-02-10"),
    ("2025-01-01", "2025-06-30"): (25, "2025-08-01"),
    ("2025-04-01", "2025-06-30"): (13, "2025-08-01"),
    ("2025-01-01", "2025-12-31"): (50, "2026-02-10"),
    ("2026-01-01", "2026-06-30"): (32, "2026-08-01"),
    ("2026-04-01", "2026-06-30"): (17, "2026-08-01"),
})  # fmt: skip
ASSETS = [
    fact(None, "2025-06-30", 900, "2025-08-01"),
    fact(None, "2026-06-30", 1000, "2026-08-01"),
]


def company_facts() -> dict[str, Any]:
    return {
        "entityName": "Acme Corp",
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": REVENUE}},
                "NetIncomeLoss": {"units": {"USD": NET_INCOME}},
                "Assets": {"units": {"USD": ASSETS}},
                "StockholdersEquity": {
                    "units": {"USD": [fact(None, "2026-06-30", 600, "2026-08-01")]}
                },
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {"shares": [fact(None, "2026-07-20", 50, "2026-08-01")]}
                }
            },
        },
    }


def submissions() -> dict[str, Any]:
    rows = [
        ("4", "2026-09-20", "0001-26-000003", "xslF345X05/form4.xml", ""),
        ("8-K", "2026-07-30", "0001-26-000002", "acme-8k.htm", "2.02,9.01"),
        ("8-K", "2026-06-01", "0001-26-000001", "acme-8k.htm", "5.02"),
        ("8-K", "2026-11-01", "0001-26-000009", "acme-8k.htm", "2.02"),  # after NOW
    ]
    keys = ("form", "filingDate", "accessionNumber", "primaryDocument", "items")
    return {
        "sic": "3571",
        "sicDescription": "Electronic Computers",
        "fiscalYearEnd": "1231",
        "filings": {"recent": {k: [r[i] for r in rows] for i, k in enumerate(keys)}},
    }


FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>20.5</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>5000</value></transactionShares>
        <transactionPricePerShare><value>1</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>200</value></transactionShares>
        <transactionPricePerShare><value>21</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


# ------------------------------------------------------------------ point-in-time math


def test_ttm_from_annual_plus_ytd_minus_prior_ytd() -> None:
    facts = load_facts(company_facts(), ["Revenues"], "USD", NOW.date())
    # FY2025 480 + H1 2026 270 - H1 2025 230
    assert ttm(facts, date(2026, 6, 30)) == 520
    assert ttm(facts, date(2025, 12, 31)) == 480  # an annual period directly
    # Q4 2025 = 480 - 355 (nine months); Q2 2026 reported directly
    assert quarter(facts, date(2025, 12, 31)) == 125
    assert quarter(facts, date(2026, 6, 30)) == 140


def test_facts_filed_later_are_invisible() -> None:
    before = load_facts(company_facts(), ["Revenues"], "USD", date(2026, 7, 1))
    assert max(f.end for f in before) == date(2026, 3, 31)
    assert ttm(before, date(2026, 3, 31)) == 480 + 130 - 110  # Q1 2026 TTM
    assert ttm(before, date(2026, 6, 30)) is None  # filed 2026-08-01: not known yet


def test_compute_fundamentals() -> None:
    f = compute_fundamentals("ACME", NOW, company_facts(), submissions(), cik=42)
    assert f.available
    assert f.name == "Acme Corp"
    assert f.cik == 42
    assert f.industry == "Electronic Computers"
    assert f.period_end == date(2026, 6, 30)
    assert f.revenue == 520
    assert f.revenue_prev == 400 + 230 - 190
    assert f.net_income == 50 + 32 - 25
    assert f.quarter_revenue == 140
    assert f.quarter_revenue_prev == 120
    assert f.quarter_eps is None  # no EPS facts
    assert f.total_assets == 1000
    assert f.total_assets_prev == 900
    assert f.equity == 600
    assert f.total_liabilities == 400  # derived from assets - equity
    assert f.shares_outstanding == 50
    assert f.last_filed == date(2026, 8, 1)
    assert f.last_earnings_date == date(2026, 7, 30)  # the November 8-K is in the future
    assert f.next_earnings_estimate == date(2026, 10, 29)


def test_compute_without_statements() -> None:
    f = compute_fundamentals("SPY", NOW, {"facts": {}}, None)
    assert not f.available
    assert f.note == "no financial statements filed"


def test_form4_parsing() -> None:
    assert parse_form4(FORM4) == [("P", 1000.0, 20.5), ("S", 200.0, 21.0)]
    assert parse_form4("not xml") == []
    activity = insider_activity([FORM4, FORM4], 90)
    assert (activity.filings, activity.buys, activity.sells) == (2, 2, 2)
    assert activity.buy_value == pytest.approx(41_000)


def test_sec_ticker() -> None:
    assert sec_ticker("brk b") == "BRK-B"
    assert sec_ticker("BF.B") == "BF-B"


# ------------------------------------------------------------------ client + updater


def sec_transport(calls: list[str], *, fail_once: bool = False) -> httpx.MockTransport:
    state = {"failed": False}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        assert "@" in request.headers["User-Agent"]
        if fail_once and not state["failed"]:
            state["failed"] = True
            return httpx.Response(429)
        if url.endswith("company_tickers.json"):
            return httpx.Response(
                200, json={"0": {"cik_str": 42, "ticker": "ACME", "title": "Acme Corp"}}
            )
        if "companyfacts/CIK0000000042" in url:
            return httpx.Response(200, json=company_facts())
        if "submissions/CIK0000000042" in url:
            return httpx.Response(200, json=submissions())
        if url.endswith("/Archives/edgar/data/42/000126000003/form4.xml"):
            return httpx.Response(200, text=FORM4)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def no_sleep(_: float) -> None:
    return None


def client(calls: list[str], **kw: Any) -> SecEdgarClient:
    return SecEdgarClient(
        "Test test@example.com",
        SecEdgarOptions(max_requests_per_second=10),
        client=httpx.AsyncClient(transport=sec_transport(calls, **kw)),
        sleep=no_sleep,
    )


def test_user_agent_needs_an_email() -> None:
    with pytest.raises(SecEdgarError):
        SecEdgarClient("no contact")
    with pytest.raises(SecEdgarError, match="SEC_EDGAR_USER_AGENT"):
        SecEdgarClient.from_env(env={})


async def test_updater_fetches_stores_and_skips_fresh(repos: Repositories) -> None:
    calls: list[str] = []
    updater = FundamentalsUpdater(client(calls, fail_once=True), repos)
    errors = await updater.refresh_fundamentals(
        ["ACME", "SPY"], now=NOW, max_age=timedelta(hours=20)
    )
    assert errors == {}
    acme = await repos.fundamentals.get_latest("ACME", NOW)
    assert acme is not None
    assert acme.revenue == 520
    assert acme.insider is not None
    assert acme.insider.buys == 1
    spy = await repos.fundamentals.get_latest("SPY", NOW)
    assert spy is not None
    assert not spy.available
    first = len(calls)
    await updater.refresh_fundamentals(["ACME", "SPY"], now=NOW, max_age=timedelta(hours=20))
    assert len(calls) == first  # both fresh
    await updater.refresh_fundamentals(
        ["ACME"], now=NOW + timedelta(days=1), max_age=timedelta(hours=20)
    )
    assert len(calls) > first
    await updater.aclose()


async def test_repository_is_point_in_time(repos: Repositories) -> None:
    await repos.fundamentals.add(
        [
            Fundamentals(symbol="ACME", as_of=NOW - timedelta(days=2), revenue=1.0),
            Fundamentals(symbol="ACME", as_of=NOW, revenue=2.0),
        ]
    )
    old = await repos.fundamentals.get_latest("acme", NOW - timedelta(days=1))
    assert old is not None
    assert old.revenue == 1.0
    many = await repos.fundamentals.get_latest_many(["ACME", "NONE"], NOW)
    assert list(many) == ["ACME"]
    assert many["ACME"].revenue == 2.0


# ------------------------------------------------------------------ data_update stage


def pipeline(benchmark: str | None = "SPY") -> PipelineConfig:
    return PipelineConfig.model_validate(
        {
            "name": "p",
            "account": "acc",
            "universe": ["AAPL"],
            "benchmark": benchmark,
            "budget": {"max_capital": 1000},
            "stages": [{"type": "data_update"}],
        }
    )


async def test_stage_updates_benchmark_and_fundamentals(repos: Repositories) -> None:
    start = (NOW - timedelta(days=500)).date()
    bars = generate_daily_bars("AAPL", start, 300) + generate_daily_bars("SPY", start, 300)
    fundamentals = FakeFundamentalsRefresher(repos)
    services = Services(
        repos=repos,
        market_data=FakeMarketDataProvider(bars),
        pipeline=pipeline(),
        fundamentals=fundamentals,
    )
    config = StageConfig.model_validate({"type": "data_update", "fundamentals": True})
    stage = build_data_update_stage(config, services)
    ctx = PipelineContext(pipeline_name="p", mode=RunMode.DRY_RUN, universe=["AAPL"], as_of=NOW)
    await stage.run(ctx)
    assert await repos.bars.get_latest_bars("SPY", 5, Timeframe.D1, as_of=NOW)
    assert fundamentals.refreshed == ["AAPL"]  # the benchmark is not a company to analyse
    stored = await repos.fundamentals.get_latest("AAPL", NOW)
    assert stored is not None
    assert stored.source == "fake"


async def test_stage_survives_missing_or_failing_fundamentals(repos: Repositories) -> None:
    start = (NOW - timedelta(days=500)).date()
    bars = generate_daily_bars("AAPL", start, 300)
    config = StageConfig.model_validate({"type": "data_update", "fundamentals": True})
    ctx = PipelineContext(pipeline_name="p", mode=RunMode.DRY_RUN, universe=["AAPL"], as_of=NOW)
    without = Services(
        repos=repos, market_data=FakeMarketDataProvider(bars), pipeline=pipeline(None)
    )
    await build_data_update_stage(config, without).run(ctx)  # logs, does not raise
    failing = without.with_(fundamentals=FakeFundamentalsRefresher(repos, fail_symbols=["AAPL"]))
    await build_data_update_stage(config, failing).run(ctx)
    assert await repos.fundamentals.get_latest("AAPL", NOW) is None
    # benchmark bars that cannot be fetched do not fail the stage either
    no_spy = Services(repos=repos, market_data=FakeMarketDataProvider(bars), pipeline=pipeline())
    await build_data_update_stage(StageConfig(type="data_update"), no_spy).run(ctx)
