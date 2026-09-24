"""Broker interface, idempotency keys, and the two brokers that never touch a real account."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from quant_core.models import (
    Action,
    Fill,
    Instrument,
    OrderIntent,
    OrderResult,
    OrderStatus,
    OrderType,
    RunMode,
)
from quant_core.timeutil import utcnow


class BrokerError(RuntimeError):
    pass


def client_order_id(run_id: UUID, symbol: str, action: Action) -> str:
    """Idempotency key: the same run, symbol and action always give the same id."""
    digest = hashlib.sha256(f"{run_id}:{symbol.upper()}:{action.value}".encode()).hexdigest()
    return f"q-{digest[:24]}"


@runtime_checkable
class Broker(Protocol):
    name: str
    mode: RunMode  # which run mode this broker is for; the trading stage checks it matches

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def is_healthy(self) -> bool: ...

    async def submit(self, intent: OrderIntent, instrument: Instrument) -> OrderResult:
        """Send the order. Returns its state right after submission."""
        ...

    async def lookup(self, intent: OrderIntent) -> OrderResult | None:
        """The broker's view of an order by client_order_id; None if it never arrived."""
        ...

    async def cancel(self, intent: OrderIntent) -> OrderResult: ...


class DryRunBroker:
    """Records orders without sending them anywhere (status DRY_RUN, never filled)."""

    name = "dry_run"
    mode = RunMode.DRY_RUN

    def __init__(self) -> None:
        self.submitted: list[OrderIntent] = []

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def is_healthy(self) -> bool:
        return True

    async def submit(self, intent: OrderIntent, instrument: Instrument) -> OrderResult:
        self.submitted.append(intent)
        return OrderResult(
            client_order_id=intent.client_order_id,
            status=OrderStatus.DRY_RUN,
            message="dry run: order recorded, not sent",
        )

    async def lookup(self, intent: OrderIntent) -> OrderResult | None:
        return None

    async def cancel(self, intent: OrderIntent) -> OrderResult:
        return OrderResult(client_order_id=intent.client_order_id, status=OrderStatus.DRY_RUN)


FillMode = Literal["immediate", "partial", "never", "reject"]


@dataclass(slots=True)
class _SimOrder:
    intent: OrderIntent
    result: OrderResult


class SimulatedBroker:
    """In-memory broker that fills orders itself, for tests and offline simulation.

    - immediate: fills completely at the limit price (market orders at `market_price`)
    - partial: fills half the quantity, the rest stays open until cancelled
    - never: stays submitted until cancelled
    - reject: rejects every order
    """

    name = "simulated"
    mode = RunMode.DRY_RUN

    def __init__(
        self,
        fill_mode: FillMode = "immediate",
        *,
        market_price: Decimal | None = None,
        commission: Decimal = Decimal(1),
    ) -> None:
        self.fill_mode = fill_mode
        self.market_price = market_price
        self.commission = commission
        self.orders: dict[str, _SimOrder] = {}
        self.submit_count = 0
        self.healthy = True

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def is_healthy(self) -> bool:
        return self.healthy

    def _fill(self, intent: OrderIntent, qty: Decimal, seq: int) -> Fill:
        price = intent.limit_price if intent.order_type is OrderType.LIMIT else self.market_price
        if price is None:
            raise BrokerError("simulated market order needs market_price")
        return Fill(
            exec_id=f"sim-{intent.client_order_id}-{seq}",
            client_order_id=intent.client_order_id,
            symbol=intent.symbol,
            side=intent.side,
            qty=qty,
            price=price,
            commission=self.commission,
            ts=utcnow(),
        )

    async def submit(self, intent: OrderIntent, instrument: Instrument) -> OrderResult:
        self.submit_count += 1
        coid = intent.client_order_id
        broker_id = f"sim-{self.submit_count}"
        if self.fill_mode == "reject":
            result = OrderResult(
                client_order_id=coid,
                status=OrderStatus.REJECTED,
                broker_order_id=broker_id,
                message="simulated rejection",
            )
        elif self.fill_mode == "immediate":
            fill = self._fill(intent, intent.quantity, 1)
            result = OrderResult(
                client_order_id=coid,
                status=OrderStatus.FILLED,
                broker_order_id=broker_id,
                filled_qty=fill.qty,
                avg_fill_price=fill.price,
                fills=[fill],
            )
        elif self.fill_mode == "partial":
            half = (intent.quantity / 2).to_integral_value(rounding="ROUND_FLOOR")
            fills = [self._fill(intent, half, 1)] if half > 0 else []
            result = OrderResult(
                client_order_id=coid,
                status=OrderStatus.PARTIALLY_FILLED if fills else OrderStatus.SUBMITTED,
                broker_order_id=broker_id,
                filled_qty=half,
                avg_fill_price=fills[0].price if fills else None,
                fills=fills,
            )
        else:
            result = OrderResult(
                client_order_id=coid, status=OrderStatus.SUBMITTED, broker_order_id=broker_id
            )
        self.orders[coid] = _SimOrder(intent, result)
        return result

    async def lookup(self, intent: OrderIntent) -> OrderResult | None:
        order = self.orders.get(intent.client_order_id)
        return order.result if order else None

    async def cancel(self, intent: OrderIntent) -> OrderResult:
        order = self.orders.get(intent.client_order_id)
        if order is None:
            raise BrokerError(f"unknown order {intent.client_order_id}")
        if not order.result.status.is_terminal:
            order.result = order.result.model_copy(
                update={"status": OrderStatus.CANCELLED, "message": "cancelled", "ts": utcnow()}
            )
        return order.result
