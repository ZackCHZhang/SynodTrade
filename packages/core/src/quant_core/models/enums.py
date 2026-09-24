"""Enumerations shared by every package, including the five-tier trading action."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum


class Action(StrEnum):
    """Five-tier action. See `quant_core.sizing` for how the weights translate to quantities.

    Buy tiers are a fraction of the strategy's buy budget; sell tiers are a fraction of the
    current position in that symbol. There is no shorting: a sell with no position is HOLD.
    """

    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"

    @property
    def weight(self) -> Decimal:
        return ACTION_TO_WEIGHT[self]

    @property
    def direction(self) -> int:
        """+1 buy side, -1 sell side, 0 hold."""
        w = self.weight
        return (w > 0) - (w < 0)

    def is_reduction_of(self, original: Action) -> bool:
        """True if `self` is `original` moved toward (or onto) HOLD, never past it.

        This is the only kind of adjustment a risk layer may make: same direction with
        a smaller-or-equal magnitude, or HOLD. Reversing direction or enlarging is not.
        """
        if self is Action.HOLD:
            return True
        return self.direction == original.direction and abs(self.weight) <= abs(original.weight)

    @classmethod
    def nearest(cls, score: Decimal) -> Action:
        """Map a weight-like score back to the closest tier; ties resolve toward HOLD."""
        return min(cls, key=lambda a: (abs(a.weight - score), abs(a.weight)))


ACTION_TO_WEIGHT: dict[Action, Decimal] = {
    Action.STRONG_BUY: Decimal("0.30"),
    Action.BUY: Decimal("0.15"),
    Action.HOLD: Decimal("0"),
    Action.SELL: Decimal("-0.15"),
    Action.STRONG_SELL: Decimal("-0.30"),
}


class RunMode(StrEnum):
    DRY_RUN = "dry_run"  # nothing is sent to any broker
    PAPER = "paper"  # IBKR paper account
    LIVE = "live"  # real money; guarded by quant_core.safety


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(StrEnum):
    PENDING_SUBMIT = "pending_submit"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    DRY_RUN = "dry_run"  # recorded but intentionally never sent

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_ORDER_STATUSES


_TERMINAL_ORDER_STATUSES = frozenset(
    {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.DRY_RUN}
)


class Verdict(StrEnum):
    APPROVE = "approve"
    REDUCE = "reduce"
    REJECT = "reject"


class Timeframe(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    D1 = "1d"
    W1 = "1w"
