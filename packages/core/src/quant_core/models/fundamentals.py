"""Company fundamentals from regulatory filings (point in time: only facts filed by `as_of`).

Amounts are reported figures (USD for US filers), not prices, so they are plain floats like
the technical indicators. Price-dependent ratios (P/E, yields, ...) are not stored: they are
computed when used, from the price of that moment (`quant_core.fundamentals`).
"""

from __future__ import annotations

from datetime import date

from pydantic import Field

from quant_core.models.base import CoreModel, Symbol
from quant_core.timeutil import UtcDatetime


class InsiderActivity(CoreModel):
    """Open-market insider trades (Form 4 codes P and S) filed within the window."""

    window_days: int
    filings: int = 0  # Form 4 filings read
    buys: int = 0
    buy_value: float = 0.0
    sells: int = 0
    sell_value: float = 0.0


class Fundamentals(CoreModel):
    symbol: Symbol
    as_of: UtcDatetime  # facts filed after this instant are excluded
    source: str = "sec_edgar"
    available: bool = True  # False: the source has no filings for the symbol (e.g. an ETF)
    note: str | None = None

    cik: int | None = None
    name: str | None = None
    sic: str | None = None
    industry: str | None = None  # SIC description, e.g. "Electronic Computers"
    fiscal_year_end: str | None = None  # MMDD
    period_end: date | None = None  # end of the latest reported period
    last_filed: date | None = None  # filing date of the latest fact used

    shares_outstanding: float | None = None
    diluted_shares: float | None = None  # weighted average, latest period
    diluted_shares_prev: float | None = None  # one year earlier

    # trailing twelve months; `_prev` = the twelve months ending one year earlier
    revenue: float | None = None
    revenue_prev: float | None = None
    gross_profit: float | None = None
    gross_profit_prev: float | None = None
    operating_income: float | None = None
    operating_income_prev: float | None = None
    net_income: float | None = None
    net_income_prev: float | None = None
    eps_diluted: float | None = None
    eps_diluted_prev: float | None = None
    operating_cash_flow: float | None = None
    operating_cash_flow_prev: float | None = None
    capex: float | None = None
    dividends_paid: float | None = None
    buybacks: float | None = None
    dividends_per_share: float | None = None
    dividends_per_share_prev: float | None = None

    # latest quarter and the same quarter a year earlier
    quarter_end: date | None = None
    quarter_revenue: float | None = None
    quarter_revenue_prev: float | None = None
    quarter_eps: float | None = None
    quarter_eps_prev: float | None = None

    # balance sheet at period end and one year earlier
    total_assets: float | None = None
    total_assets_prev: float | None = None
    total_liabilities: float | None = None
    equity: float | None = None
    current_assets: float | None = None
    current_assets_prev: float | None = None
    current_liabilities: float | None = None
    current_liabilities_prev: float | None = None
    long_term_debt: float | None = None
    long_term_debt_prev: float | None = None
    cash: float | None = None

    last_earnings_date: date | None = None  # last earnings release (8-K item 2.02)
    next_earnings_estimate: date | None = None  # last release + one quarter (an estimate)
    insider: InsiderActivity | None = Field(default=None)
