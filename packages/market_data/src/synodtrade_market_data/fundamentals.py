"""Company fundamentals from SEC EDGAR, point in time, and their storage.

Only facts filed on or before `as_of` are used, so a run (or a replay) never sees a filing
from its future. Flow figures (revenue, earnings, cash flow) become trailing-twelve-month
values: the latest annual figure plus the current fiscal year to date minus the same period
of the previous year; quarters are reported directly or derived as annual minus nine months.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from synodtrade_core.logging import get_logger
from synodtrade_core.models import Fundamentals, InsiderActivity
from synodtrade_database import Repositories
from synodtrade_market_data.sec_edgar import SecEdgarClient

log = get_logger(__name__)

# Preferred concept first; companies switch tags over the years (e.g. revenue in 2018).
REVENUE = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenuesNetOfInterestExpense",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
)
GROSS_PROFIT = ("GrossProfit",)
OPERATING_INCOME = ("OperatingIncomeLoss",)
NET_INCOME = ("NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic")
EPS_DILUTED = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted")
OPERATING_CASH_FLOW = (
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
)
CAPEX = ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")
DIVIDENDS = ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock")
BUYBACKS = ("PaymentsForRepurchaseOfCommonStock",)
DPS = ("CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid")
DILUTED_SHARES = ("WeightedAverageNumberOfDilutedSharesOutstanding",)
ASSETS = ("Assets",)
LIABILITIES = ("Liabilities",)
EQUITY = (
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
)
CURRENT_ASSETS = ("AssetsCurrent",)
CURRENT_LIABILITIES = ("LiabilitiesCurrent",)
LONG_TERM_DEBT = (
    "LongTermDebtNoncurrent",
    "LongTermDebt",
    "LongTermDebtAndCapitalLeaseObligations",
)
CASH = (
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
)

YEAR = (350, 380)  # day count of an annual period
QUARTER = (80, 100)
NINE_MONTHS = (260, 285)
TOLERANCE = timedelta(days=10)


@dataclass(frozen=True, slots=True)
class Fact:
    start: date | None  # None for instants (balance sheet items)
    end: date
    value: float
    filed: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days if self.start is not None else 0


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def load_facts(
    company_facts: dict[str, Any], concepts: Sequence[str], unit: str, as_of: date
) -> list[Fact]:
    """Facts of the first concept that knows a period win; within a concept the latest
    filing (a restatement) wins. Facts filed after `as_of` are ignored."""
    taxonomies = company_facts.get("facts", {})
    chosen: dict[tuple[date | None, date], Fact] = {}
    for concept in concepts:
        entry = taxonomies.get("us-gaap", {}).get(concept) or taxonomies.get("dei", {}).get(concept)
        if not entry:
            continue
        own: dict[tuple[date | None, date], Fact] = {}
        for raw in entry.get("units", {}).get(unit, []):
            end, filed = _date(raw.get("end")), _date(raw.get("filed"))
            if end is None or filed is None or filed > as_of or raw.get("val") is None:
                continue
            start = _date(raw["start"]) if raw.get("start") else None
            fact = Fact(start, end, float(raw["val"]), filed)
            key = (start, end)
            if key not in own or own[key].filed <= filed:
                own[key] = fact
        for key, fact in own.items():
            chosen.setdefault(key, fact)
    return sorted(chosen.values(), key=lambda f: (f.end, f.days))


def _near(a: date, b: date) -> bool:
    return abs(a - b) <= TOLERANCE


def _in(days: int, bounds: tuple[int, int]) -> bool:
    return bounds[0] <= days <= bounds[1]


def ttm(facts: Sequence[Fact], end: date) -> float | None:
    """Trailing twelve months ending at `end`."""
    durations = [f for f in facts if f.start is not None and f.end == end]
    annual = [f for f in durations if _in(f.days, YEAR)]
    if annual:
        return annual[-1].value
    ytd = max((f for f in durations if f.days < YEAR[0]), key=lambda f: f.days, default=None)
    if ytd is None or ytd.start is None:
        return None
    prior_end = end - timedelta(days=365)
    prior = [
        f
        for f in facts
        if f.start is not None and _near(f.end, prior_end) and abs(f.days - ytd.days) <= 10
    ]
    fiscal_end = ytd.start - timedelta(days=1)
    full = [
        f for f in facts if f.start is not None and _in(f.days, YEAR) and _near(f.end, fiscal_end)
    ]
    if not prior or not full:
        return None
    return full[-1].value + ytd.value - prior[-1].value


def quarter(facts: Sequence[Fact], end: date) -> float | None:
    """The three months ending at `end` (reported, or annual minus nine months)."""
    durations = [f for f in facts if f.start is not None and f.end == end]
    direct = [f for f in durations if _in(f.days, QUARTER)]
    if direct:
        return direct[-1].value
    annual = [f for f in durations if _in(f.days, YEAR)]
    if not annual:
        return None
    start = annual[-1].start
    nine = [
        f
        for f in facts
        if f.start is not None and start is not None and abs((f.start - start).days) <= 3
        and _in(f.days, NINE_MONTHS)
    ]  # fmt: skip
    return annual[-1].value - nine[-1].value if nine else None


def instant(facts: Sequence[Fact], end: date) -> float | None:
    found = [f for f in facts if f.start is None and _near(f.end, end)]
    if not found:
        return None
    return min(found, key=lambda f: (abs((f.end - end).days), -f.filed.toordinal())).value


def latest_period_end(facts: Sequence[Fact]) -> date | None:
    return max((f.end for f in facts if f.start is not None), default=None)


def year_earlier(facts: Sequence[Fact], end: date) -> date | None:
    """The reported period end closest to one year before `end`."""
    target = end - timedelta(days=365)
    ends = {f.end for f in facts if f.start is not None and _near(f.end, target)}
    return min(ends, key=lambda d: abs((d - target).days)) if ends else None


def latest_value(facts: Sequence[Fact], end: date) -> float | None:
    """Latest quarter's value of a per-period average (e.g. weighted diluted shares)."""
    found = [f for f in facts if f.start is not None and f.end == end]
    return min(found, key=lambda f: f.days).value if found else None


# ------------------------------------------------------------------ filings


def recent_filings(submissions: dict[str, Any], as_of: date) -> list[dict[str, str]]:
    """The submissions index as rows, newest first, filed on or before `as_of`."""
    recent = submissions.get("filings", {}).get("recent", {})
    keys = ("form", "filingDate", "accessionNumber", "primaryDocument", "items")
    columns = [recent.get(k, []) for k in keys]
    rows = []
    for values in zip(*columns, strict=False):
        row = dict(zip(keys, (str(v) for v in values), strict=True))
        filed = _date(row["filingDate"])
        if filed is not None and filed <= as_of:
            rows.append(row)
    return sorted(rows, key=lambda r: r["filingDate"], reverse=True)


def last_earnings_release(filings: Sequence[dict[str, str]]) -> date | None:
    """Filing date of the latest 8-K reporting results of operations (item 2.02)."""
    for row in filings:
        if row["form"] == "8-K" and "2.02" in row.get("items", "").split(","):
            return _date(row["filingDate"])
    return None


def parse_form4(xml_text: str) -> list[tuple[str, float, float]]:
    """Open-market trades of a Form 4: (code P or S, shares, price)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    trades = []
    for tx in root.iter("nonDerivativeTransaction"):
        code = (tx.findtext("transactionCoding/transactionCode") or "").strip()
        if code not in ("P", "S"):
            continue
        try:
            shares = float(tx.findtext("transactionAmounts/transactionShares/value") or 0)
            price = float(tx.findtext("transactionAmounts/transactionPricePerShare/value") or 0)
        except ValueError:
            continue
        trades.append((code, shares, price))
    return trades


def insider_activity(documents: Sequence[str], window_days: int) -> InsiderActivity:
    buys = sells = 0
    buy_value = sell_value = 0.0
    for doc in documents:
        for code, shares, price in parse_form4(doc):
            if code == "P":
                buys += 1
                buy_value += shares * price
            else:
                sells += 1
                sell_value += shares * price
    return InsiderActivity(
        window_days=window_days,
        filings=len(documents),
        buys=buys,
        buy_value=buy_value,
        sells=sells,
        sell_value=sell_value,
    )


# ------------------------------------------------------------------ assembly


def compute_fundamentals(
    symbol: str,
    as_of: datetime,
    company_facts: dict[str, Any],
    submissions: dict[str, Any] | None = None,
    *,
    cik: int | None = None,
    name: str | None = None,
    insider: InsiderActivity | None = None,
) -> Fundamentals:
    day = as_of.date()

    def facts(concepts: Sequence[str], unit: str = "USD") -> list[Fact]:
        return load_facts(company_facts, concepts, unit, day)

    income = facts(NET_INCOME)
    revenue = facts(REVENUE)
    end = latest_period_end(income) or latest_period_end(revenue)
    base: dict[str, Any] = {
        "symbol": symbol,
        "as_of": as_of,
        "cik": cik,
        "name": name or company_facts.get("entityName"),
    }
    if submissions:
        base |= {
            "sic": str(submissions.get("sic") or "") or None,
            "industry": submissions.get("sicDescription") or None,
            "fiscal_year_end": submissions.get("fiscalYearEnd") or None,
        }
        filings = recent_filings(submissions, day)
        released = last_earnings_release(filings)
        base["last_earnings_date"] = released
        if released is not None:
            base["next_earnings_estimate"] = released + timedelta(days=91)
    base["insider"] = insider
    if end is None:
        return Fundamentals(**base, available=False, note="no financial statements filed")

    prev = year_earlier(income, end) or year_earlier(revenue, end)
    flows = {
        "revenue": revenue,
        "gross_profit": facts(GROSS_PROFIT),
        "operating_income": facts(OPERATING_INCOME),
        "net_income": income,
        "eps_diluted": facts(EPS_DILUTED, "USD/shares"),
        "operating_cash_flow": facts(OPERATING_CASH_FLOW),
        "dividends_per_share": facts(DPS, "USD/shares"),
    }
    values: dict[str, Any] = {}
    for key, series in flows.items():
        values[key] = ttm(series, end)
        values[f"{key}_prev"] = ttm(series, prev) if prev is not None else None
    for key, concepts in (("capex", CAPEX), ("dividends_paid", DIVIDENDS), ("buybacks", BUYBACKS)):
        values[key] = ttm(facts(concepts), end)

    quarter_end = latest_period_end(income)
    if quarter_end is not None:
        q_prev = year_earlier(income, quarter_end)
        eps = flows["eps_diluted"]
        values |= {
            "quarter_end": quarter_end,
            "quarter_revenue": quarter(revenue, quarter_end),
            "quarter_eps": quarter(eps, quarter_end),
            "quarter_revenue_prev": quarter(revenue, q_prev) if q_prev else None,
            "quarter_eps_prev": quarter(eps, q_prev) if q_prev else None,
        }

    balance = {
        "total_assets": facts(ASSETS),
        "current_assets": facts(CURRENT_ASSETS),
        "current_liabilities": facts(CURRENT_LIABILITIES),
        "long_term_debt": facts(LONG_TERM_DEBT),
    }
    for key, series in balance.items():
        values[key] = instant(series, end)
        values[f"{key}_prev"] = instant(series, prev) if prev is not None else None
    values["total_liabilities"] = instant(facts(LIABILITIES), end)
    values["equity"] = instant(facts(EQUITY), end)
    values["cash"] = instant(facts(CASH), end)
    assets, equity = values["total_assets"], values["equity"]
    if values["total_liabilities"] is None and assets is not None and equity is not None:
        values["total_liabilities"] = assets - equity  # some filers report only both totals

    shares = facts(DILUTED_SHARES, "shares")
    values["diluted_shares"] = latest_value(shares, end)
    values["diluted_shares_prev"] = latest_value(shares, prev) if prev is not None else None
    outstanding = facts(("EntityCommonStockSharesOutstanding",), "shares")
    if outstanding:
        last = max(f.end for f in outstanding)
        same_day = [f for f in outstanding if f.end == last]
        if len(same_day) == 1:  # several share classes: fall back to diluted shares
            values["shares_outstanding"] = same_day[0].value

    used = [f.filed for series in (*flows.values(), *balance.values()) for f in series]
    return Fundamentals(
        **base,
        period_end=end,
        last_filed=max(used) if used else None,
        **values,
    )


class FundamentalsUpdater:
    """Fetches fundamentals from SEC EDGAR and stores snapshots (core `FundamentalsRefresher`)."""

    def __init__(self, client: SecEdgarClient, repos: Repositories) -> None:
        self._client = client
        self._repos = repos

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, symbol: str, as_of: datetime) -> Fundamentals:
        found = await self._client.lookup(symbol)
        if found is None:
            return Fundamentals(
                symbol=symbol,
                as_of=as_of,
                available=False,
                note="not an SEC filer (e.g. an ETF or a foreign listing)",
            )
        cik, name = found
        facts = await self._client.company_facts(cik) or {}
        submissions = await self._client.submissions(cik)
        insider = None
        if submissions is not None and self._client.options.max_form4 > 0:
            insider = await self._insider(cik, submissions, as_of.date())
        return compute_fundamentals(
            symbol, as_of, facts, submissions, cik=cik, name=name, insider=insider
        )

    async def _insider(self, cik: int, submissions: dict[str, Any], day: date) -> InsiderActivity:
        window = self._client.options.insider_window_days
        since = day - timedelta(days=window)
        rows = [
            r
            for r in recent_filings(submissions, day)
            if r["form"] == "4" and (_date(r["filingDate"]) or since) > since
        ][: self._client.options.max_form4]
        documents = []
        for row in rows:
            doc = await self._client.filing_document(
                cik, row["accessionNumber"], row["primaryDocument"]
            )
            if doc is not None:
                documents.append(doc)
        return insider_activity(documents, window)

    async def refresh_fundamentals(
        self, symbols: Sequence[str], *, now: datetime, max_age: timedelta
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        fresh: list[Fundamentals] = []
        for symbol in dict.fromkeys(s.upper() for s in symbols):
            stored = await self._repos.fundamentals.get_latest(symbol, now)
            if stored is not None and now - stored.as_of < max_age:
                continue
            try:
                fresh.append(await self.fetch(symbol, now))
            except Exception as exc:  # one bad symbol must not stop the others
                errors[symbol] = f"{type(exc).__name__}: {exc}"
                log.warning("fundamentals.refresh_failed", symbol=symbol, error=str(exc))
        await self._repos.fundamentals.add(fresh)
        log.info(
            "fundamentals.refreshed",
            refreshed=[f.symbol for f in fresh],
            unavailable=[f.symbol for f in fresh if not f.available],
            errors=errors,
        )
        return errors
