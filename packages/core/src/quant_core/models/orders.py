"""Order intents, broker results and fills."""

from __future__ import annotations

from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from quant_core.models.base import (
    CoreModel,
    Money,
    NonNegativeMoney,
    PositiveMoney,
    PositiveQuantity,
    Quantity,
    Symbol,
)
from quant_core.models.enums import Action, OrderSide, OrderStatus, OrderType
from quant_core.timeutil import UtcDatetime, utcnow


class OrderIntent(CoreModel):
    client_order_id: str  # idempotency key
    run_id: UUID
    pipeline_name: str
    symbol: Symbol
    action: Action
    side: OrderSide
    quantity: PositiveQuantity
    order_type: OrderType
    limit_price: PositiveMoney | None = None
    time_in_force: str = "DAY"
    estimated_notional: NonNegativeMoney

    @model_validator(mode="after")
    def _check(self) -> Self:
        expected = {1: OrderSide.BUY, -1: OrderSide.SELL}.get(self.action.direction)
        if expected is None:
            raise ValueError("hold does not produce an order")
        if self.side is not expected:
            raise ValueError(f"{self.action} must be a {expected} order")
        if (self.order_type is OrderType.LIMIT) != (self.limit_price is not None):
            raise ValueError("limit_price is required for limit orders and only for them")
        return self


class Fill(CoreModel):
    exec_id: str  # broker execution id, unique
    client_order_id: str
    symbol: Symbol
    side: OrderSide
    qty: PositiveQuantity
    price: PositiveMoney
    commission: NonNegativeMoney = Decimal(0)
    ts: UtcDatetime


class OrderResult(CoreModel):
    client_order_id: str
    status: OrderStatus
    broker_order_id: str | None = None
    filled_qty: Quantity = Field(default=Decimal(0), ge=0)
    avg_fill_price: Money | None = None
    fills: list[Fill] = Field(default_factory=list)
    message: str | None = None
    ts: UtcDatetime = Field(default_factory=utcnow)
