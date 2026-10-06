from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from quant_core.fundamentals import (
    fundamental_lines,
    fundamental_metrics,
    fundamental_summary,
    fundamentals_inputs,
    piotroski,
)
from quant_core.indicators import (
    atr,
    compute_indicators,
    correlation,
    max_gap,
    relative_to,
)
from quant_core.models import (
    Action,
    AggregatedDecision,
    Bar,
    DecisionOutcome,
    Fundamentals,
    InsiderActivity,
    SelectionPick,
    SelectionResult,
    StockSelection,
    Timeframe,
    WatchlistEntry,
)
from quant_core.research import (
    describe_outcome,
    earnings_reaction,
    history_entries,
    history_inputs,
    selection_inputs,
)

D = Decimal
NOW = datetime(2026, 10, 5, 14, 0, tzinfo=UTC)
DAY0 = datetime(2025, 6, 2, 5, 0, tzinfo=UTC)


def bars(symbol: str, closes: list[float], opens: list[float] | None = None) -> list[Bar]:
    out = []
    for i, c in enumerate(closes):
        o = opens[i] if opens else c
        out.append(
            Bar(
                symbol=symbol,
                timeframe=Timeframe.D1,
                ts=DAY0 + timedelta(days=i),
                open=D(str(o)),
                high=D(str(max(o, c) + 1)),
                low=D(str(min(o, c) - 1)),
                close=D(str(c)),
                volume=D(1000),
            )
        )
    return out


def company(**overrides: object) -> Fundamentals:
    base: dict[str, object] = {
        "symbol": "ACME",
        "as_of": NOW,
        "name": "Acme Corp",
        "industry": "Widgets",
        "period_end": date(2026, 6, 30),
        "shares_outstanding": 100.0,
        "diluted_shares": 100.0,
        "diluted_shares_prev": 105.0,
        "revenue": 1000.0,
        "revenue_prev": 800.0,
        "gross_profit": 500.0,
        "gross_profit_prev": 380.0,
        "operating_income": 200.0,
        "net_income": 150.0,
        "net_income_prev": 100.0,
        "eps_diluted": 1.5,
        "eps_diluted_prev": 1.0,
        "operating_cash_flow": 180.0,
        "capex": 30.0,
        "dividends_paid": 50.0,
        "buybacks": 25.0,
        "total_assets": 2000.0,
        "total_assets_prev": 1900.0,
        "total_liabilities": 1200.0,
        "equity": 800.0,
        "current_assets": 600.0,
        "current_assets_prev": 500.0,
        "current_liabilities": 300.0,
        "current_liabilities_prev": 300.0,
        "long_term_debt": 400.0,
        "long_term_debt_prev": 450.0,
        "cash": 100.0,
    }
    return Fundamentals.model_validate({**base, **overrides})


# ------------------------------------------------------------------ indicators


def test_atr_gap_and_channels() -> None:
    series = bars("X", [100.0] * 70, opens=[100.0] * 60 + [104.0] + [100.0] * 9)
    assert atr(series[:10]) is None
    assert atr(series) == pytest.approx(2.0, abs=0.6)
    assert max_gap(series, 60) == pytest.approx(0.04)
    snap = compute_indicators(series)
    assert snap.high_20d == 105.0
    assert snap.low_20d == 99.0
    assert snap.high_55d == 105.0
    assert snap.low_55d == 99.0
    assert snap.atr_14 is not None
    assert snap.atr_14_pct == pytest.approx(snap.atr_14 / 100)


def test_relative_to_and_correlation() -> None:
    bench = [100 * (1.001**i) * (1.01 if i % 2 else 0.99) for i in range(300)]
    twice = [100 * (b / bench[0]) ** 2 for b in bench]  # moves twice as much
    s, b = bars("X", twice), bars("SPY", bench)
    rel = relative_to(s, b, "SPY")
    assert rel.days_used == 300
    assert rel.beta_1y == pytest.approx(2.0, rel=0.1)
    assert rel.correlation_1y == pytest.approx(1.0, abs=0.01)
    assert rel.relative_return_250d is not None
    assert rel.relative_return_250d > 0
    assert correlation(s, b, 60) == pytest.approx(1.0, abs=0.01)
    assert relative_to(s[:10], b, "SPY").beta_1y is None  # too little history


# ------------------------------------------------------------------ fundamentals


def test_metrics_with_price() -> None:
    m = fundamental_metrics(company(), price=30.0)
    assert m["market_cap"] == 3000.0
    assert m["pe"] == pytest.approx(20.0)
    assert m["pb"] == pytest.approx(3000 / 800)
    assert m["ev_ebit"] == pytest.approx((3000 + 400 - 100) / 200)
    assert m["fcf_yield"] == pytest.approx(150 / 3000)
    assert m["shareholder_yield"] == pytest.approx(75 / 3000)
    assert m["revenue_growth"] == pytest.approx(0.25)
    assert m["eps_growth"] == pytest.approx(0.5)
    assert m["peg"] == pytest.approx(20 / 50)
    assert m["gross_margin_change"] == pytest.approx(0.5 - 0.475)
    assert m["share_change"] == pytest.approx(100 / 105 - 1)
    assert m["cash_runway_years"] is None  # free cash flow is positive


def test_meaningless_ratios_are_none() -> None:
    loss = company(eps_diluted=-0.5, net_income=-50.0, equity=-10.0, operating_income=-5.0)
    m = fundamental_metrics(loss, price=30.0)
    assert m["pe"] is None
    assert m["pb"] is None
    assert m["ev_ebit"] is None
    assert m["roe"] is None
    lines = {line["id"]: line["value"] for line in fundamental_lines(loss, 30.0, NOW.date())}
    assert lines["fund:pe"] == "not meaningful (TTM loss)"
    assert fundamental_metrics(company(), price=None)["market_cap"] is None


def test_share_class_mismatch_and_financials() -> None:
    class_a = company(eps_diluted=40_000.0, net_income=4e9, shares_outstanding=100_000.0)
    m = fundamental_metrics(class_a, price=500.0)  # a Class B price
    assert m["market_cap"] is None
    assert m["pe"] is None
    assert m["fcf_yield"] is None
    assert m["roe"] is not None  # price-free ratios stay
    lines = {line["id"]: line["value"] for line in fundamental_lines(class_a, 500.0, NOW.date())}
    assert "another share class" in lines["fund:share_class"]
    assert "other share class" in fundamental_summary(class_a, 500.0)

    a_shares = company(eps_diluted=None, shares_outstanding=1.0)  # mcap 30 vs equity 800
    assert fundamental_metrics(a_shares, price=30.0)["market_cap"] is None

    bank = company(sic="6021")
    m = fundamental_metrics(bank, price=30.0)
    assert m["fcf_yield"] is None
    assert m["current_ratio"] is None
    assert m["accruals"] is None
    assert m["pe"] == pytest.approx(20.0)
    assert "fund:financial" in {line["id"] for line in fundamental_lines(bank, 30.0, NOW.date())}


def test_piotroski() -> None:
    assert piotroski(company()) == (9, 9)
    assert piotroski(company(current_assets=450.0)) == (8, 9)  # current ratio worsened
    assert piotroski(Fundamentals(symbol="X", as_of=NOW)) == (0, 0)
    assert fundamental_metrics(Fundamentals(symbol="X", as_of=NOW), 1.0)["f_score"] is None


def test_lines_summary_and_inputs() -> None:
    f = company(
        last_earnings_date=date(2026, 7, 30),
        next_earnings_estimate=date(2026, 10, 29),
        insider=InsiderActivity(window_days=90, filings=3, buys=2, buy_value=1e6, sells=1),
    )
    lines = {line["id"]: line for line in fundamental_lines(f, 30.0, NOW.date())}
    assert lines["fund:industry"]["value"] == "Widgets"
    assert lines["fund:pe"]["value"] == "20.0"
    assert lines["fund:gross_margin"]["value"] == "50.0%"
    assert lines["fund:revenue_growth"]["value"] == "+25.0%"
    assert lines["fund:f_score"]["value"].startswith("9 of 9")
    assert "in about 24 days" in lines["fund:next_earnings"]["value"]
    assert lines["fund:insider"]["value"].startswith("2 buys ($1.00M)")
    summary = fundamental_summary(f, 30.0)
    assert summary.startswith("Widgets; mcap $3.00K; P/E 20.0")
    assert "insider buys 2 / sells 1" in summary
    assert fundamental_summary(None, 30.0) == ""
    unavailable = Fundamentals(symbol="SPY", as_of=NOW, available=False)
    assert fundamental_summary(unavailable, 30.0) == ""
    assert fundamentals_inputs(unavailable, 30.0, NOW.date()) is None
    inputs = fundamentals_inputs(f, 30.0, NOW.date())
    assert inputs is not None
    assert inputs["period_end"] == "2026-06-30"


# ------------------------------------------------------------------ research


def agg(action: Action, created: datetime, run_id: UUID | None = None) -> AggregatedDecision:
    return AggregatedDecision(
        run_id=run_id or uuid4(),
        symbol="ACME",
        final_action=action,
        method="weighted_vote",
        score=0.2,
        votes=[],
        created_at=created,
    )


def test_describe_outcome() -> None:
    assert describe_outcome(Action.HOLD, None) == "nothing to execute"
    assert describe_outcome(Action.BUY, None) == "not executed, no risk review recorded"
    rejected = DecisionOutcome(risk_action=Action.HOLD, risk_reason="max_position_pct")
    assert describe_outcome(Action.BUY, rejected) == "rejected by risk (max_position_pct)"
    reduced = DecisionOutcome(risk_action=Action.BUY)
    assert describe_outcome(Action.STRONG_BUY, reduced).startswith("reduced by risk to buy")
    filled = DecisionOutcome(
        risk_action=Action.BUY, order_status="filled", filled_qty=D(5), avg_fill_price=D(10)
    )
    assert describe_outcome(Action.BUY, filled) == (
        "approved by risk; order filled, 5 shares filled at 10.00"
    )
    unsent = DecisionOutcome(risk_action=Action.BUY, order_status="dry_run")
    assert describe_outcome(Action.BUY, unsent).endswith("order dry_run, nothing filled")


def test_history_inputs_carry_outcomes() -> None:
    series = bars("ACME", [100.0 + i for i in range(30)])
    d = agg(Action.BUY, series[9].ts + timedelta(days=1, hours=1))
    entries = history_entries(
        [d], series, timedelta(days=1), {d.id: DecisionOutcome(risk_action=Action.HOLD)}
    )
    (row,) = history_inputs(entries)
    assert row["price_then"] == "109.00"
    assert row["change_since"] == "+18.35%"
    assert row["outcome"].startswith("rejected by risk")


def test_earnings_reaction() -> None:
    closes = [100.0] * 10 + [104.0, 110.0] + [99.0] * 8
    series = bars("ACME", closes)
    release = series[10].ts.date()
    f = company(last_earnings_date=release)
    line = earnings_reaction(f, series, 112.0)
    assert line is not None
    assert line["value"] == (
        "+10.00% over the first two sessions, +12.00% since the close before the release (held)"
    )
    faded = earnings_reaction(f, series, None)  # the last close, 99
    assert faded is not None
    assert faded["value"].endswith("(faded)")
    assert earnings_reaction(company(), series, 112.0) is None  # no release date known


def test_selection_inputs() -> None:
    run_id = uuid4()
    selection = StockSelection(
        run_id=run_id,
        pipeline_name="p",
        method="weighted_score",
        candidates=["AAA", "BBB", "CCC"],
        selected=["BBB", "AAA"],
        holdings=["ZZZ"],
        scores={"BBB": 0.8, "AAA": 0.6},
    )
    result = SelectionResult(
        run_id=run_id,
        instance_id=uuid4(),
        agent_id="momentum_screener",
        prompt_version="v1",
        pipeline_name="p",
        picks=[SelectionPick(symbol="BBB", score=0.9, reason="strong trend")],
    )
    out = selection_inputs(selection, [result], this_run=True)
    assert out["BBB"]["status"] == "selected, rank 1 of 2, aggregated score 0.80"
    assert out["BBB"]["reasons"] == [
        {"agent": "momentum_screener", "score": "0.90", "reason": "strong trend"}
    ]
    assert out["CCC"]["status"] == "screened in but not selected"
    assert out["ZZZ"]["status"].startswith("not selected; kept")
    assert out["AAA"]["when"] == "this run"


def test_selection_inputs_include_the_watchlist() -> None:
    run = uuid4()
    selection = StockSelection(
        run_id=run,
        pipeline_name="p",
        method="m",
        candidates=["NVDA", "AAPL"],
        selected=["NVDA"],
        watchlist=["AAPL"],
        scores={"NVDA": 0.8},
    )
    watchlist = [
        WatchlistEntry(
            pipeline_name="p",
            symbol="AAPL",
            added_at=NOW - timedelta(days=3),
            last_selected_at=NOW - timedelta(days=2),
            times_selected=2,
            last_score=0.7,
            last_reason="quality compounder near highs",
        ),
        WatchlistEntry(
            pipeline_name="p", symbol="KO", added_at=NOW, pinned=True, note="dividend idea"
        ),
    ]
    out = selection_inputs(selection, [], this_run=True, watchlist=watchlist)
    assert out["NVDA"]["status"].startswith("selected, rank 1 of 1")
    aapl = out["AAPL"]
    assert aapl["status"].startswith("not picked this time; still followed on the watchlist; ")
    assert "picked 2x, last on" in aapl["status"]
    assert aapl["reasons"][0]["reason"] == "quality compounder near highs"
    ko = out["KO"]  # added by hand, not a candidate of this run
    assert ko["when"] == "watchlist"
    assert ko["status"] == (
        f"on the watchlist since {NOW.date().isoformat()}, added by hand, pinned, "
        "note: dividend idea"
    )
    assert selection.universe == ["NVDA", "AAPL"]
    assert selection_inputs(None, [], this_run=False) == {}
