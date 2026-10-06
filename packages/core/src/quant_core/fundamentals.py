"""Fundamental ratios computed in code from `Fundamentals` and a price (never by the LLM).

Ratios that need a price (P/E, yields, market cap) use the price of the moment they are
shown, so stored fundamentals never go stale against the market. Every ratio is None when
an input is missing or the ratio is meaningless (e.g. P/E with negative earnings).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from quant_core.models import Fundamentals

TAX_RATE = 0.21  # US federal rate, for the NOPAT in ROIC


def _div(a: float | None, b: float | None, *, positive_b: bool = False) -> float | None:
    if a is None or b is None or b == 0 or (positive_b and b < 0):
        return None
    return a / b


def _growth(now: float | None, before: float | None) -> float | None:
    """now / before - 1, only for a positive base (growth from a loss is meaningless)."""
    if now is None or before is None or before <= 0:
        return None
    return now / before - 1


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def piotroski(f: Fundamentals) -> tuple[int, int]:
    """(F-score, number of the nine signals that could be evaluated)."""
    roa, roa_prev = _div(f.net_income, f.total_assets), _div(f.net_income_prev, f.total_assets_prev)
    lev = _div(f.long_term_debt, f.total_assets)
    lev_prev = _div(f.long_term_debt_prev, f.total_assets_prev)
    cr = _div(f.current_assets, f.current_liabilities)
    cr_prev = _div(f.current_assets_prev, f.current_liabilities_prev)
    gm, gm_prev = _div(f.gross_profit, f.revenue), _div(f.gross_profit_prev, f.revenue_prev)
    turn, turn_prev = _div(f.revenue, f.total_assets), _div(f.revenue_prev, f.total_assets_prev)

    def gt(a: float | None, b: float | None) -> bool | None:
        return None if a is None or b is None else a > b

    signals = [
        None if roa is None else roa > 0,
        None if f.operating_cash_flow is None else f.operating_cash_flow > 0,
        gt(roa, roa_prev),
        gt(f.operating_cash_flow, f.net_income),
        gt(lev_prev, lev) if lev is not None and lev_prev is not None else None,
        gt(cr, cr_prev),
        None
        if f.diluted_shares is None or f.diluted_shares_prev is None
        else f.diluted_shares <= f.diluted_shares_prev,
        gt(gm, gm_prev),
        gt(turn, turn_prev),
    ]
    known = [s for s in signals if s is not None]
    return sum(known), len(known)


def is_financial(f: Fundamentals) -> bool:
    """Banks, insurers, brokers, REITs (SIC 6000-6799): operating cash flow, free cash flow
    and current ratio are not meaningful for them."""
    return f.sic is not None and f.sic.isdigit() and 6000 <= int(f.sic) <= 6799


def share_class_mismatch(f: Fundamentals, price: float | None) -> bool:
    """The filings' per-share figures belong to another share class than the quoted price
    (e.g. BRK B priced, Class A shares reported). Caught by impossible relations: EPS above
    the price, or a market value below 5% of book value or 1% of revenue."""
    if price is None or price <= 0:
        return False
    eps = f.eps_diluted if f.eps_diluted is not None and f.eps_diluted > 0 else None
    dps = f.dividends_per_share
    if (eps is not None and eps > price) or (dps is not None and dps > price / 2):
        return True
    shares = f.shares_outstanding or f.diluted_shares
    if not shares:
        return False
    mcap = price * shares
    return (f.equity is not None and f.equity > 0 and mcap < 0.05 * f.equity) or (
        f.revenue is not None and f.revenue > 0 and mcap < 0.01 * f.revenue
    )


def fundamental_metrics(f: Fundamentals, price: float | None) -> dict[str, float | None]:
    """Every derived ratio by name (fractions, not percent)."""
    if share_class_mismatch(f, price):
        price = None  # price-based ratios would be off by the share-class factor
    if is_financial(f):
        f = f.model_copy(
            update={
                "operating_cash_flow": None,
                "operating_cash_flow_prev": None,
                "capex": None,
                "current_assets": None,
                "current_assets_prev": None,
                "current_liabilities": None,
                "current_liabilities_prev": None,
            }
        )
    shares = f.shares_outstanding or f.diluted_shares
    mcap = price * shares if price is not None and shares else None
    ev = None
    if mcap is not None:
        ev = mcap + (f.long_term_debt or 0.0) - (f.cash or 0.0)
    fcf = _sub(f.operating_cash_flow, f.capex) if f.capex is not None else f.operating_cash_flow
    invested = None
    if f.equity is not None:
        invested = f.equity + (f.long_term_debt or 0.0) - (f.cash or 0.0)
    nopat = f.operating_income * (1 - TAX_RATE) if f.operating_income is not None else None
    eps_growth = _growth(f.eps_diluted, f.eps_diluted_prev)
    pe = _div(price, f.eps_diluted, positive_b=True)
    dividend_yield = _div(f.dividends_per_share, price)
    if dividend_yield is None and f.dividends_paid is not None:
        dividend_yield = _div(f.dividends_paid, mcap)
    payouts = None
    if f.dividends_paid is not None or f.buybacks is not None:
        payouts = (f.dividends_paid or 0.0) + (f.buybacks or 0.0)
    ncav = _sub(f.current_assets, f.total_liabilities)
    score, known = piotroski(f)
    gm = _div(f.gross_profit, f.revenue, positive_b=True)
    gm_prev = _div(f.gross_profit_prev, f.revenue_prev, positive_b=True)
    runway = None
    if fcf is not None and fcf < 0 and f.cash is not None:
        runway = f.cash / -fcf
    return {
        "market_cap": mcap,
        "pe": pe,
        "earnings_yield": _div(f.eps_diluted, price),
        "pb": _div(mcap, f.equity, positive_b=True),
        "ps": _div(mcap, f.revenue, positive_b=True),
        "ev_ebit": _div(ev, f.operating_income, positive_b=True),
        "ebit_ev": _div(f.operating_income, ev, positive_b=True),
        "fcf": fcf,
        "fcf_yield": _div(fcf, mcap),
        "dividend_yield": dividend_yield,
        "buyback_yield": _div(f.buybacks, mcap),
        "shareholder_yield": _div(payouts, mcap),
        "payout_ratio": _div(f.dividends_paid, f.net_income, positive_b=True),
        "gross_margin": gm,
        "gross_margin_change": _sub(gm, gm_prev),
        "cash_runway_years": runway,
        "operating_margin": _div(f.operating_income, f.revenue, positive_b=True),
        "net_margin": _div(f.net_income, f.revenue, positive_b=True),
        "fcf_margin": _div(fcf, f.revenue, positive_b=True),
        "roe": _div(f.net_income, f.equity, positive_b=True),
        "roa": _div(f.net_income, f.total_assets, positive_b=True),
        "roic": _div(nopat, invested, positive_b=True),
        "debt_to_equity": _div(f.long_term_debt, f.equity, positive_b=True),
        "current_ratio": _div(f.current_assets, f.current_liabilities, positive_b=True),
        "revenue_growth": _growth(f.revenue, f.revenue_prev),
        "eps_growth": eps_growth,
        "quarter_revenue_growth": _growth(f.quarter_revenue, f.quarter_revenue_prev),
        "quarter_eps_growth": _growth(f.quarter_eps, f.quarter_eps_prev),
        "operating_income_growth": _growth(f.operating_income, f.operating_income_prev),
        "dividend_growth": _growth(f.dividends_per_share, f.dividends_per_share_prev),
        "share_change": _growth(f.diluted_shares, f.diluted_shares_prev),
        "peg": pe / (eps_growth * 100)
        if pe is not None and eps_growth and eps_growth > 0
        else None,
        "accruals": _div(
            _sub(f.net_income, f.operating_cash_flow), f.total_assets, positive_b=True
        ),
        "ncav": ncav,
        "ncav_to_market_cap": _div(ncav, mcap),
        "f_score": float(score) if known >= 6 else None,
        "f_score_signals": float(known),
    }


def fmt_money(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "-" if value < 0 else ""
    v = abs(value)
    for unit, size in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if v >= size:
            return f"{sign}${v / size:.2f}{unit}"
    return f"{sign}${v:.0f}"


def _pct(value: float) -> str:
    return f"{value * 100:+.1f}%"


def _upct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _ratio(value: float) -> str:
    return f"{value:.1f}"


def _ratio2(value: float) -> str:
    return f"{value:.2f}"


_FMT: dict[str, Callable[[float], str]] = {
    "money": fmt_money,
    "pct": _pct,  # signed: changes
    "upct": _upct,  # levels: margins, yields, returns on capital
    "ratio": _ratio,
    "ratio2": _ratio2,
}

# (key, label, format) in prompt order
_LINES: tuple[tuple[str, str, str], ...] = (
    ("market_cap", "Market cap", "money"),
    ("pe", "P/E (TTM diluted EPS)", "ratio"),
    ("pb", "Price / book", "ratio"),
    ("ps", "Price / sales", "ratio"),
    ("ev_ebit", "EV / EBIT", "ratio"),
    ("ebit_ev", "Earnings yield (EBIT / EV)", "upct"),
    ("fcf_yield", "Free cash flow yield", "upct"),
    ("dividend_yield", "Dividend yield", "upct"),
    ("buyback_yield", "Buyback yield", "upct"),
    ("shareholder_yield", "Shareholder yield (dividends + buybacks)", "upct"),
    ("payout_ratio", "Dividend payout ratio", "upct"),
    ("dividend_growth", "Dividend per share growth (1y)", "pct"),
    ("revenue_growth", "Revenue growth (TTM vs prior TTM)", "pct"),
    ("eps_growth", "EPS growth (TTM vs prior TTM)", "pct"),
    ("quarter_revenue_growth", "Latest quarter revenue vs year-ago quarter", "pct"),
    ("quarter_eps_growth", "Latest quarter EPS vs year-ago quarter", "pct"),
    ("peg", "PEG (P/E / EPS growth %)", "ratio"),
    ("gross_margin", "Gross margin", "upct"),
    ("gross_margin_change", "Gross margin change vs a year earlier (points)", "pct"),
    ("operating_margin", "Operating margin", "upct"),
    ("net_margin", "Net margin", "upct"),
    ("fcf_margin", "Free cash flow margin", "upct"),
    ("roe", "Return on equity", "upct"),
    ("roa", "Return on assets", "upct"),
    ("roic", "Return on invested capital (after 21% tax)", "upct"),
    ("debt_to_equity", "Long-term debt / equity", "ratio"),
    ("current_ratio", "Current ratio", "ratio"),
    ("share_change", "Diluted share count change (1y)", "pct"),
    ("accruals", "Accruals ((net income - operating cash flow) / assets)", "pct"),
    ("ncav_to_market_cap", "Net current asset value / market cap", "ratio2"),
    ("cash_runway_years", "Cash runway at the current free cash flow burn (years)", "ratio"),
)


def fundamental_lines(f: Fundamentals, price: float | None, today: date) -> list[dict[str, str]]:
    """Prompt lines `{id, label, value}` (ids `fund:<key>`) for every available figure."""
    if not f.available:
        return []
    m = fundamental_metrics(f, price)
    lines: list[dict[str, str]] = []

    def add(key: str, label: str, value: str) -> None:
        lines.append({"id": f"fund:{key}", "label": label, "value": value})

    if f.industry:
        add("industry", "Industry (SIC)", f.industry)
    if share_class_mismatch(f, price):
        add(
            "share_class",
            "Price-based ratios",
            "not available: the filings report per-share figures for another share class",
        )
    if is_financial(f):
        add(
            "financial",
            "Note",
            "financial company: cash flow and current-ratio figures are not meaningful",
        )
    for key, label, kind in _LINES:
        value = m[key]
        if value is not None:
            add(key, label, _FMT[kind](value))
    if m["f_score"] is not None:
        add(
            "f_score",
            "Piotroski F-score",
            f"{m['f_score']:.0f} of {m['f_score_signals']:.0f} signals evaluated (max 9)",
        )
    if f.eps_diluted is not None and f.eps_diluted <= 0:
        add("pe", "P/E", "not meaningful (TTM loss)")
    for key, label, amount in (
        ("revenue", "Revenue (TTM)", f.revenue),
        ("net_income", "Net income (TTM)", f.net_income),
        ("fcf", "Free cash flow (TTM)", m["fcf"]),
        ("cash", "Cash", f.cash),
        ("long_term_debt", "Long-term debt", f.long_term_debt),
    ):
        if amount is not None:
            add(key, label, fmt_money(amount))
    if f.last_earnings_date is not None:
        add(
            "last_earnings",
            "Last earnings release",
            f"{f.last_earnings_date.isoformat()} ({(today - f.last_earnings_date).days} days ago)",
        )
    if f.next_earnings_estimate is not None:
        days = (f.next_earnings_estimate - today).days
        when = f"in about {days} days" if days >= 0 else f"about {-days} days overdue"
        add(
            "next_earnings",
            "Next earnings (estimated: last release + one quarter)",
            f"{f.next_earnings_estimate.isoformat()} ({when})",
        )
    if f.insider is not None and f.insider.filings:
        i = f.insider
        bought, sold = fmt_money(i.buy_value), fmt_money(i.sell_value)
        add(
            "insider",
            f"Insider open-market trades, last {i.window_days} days",
            f"{i.buys} buys ({bought}), {i.sells} sells ({sold})",
        )
    return lines


def fundamental_summary(f: Fundamentals | None, price: float | None) -> str:
    """One compact line (for candidate lists and holdings), '' when nothing is known."""
    if f is None or not f.available:
        return ""
    m = fundamental_metrics(f, price)
    parts: list[str] = []
    if f.industry:
        parts.append(f.industry)
    if share_class_mismatch(f, price):
        parts.append("price ratios n/a (other share class)")
    for key, label, kind in (
        ("market_cap", "mcap", "money"),
        ("pe", "P/E", "ratio"),
        ("pb", "P/B", "ratio"),
        ("ev_ebit", "EV/EBIT", "ratio"),
        ("fcf_yield", "FCF yield", "upct"),
        ("dividend_yield", "div yield", "upct"),
        ("shareholder_yield", "shareholder yield", "upct"),
        ("revenue_growth", "rev growth", "pct"),
        ("eps_growth", "EPS growth", "pct"),
        ("quarter_eps_growth", "last Q EPS yoy", "pct"),
        ("gross_margin", "gross margin", "upct"),
        ("roic", "ROIC", "upct"),
        ("roe", "ROE", "upct"),
        ("debt_to_equity", "debt/equity", "ratio"),
        ("ncav_to_market_cap", "NCAV/mcap", "ratio2"),
    ):
        value = m[key]
        if value is not None:
            parts.append(f"{label} {_FMT[kind](value)}")
    if f.eps_diluted is not None and f.eps_diluted <= 0:
        parts.append("TTM loss")
    if m["f_score"] is not None:
        parts.append(f"F-score {m['f_score']:.0f}/{m['f_score_signals']:.0f}")
    if f.insider is not None and (f.insider.buys or f.insider.sells):
        parts.append(f"insider buys {f.insider.buys} / sells {f.insider.sells}")
    if f.next_earnings_estimate is not None:
        parts.append(f"next earnings ~{f.next_earnings_estimate.isoformat()}")
    return "; ".join(parts)


def fundamentals_inputs(
    f: Fundamentals | None, price: float | None, today: date
) -> dict[str, Any] | None:
    """Template input: `{source, period_end, filed, lines}` or None without data."""
    if f is None or not f.available:
        return None
    lines = fundamental_lines(f, price, today)
    if not lines:
        return None
    return {
        "source": f.source,
        "name": f.name or f.symbol,
        "period_end": f.period_end.isoformat() if f.period_end else "n/a",
        "filed": f.last_filed.isoformat() if f.last_filed else "n/a",
        "lines": lines,
    }
