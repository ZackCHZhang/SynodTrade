"""Rule engine boundaries. Defaults: NAV 10,000, cash 10,000, price 100, no positions."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from synodtrade_core.models import Action, OrderSide, Verdict
from synodtrade_core.sizing import SizedOrder, SizingConfig
from synodtrade_risk import (
    MarketSnapshot,
    PortfolioState,
    RiskRulesConfig,
    RuleEngine,
    RuleOutcome,
    reductions,
    verdict_between,
)

D = Decimal
A = Action
NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)


def rules(**overrides: Any) -> RiskRulesConfig:
    base: dict[str, Any] = {"name": "t", "max_order_notional": 2000}
    return RiskRulesConfig.model_validate({**base, **overrides})


def state(**overrides: Any) -> PortfolioState:
    base: dict[str, Any] = {"as_of": NOW, "nav": D(10_000), "cash": D(10_000)}
    return PortfolioState(**{**base, **overrides})


def market(
    price: str | None = "100", spread: str | None = "10", volume: str | None = "1000000"
) -> MarketSnapshot:
    return MarketSnapshot(
        price=D(price) if price else None,
        spread_bps=D(spread) if spread else None,
        avg_volume=D(volume) if volume else None,
    )


def evaluate(
    action: Action,
    *,
    cfg: RiskRulesConfig | None = None,
    st: PortfolioState | None = None,
    mk: MarketSnapshot | None = None,
    symbol: str = "AAPL",
    sizing: SizingConfig | None = None,
) -> RuleOutcome:
    engine = RuleEngine(cfg or rules(), sizing or SizingConfig())
    return engine.evaluate(symbol, action, mk or market(), st or state())


def blocking(outcome: RuleOutcome) -> set[str]:
    return {h.rule for h in outcome.hits if h.blocking}


# ------------------------------------------------------------------ helpers


def test_reductions_and_verdicts() -> None:
    assert reductions(A.STRONG_BUY) == [A.STRONG_BUY, A.BUY, A.HOLD]
    assert reductions(A.SELL) == [A.SELL, A.HOLD]
    assert reductions(A.HOLD) == [A.HOLD]
    assert verdict_between(A.BUY, A.BUY) is Verdict.APPROVE
    assert verdict_between(A.STRONG_SELL, A.SELL) is Verdict.REDUCE
    assert verdict_between(A.BUY, A.HOLD) is Verdict.REJECT
    assert verdict_between(A.HOLD, A.HOLD) is Verdict.APPROVE


# ------------------------------------------------------------------ approvals and size rules


def test_buy_passes_all_rules() -> None:
    out = evaluate(A.BUY)  # 15% of 10,000 = 1,500 -> 15 shares
    assert out.adjusted is A.BUY
    assert out.verdict is Verdict.APPROVE
    assert out.sized is not None
    assert (out.sized.quantity, out.sized.notional) == (D(15), D(1500))
    assert out.reason == "all risk rules passed"
    assert blocking(out) == set()


def test_strong_buy_reduced_to_buy_by_size_rules() -> None:
    out = evaluate(A.STRONG_BUY)  # 3,000: > notional limit 2,000 and 30% > 20% position
    assert out.adjusted is A.BUY
    assert out.verdict is Verdict.REDUCE
    assert blocking(out) == {"max_order_notional", "max_position_pct"}
    assert all(h.details["tier"] == "strong_buy" for h in out.hits)
    assert "strong_buy" in out.reason


@pytest.mark.parametrize(("existing", "expected"), [("500", A.BUY), ("501", A.HOLD)])
def test_max_position_boundary(existing: str, expected: Action) -> None:
    # after buying 1,500: (existing + 1,500) / 10,000 must be <= 20%
    st = state(position_qty={"AAPL": D(5)}, position_value={"AAPL": D(existing)})
    assert evaluate(A.BUY, st=st).adjusted is expected


@pytest.mark.parametrize(("gross", "expected"), [("7500", A.BUY), ("7501", A.HOLD)])
def test_gross_exposure_boundary(gross: str, expected: Action) -> None:
    st = state(position_value={"OTHER": D(gross)})  # + 1,500 must be <= 90% of 10,000
    assert evaluate(A.BUY, st=st).adjusted is expected


@pytest.mark.parametrize(("cash", "expected"), [("1100", A.BUY), ("1099", A.HOLD)])
def test_min_cash_boundary(cash: str, expected: Action) -> None:
    # 15% of cash buys 1 share (100): cash after must stay >= 10% of 10,000 = 1,000
    out = evaluate(A.BUY, st=state(cash=D(cash)))
    assert out.adjusted is expected
    if expected is A.HOLD:
        assert blocking(out) == {"min_cash_pct"}


@pytest.mark.parametrize(("limit", "expected"), [("1500", A.BUY), ("1499.99", A.HOLD)])
def test_max_order_notional_boundary(limit: str, expected: Action) -> None:
    assert evaluate(A.BUY, cfg=rules(max_order_notional=limit)).adjusted is expected


def test_no_notional_limit() -> None:
    cfg = rules(max_order_notional=None, max_position_pct="0.5")
    assert evaluate(A.STRONG_BUY, cfg=cfg).adjusted is A.STRONG_BUY


def test_nav_based_sizing_and_non_positive_nav() -> None:
    from synodtrade_core.sizing import BuyBase

    nav_sizing = SizingConfig(buy_base=BuyBase.NAV)
    out = evaluate(A.BUY, st=state(cash=D(5000)), sizing=nav_sizing)
    assert out.sized is not None
    assert out.sized.notional == D(1500)  # 15% of NAV, not of cash
    broke = evaluate(A.BUY, st=state(nav=D(0), cash=D(1000)))
    assert broke.adjusted is A.HOLD
    assert blocking(broke) == {"non_positive_nav"}


def test_order_too_small_is_informational() -> None:
    out = evaluate(A.BUY, mk=market(price="5000"))  # 1,500 buys no share at 5,000
    assert out.adjusted is A.BUY  # nothing to block; trading will skip the empty order
    assert out.sized is not None
    assert not out.sized.is_trade
    assert [(h.rule, h.blocking) for h in out.hits] == [("order_too_small", False)]


def test_sell_limited_only_by_notional() -> None:
    st = state(position_qty={"AAPL": D(100)}, position_value={"AAPL": D(20_000)})
    out = evaluate(A.STRONG_SELL, st=st, mk=market(price="200"))
    # 30 shares = 6,000 and 15 shares = 3,000 both exceed the 2,000 order limit
    assert out.adjusted is A.HOLD
    assert blocking(out) == {"max_order_notional"}
    lenient = evaluate(
        A.STRONG_SELL, st=st, mk=market(price="200"), cfg=rules(max_order_notional=10_000)
    )
    assert lenient.adjusted is A.STRONG_SELL  # position/exposure/cash rules never block sells


def test_sell_without_position_is_not_blocked() -> None:
    out = evaluate(A.SELL)
    assert out.adjusted is A.SELL
    assert out.sized is not None
    assert not out.sized.is_trade
    assert out.hits[0].message == "no position to sell"


# ------------------------------------------------------------------ gates that close everything


@pytest.mark.parametrize(
    ("kwargs", "rule"),
    [
        ({"cfg": rules(kill_switch=True)}, "kill_switch"),
        ({"st": state(kill_switch="manual stop")}, "kill_switch"),
        ({"cfg": rules(whitelist=["msft"])}, "whitelist"),
        ({"cfg": rules(blacklist=["aapl"])}, "blacklist"),
        ({"st": state(market_open=False)}, "trading_hours"),
        ({"mk": market(price=None)}, "no_price"),
        ({"st": state(trades_today=4)}, "max_trades_per_day"),
        ({"st": state(orders_today={"AAPL": 1})}, "one_order_per_symbol_per_day"),
    ],
)
@pytest.mark.parametrize("action", [A.STRONG_BUY, A.SELL])
def test_closing_gates_block_buys_and_sells(
    kwargs: dict[str, Any], rule: str, action: Action
) -> None:
    kwargs = dict(kwargs)  # parametrize shares the dict between the two `action` cases
    st = kwargs.pop("st", state(position_qty={"AAPL": D(10)}, position_value={"AAPL": D(1000)}))
    out = evaluate(action, st=st, **kwargs)
    assert out.adjusted is A.HOLD
    assert out.verdict is Verdict.REJECT
    assert rule in blocking(out)


def test_gates_that_do_not_apply() -> None:
    assert evaluate(A.BUY, cfg=rules(whitelist=["AAPL"])).adjusted is A.BUY
    assert evaluate(A.BUY, st=state(trades_today=3)).adjusted is A.BUY  # limit 4
    assert evaluate(A.BUY, st=state(orders_today={"MSFT": 1})).adjusted is A.BUY
    closed_but_ignored = rules(trading_hours={"enabled": False})
    assert evaluate(A.BUY, cfg=closed_but_ignored, st=state(market_open=False)).adjusted is A.BUY
    no_limits = rules(max_trades_per_day=None, one_order_per_symbol_per_day=False)
    busy = state(trades_today=100, orders_today={"AAPL": 3})
    assert evaluate(A.BUY, cfg=no_limits, st=busy).adjusted is A.BUY


def test_hold_is_never_blocked() -> None:
    out = evaluate(A.HOLD, cfg=rules(kill_switch=True), mk=market(price=None))
    assert out.adjusted is A.HOLD
    assert out.verdict is Verdict.APPROVE
    assert blocking(out) == set()
    assert {h.rule for h in out.hits} == {"kill_switch", "no_price"}  # still recorded


# ------------------------------------------------------------------ gates that stop buys only


@pytest.mark.parametrize(
    ("kwargs", "rule"),
    [
        ({"st": state(daily_return=D("-0.03"))}, "daily_loss_limit"),
        ({"st": state(weekly_return=D("-0.06"))}, "weekly_loss_limit"),
        ({"mk": market(spread="50.01")}, "liquidity_spread"),
        ({"mk": market(volume="99999")}, "liquidity_volume"),
        ({"mk": market(volume=None)}, "liquidity_volume"),
        (
            {"mk": market(spread=None), "cfg": rules(liquidity={"require_quote": True})},
            "liquidity_spread",
        ),
    ],
)
def test_buy_only_gates(kwargs: dict[str, Any], rule: str) -> None:
    kwargs = dict(kwargs)
    held = state(position_qty={"AAPL": D(10)}, position_value={"AAPL": D(1000)})
    st = kwargs.pop("st", held)
    if st is not held:
        st.position_qty, st.position_value = held.position_qty, held.position_value
    buy = evaluate(A.BUY, st=st, **kwargs)
    assert buy.adjusted is A.HOLD
    assert rule in blocking(buy)
    sell = evaluate(A.SELL, st=st, **kwargs)
    assert sell.adjusted is A.SELL  # reducing risk is still allowed
    assert rule in {h.rule for h in sell.hits}
    assert rule not in blocking(sell)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"st": state(daily_return=D("-0.0299"), weekly_return=D("-0.0599"))},
        {"mk": market(spread="50")},
        {"mk": market(volume="100000")},
        {
            "cfg": rules(max_daily_loss_pct=None, max_weekly_loss_pct=None),
            "st": state(daily_return=D("-0.5"), weekly_return=D("-0.5")),
        },
        {
            "cfg": rules(liquidity={"max_spread_bps": None, "min_avg_volume": None}),
            "mk": market(spread=None, volume=None),
        },
    ],
)
def test_buy_only_gates_just_inside_limits(kwargs: dict[str, Any]) -> None:
    assert evaluate(A.BUY, **kwargs).adjusted is A.BUY


def test_missing_quote_is_informational_by_default() -> None:
    out = evaluate(A.BUY, mk=market(spread=None))
    assert out.adjusted is A.BUY
    assert [(h.rule, h.blocking) for h in out.hits] == [("liquidity_spread", False)]


# ------------------------------------------------------------------ sequential portfolio effects


def test_portfolio_state_apply() -> None:
    st = state(position_qty={"AAPL": D(10)}, position_value={"AAPL": D(1000)})
    buy = SizedOrder(A.BUY, A.BUY, OrderSide.BUY, D(5), D(500), "buy tier")
    st.apply("AAPL", buy, D(100))
    assert (st.cash, st.position_qty["AAPL"], st.position_value["AAPL"]) == (
        D(9500),
        D(15),
        D(1500),
    )
    sell = SizedOrder(A.SELL, A.SELL, OrderSide.SELL, D(3), D(300), "sell tier")
    st.apply("AAPL", sell, D(100))
    assert st.cash == D(9500)  # sale proceeds are not counted before they settle
    assert (st.position_qty["AAPL"], st.position_value["AAPL"]) == (D(12), D(1200))
    assert st.trades_today == 2
    assert st.orders_today == {"AAPL": 2}
    st.apply("MSFT", SizedOrder(A.BUY, A.HOLD, None, D(0), D(0), "too small"), D(1))
    assert st.trades_today == 2
    assert st.gross_value == D(1200)


def test_approved_orders_count_against_later_symbols() -> None:
    cfg = rules(
        max_trades_per_day=10,
        max_order_notional=None,
        max_position_pct="1",
        max_gross_exposure_pct="0.4",
    )
    engine = RuleEngine(cfg, SizingConfig())
    st = state()
    results = []
    for symbol in ("A1", "A2", "A3"):
        out = engine.evaluate(symbol, A.STRONG_BUY, market(), st)
        if out.sized is not None:
            st.apply(symbol, out.sized, D(100))
        results.append((out.adjusted, out.sized.notional if out.sized else None))
    assert results == [
        (A.STRONG_BUY, D(3000)),  # 30% of 10,000 cash; exposure 30%
        (A.BUY, D(1000)),  # strong: 2,100 -> 51% > 40%; buy: 10 shares -> exactly 40%
        (A.HOLD, None),  # strong 58%, buy 49%: both over the exposure limit
    ]
    assert st.gross_value / st.nav == D("0.4")
    assert st.cash == D(6000)
