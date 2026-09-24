from decimal import Decimal

import pytest

from quant_core.models import ACTION_TO_WEIGHT, Action, OrderSide
from quant_core.sizing import (
    BuyBase,
    SizingConfig,
    buy_base_amount,
    floor_to_lot,
    size_order,
    spendable_cash,
)

D = Decimal


# ------------------------------------------------------------------ Action


def test_weights_match_spec() -> None:
    assert {
        Action.STRONG_BUY: D("0.30"),
        Action.BUY: D("0.15"),
        Action.HOLD: D("0"),
        Action.SELL: D("-0.15"),
        Action.STRONG_SELL: D("-0.30"),
    } == ACTION_TO_WEIGHT
    assert Action.BUY.weight == D("0.15")


@pytest.mark.parametrize(
    ("action", "direction"),
    [
        (Action.STRONG_BUY, 1),
        (Action.BUY, 1),
        (Action.HOLD, 0),
        (Action.SELL, -1),
        (Action.STRONG_SELL, -1),
    ],
)
def test_direction(action: Action, direction: int) -> None:
    assert action.direction == direction


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (D("0.31"), Action.STRONG_BUY),
        (D("0.9"), Action.STRONG_BUY),
        (D("0.2"), Action.BUY),
        (D("0.225"), Action.BUY),  # tie between BUY and STRONG_BUY -> toward HOLD
        (D("0.075"), Action.HOLD),  # tie between HOLD and BUY -> HOLD
        (D("0"), Action.HOLD),
        (D("-0.08"), Action.SELL),
        (D("-0.225"), Action.SELL),
        (D("-5"), Action.STRONG_SELL),
    ],
)
def test_nearest(score: Decimal, expected: Action) -> None:
    assert Action.nearest(score) is expected


REDUCTIONS = {
    Action.STRONG_BUY: {Action.STRONG_BUY, Action.BUY, Action.HOLD},
    Action.BUY: {Action.BUY, Action.HOLD},
    Action.HOLD: {Action.HOLD},
    Action.SELL: {Action.SELL, Action.HOLD},
    Action.STRONG_SELL: {Action.STRONG_SELL, Action.SELL, Action.HOLD},
}


@pytest.mark.parametrize("original", list(Action))
@pytest.mark.parametrize("adjusted", list(Action))
def test_is_reduction_of_full_matrix(original: Action, adjusted: Action) -> None:
    assert adjusted.is_reduction_of(original) == (adjusted in REDUCTIONS[original])


# ------------------------------------------------------------------ helpers


@pytest.mark.parametrize(
    ("qty", "lot", "expected"),
    [
        (D("10.9"), D("1"), D("10")),
        (D("0.99"), D("1"), D("0")),
        (D("250"), D("100"), D("200")),
        (D("0"), D("1"), D("0")),
        (D("-3"), D("1"), D("0")),
        (D("1.2345"), D("0.01"), D("1.23")),
    ],
)
def test_floor_to_lot(qty: Decimal, lot: Decimal, expected: Decimal) -> None:
    assert floor_to_lot(qty, lot) == expected


def test_floor_to_lot_rejects_bad_lot() -> None:
    with pytest.raises(ValueError, match="lot_size"):
        floor_to_lot(D("1"), D("0"))


def test_buy_base_amount() -> None:
    assert buy_base_amount(BuyBase.AVAILABLE_CASH, ledger_cash=D(1000), ledger_nav=D(5000)) == 1000
    assert buy_base_amount(BuyBase.NAV, ledger_cash=D(1000), ledger_nav=D(5000)) == 5000
    assert buy_base_amount(BuyBase.AVAILABLE_CASH, ledger_cash=D(-5), ledger_nav=D(1)) == 0


def test_spendable_cash_is_capped_by_account() -> None:
    assert spendable_cash(ledger_cash=D(1000), account_available_cash=D(400)) == 400
    assert spendable_cash(ledger_cash=D(300), account_available_cash=D(400)) == 300
    assert spendable_cash(ledger_cash=D(300), account_available_cash=D(-1)) == 0


# ------------------------------------------------------------------ size_order


def _size(action: Action, **kw: object) -> object:
    args: dict[str, object] = {
        "price": D("100"),
        "base_amount": D("10000"),
        "cash_cap": D("10000"),
        "position_qty": D("0"),
    }
    args.update(kw)
    return size_order(action, **args)  # type: ignore[arg-type]


def test_hold_is_noop() -> None:
    sized = size_order(
        Action.HOLD, price=D(100), base_amount=D(1000), cash_cap=D(1000), position_qty=D(10)
    )
    assert sized.action is Action.HOLD
    assert not sized.is_trade
    assert sized.quantity == 0


@pytest.mark.parametrize(("action", "qty"), [(Action.BUY, D(15)), (Action.STRONG_BUY, D(30))])
def test_buy_tiers_use_fraction_of_base(action: Action, qty: Decimal) -> None:
    sized = size_order(
        action, price=D(100), base_amount=D(10000), cash_cap=D(10000), position_qty=D(0)
    )
    assert sized.side is OrderSide.BUY
    assert sized.quantity == qty
    assert sized.notional == qty * 100
    assert sized.is_trade


def test_buy_floors_to_whole_shares() -> None:
    # 15% of 1000 = 150 at 70/share -> 2.14 -> 2
    sized = size_order(
        Action.BUY, price=D(70), base_amount=D(1000), cash_cap=D(1000), position_qty=D(0)
    )
    assert sized.quantity == 2
    assert sized.notional == D(140)


def test_buy_capped_by_cash_when_base_is_nav() -> None:
    # 30% of NAV 100k = 30k, but only 5k spendable -> 50 shares at 100
    sized = size_order(
        Action.STRONG_BUY, price=D(100), base_amount=D(100000), cash_cap=D(5000), position_qty=D(0)
    )
    assert sized.quantity == 50


def test_buy_too_small_becomes_hold() -> None:
    sized = size_order(
        Action.BUY, price=D(500), base_amount=D(1000), cash_cap=D(1000), position_qty=D(0)
    )
    assert sized.action is Action.HOLD
    assert sized.requested is Action.BUY
    assert "too small" in sized.reason


def test_buy_respects_lot_size() -> None:
    cfg = SizingConfig(lot_size=D(10))
    sized = size_order(
        Action.STRONG_BUY,
        price=D(10),
        base_amount=D(1000),
        cash_cap=D(1000),
        position_qty=D(0),
        config=cfg,
    )
    assert sized.quantity == 30  # 300/10 = 30 -> multiple of 10


@pytest.mark.parametrize(("action", "qty"), [(Action.SELL, D(15)), (Action.STRONG_SELL, D(30))])
def test_sell_tiers_use_fraction_of_position(action: Action, qty: Decimal) -> None:
    sized = size_order(action, price=D(50), base_amount=D(0), cash_cap=D(0), position_qty=D(100))
    assert sized.side is OrderSide.SELL
    assert sized.quantity == qty
    assert sized.notional == qty * 50


def test_sell_without_position_becomes_hold() -> None:
    for pos in (D(0), D(-5)):
        sized = size_order(
            Action.STRONG_SELL, price=D(50), base_amount=D(0), cash_cap=D(0), position_qty=pos
        )
        assert sized.action is Action.HOLD
        assert sized.reason == "no position to sell"


def test_small_sell_floors_to_zero_by_default() -> None:
    sized = size_order(Action.SELL, price=D(50), base_amount=D(0), cash_cap=D(0), position_qty=D(3))
    assert sized.action is Action.HOLD
    assert "too small" in sized.reason


def test_small_sell_can_round_up_to_one_lot() -> None:
    cfg = SizingConfig(min_one_lot_on_sell=True)
    sized = size_order(
        Action.SELL, price=D(50), base_amount=D(0), cash_cap=D(0), position_qty=D(3), config=cfg
    )
    assert sized.quantity == 1
    assert sized.side is OrderSide.SELL


def test_round_up_never_exceeds_a_sub_lot_position() -> None:
    cfg = SizingConfig(min_one_lot_on_sell=True, lot_size=D(10))
    sized = size_order(
        Action.SELL, price=D(5), base_amount=D(0), cash_cap=D(0), position_qty=D(7), config=cfg
    )
    assert sized.action is Action.HOLD


def test_sell_quantity_never_exceeds_position() -> None:
    for pos in [D(1), D(7), D(99), D("12.5")]:
        for action in (Action.SELL, Action.STRONG_SELL):
            sized = size_order(
                action,
                price=D(10),
                base_amount=D(0),
                cash_cap=D(0),
                position_qty=pos,
                config=SizingConfig(min_one_lot_on_sell=True),
            )
            assert sized.quantity <= pos


@pytest.mark.parametrize(
    "kwargs",
    [
        {"price": D(0)},
        {"price": D(-1)},
        {"base_amount": D(-1)},
        {"cash_cap": D(-1)},
    ],
)
def test_invalid_inputs(kwargs: dict[str, Decimal]) -> None:
    with pytest.raises(ValueError, match="must"):
        _size(Action.BUY, **kwargs)


def test_sizing_config_validation() -> None:
    with pytest.raises(ValueError, match="greater than 0"):
        SizingConfig(lot_size=D(0))
    assert SizingConfig().buy_base is BuyBase.AVAILABLE_CASH
