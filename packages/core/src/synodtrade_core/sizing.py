"""Five-tier position sizing (spec §3.1). Pure, deterministic, Decimal-only.

- Buy tiers (+15% / +30%): spend that fraction of the *buy base* (the pipeline sub-ledger's
  cash or NAV, per `sizing.buy_base`), never more than the spendable cash.
- Sell tiers (-15% / -30%): sell that fraction of the *current position* (the pipeline's
  own sub-ledger position), floored to the lot size. No position -> HOLD (no shorting).
  A decision may give its own `sell_fraction` (0..1] instead of the tier's; 1 sells it all.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum

from pydantic import Field

from synodtrade_core.models.base import CoreModel
from synodtrade_core.models.enums import Action, OrderSide


class BuyBase(StrEnum):
    AVAILABLE_CASH = "available_cash"
    NAV = "nav"


class SizingConfig(CoreModel):
    buy_base: BuyBase = BuyBase.AVAILABLE_CASH
    # The spec floors sells, so a small position may never be sellable by a 15%/30% tier
    # (e.g. 3 shares * 15% -> 0). When True, a sell that floors to 0 sells one lot instead.
    min_one_lot_on_sell: bool = False
    lot_size: Decimal = Field(default=Decimal(1), gt=0)


@dataclass(frozen=True, slots=True)
class SizedOrder:
    requested: Action
    action: Action  # effective action; HOLD if sizing produced nothing to trade
    side: OrderSide | None
    quantity: Decimal
    notional: Decimal
    reason: str

    @property
    def is_trade(self) -> bool:
        return self.side is not None and self.quantity > 0


def floor_to_lot(quantity: Decimal, lot_size: Decimal) -> Decimal:
    if lot_size <= 0:
        raise ValueError("lot_size must be positive")
    if quantity <= 0:
        return Decimal(0)
    return (quantity / lot_size).to_integral_value(rounding=ROUND_FLOOR) * lot_size


def buy_base_amount(base: BuyBase, *, ledger_cash: Decimal, ledger_nav: Decimal) -> Decimal:
    """The amount a buy tier's percentage applies to, from the pipeline's sub-ledger."""
    raw = ledger_cash if base is BuyBase.AVAILABLE_CASH else ledger_nav
    return max(Decimal(0), raw)


def spendable_cash(*, ledger_cash: Decimal, account_available_cash: Decimal) -> Decimal:
    """Hard cap on any buy: the pipeline's own cash, never more than the account has."""
    return max(Decimal(0), min(ledger_cash, account_available_cash))


def adjusted_sell_fraction(
    fraction: Decimal | None, decided: Action, adjusted: Action
) -> Decimal | None:
    """A decision's own sell fraction after the risk layer turned `decided` into `adjusted`.

    Risk may only reduce: a lowered sell tier caps the fraction at that tier's fixed one.
    None: not a sell, or no own fraction (the tier's fixed fraction applies).
    """
    if fraction is None or adjusted.direction >= 0:
        return None
    return fraction if adjusted is decided else min(fraction, abs(adjusted.weight))


def size_order(
    action: Action,
    *,
    price: Decimal,
    base_amount: Decimal,
    cash_cap: Decimal,
    position_qty: Decimal,
    config: SizingConfig | None = None,
    sell_fraction: Decimal | None = None,
) -> SizedOrder:
    cfg = config or SizingConfig()
    if price <= 0:
        raise ValueError(f"price must be positive, got {price}")
    if base_amount < 0 or cash_cap < 0:
        raise ValueError("base_amount and cash_cap must not be negative")
    if sell_fraction is not None and not Decimal(0) < sell_fraction <= Decimal(1):
        raise ValueError(f"sell_fraction must be in (0, 1], got {sell_fraction}")

    def hold(reason: str) -> SizedOrder:
        return SizedOrder(action, Action.HOLD, None, Decimal(0), Decimal(0), reason)

    if action is Action.HOLD:
        return hold("hold")

    if action.direction > 0:
        target = min(base_amount * action.weight, cash_cap)
        qty = floor_to_lot(target / price, cfg.lot_size)
        if qty == 0:
            return hold(f"buy amount {target} too small for one lot at {price}")
        return SizedOrder(action, action, OrderSide.BUY, qty, qty * price, "buy tier")

    if position_qty <= 0:
        return hold("no position to sell")
    held = floor_to_lot(position_qty, cfg.lot_size)
    fraction = abs(action.weight) if sell_fraction is None else sell_fraction
    qty = floor_to_lot(position_qty * fraction, cfg.lot_size)
    reason = "sell tier" if sell_fraction is None else f"sell {fraction:%} (decision)"
    if qty == 0 and cfg.min_one_lot_on_sell and held > 0:
        qty, reason = cfg.lot_size, "sell tier rounded up to one lot"
    if qty == 0:
        return hold(f"position {position_qty} too small to sell {action.weight:%} of")
    return SizedOrder(action, action, OrderSide.SELL, qty, qty * price, reason)
