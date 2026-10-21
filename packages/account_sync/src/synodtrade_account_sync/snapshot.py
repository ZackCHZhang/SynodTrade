"""What the broker reports about one account at one instant, independent of `ib_async`.

A `BrokerReader` produces a `BrokerSnapshot`; the syncer compares it with the database.
Keeping this plain data makes the synchronisation logic testable without a gateway.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from synodtrade_core.models import (
    AccountSnapshot,
    Fill,
    OrderIntent,
    OrderResult,
    OrderStatus,
    Position,
)


@dataclass(frozen=True, slots=True)
class BrokerOrder:
    """An order as the broker lists it (open, or completed in the current session)."""

    ref: str  # orderRef: our client_order_id, or "" for orders placed elsewhere
    symbol: str
    side: str  # "buy" | "sell"
    quantity: Decimal
    status: OrderStatus
    broker_status: str  # the broker's own status text, e.g. "PreSubmitted"
    filled: Decimal = Decimal(0)
    avg_fill_price: Decimal | None = None
    limit_price: Decimal | None = None
    perm_id: int = 0
    order_id: int = 0
    open: bool = False  # listed among the open orders
    message: str | None = None

    @property
    def broker_order_id(self) -> str | None:
        return str(self.perm_id or self.order_id) if (self.perm_id or self.order_id) else None


@dataclass(frozen=True, slots=True)
class BrokerExecution:
    exec_id: str
    ref: str
    symbol: str
    side: str
    shares: Decimal
    price: Decimal
    ts: datetime
    commission: Decimal | None = None  # None: the commission report has not arrived


@dataclass(slots=True)
class BrokerSnapshot:
    account_id: str
    fetched_at: datetime
    orders: dict[str, BrokerOrder] = field(default_factory=dict)  # by ref (ours only)
    open_orders: list[BrokerOrder] = field(default_factory=list)  # every open order
    executions: dict[str, list[BrokerExecution]] = field(default_factory=dict)  # by ref
    account: AccountSnapshot | None = None
    positions: list[Position] = field(default_factory=list)
    account_error: str | None = None  # why `account` is missing

    def result_for(self, intent: OrderIntent, *, all_fills: bool = False) -> OrderResult | None:
        """The broker's view of one of our orders; None if it knows nothing about it.

        Status and quantities come from the order (open or completed) when the broker still
        lists it, otherwise from executions alone. Fills are included once their commission
        is known, or when the order is final or `all_fills` (fills are stored once, so
        waiting avoids recording a commission of 0 for a fill whose report is on its way).
        """
        coid = intent.client_order_id
        order = self.orders.get(coid)
        executions = self.executions.get(coid, [])
        if order is None and not executions:
            return None
        executed = sum((e.shares for e in executions), Decimal(0))
        if order is not None:
            filled = max(order.filled, executed)
            status = order.status
            if status is OrderStatus.SUBMITTED and filled > 0:
                status = OrderStatus.PARTIALLY_FILLED
            avg = order.avg_fill_price or _vwap(executions)
            message = order.message
        else:
            filled = executed
            status = (
                OrderStatus.FILLED if executed >= intent.quantity else OrderStatus.PARTIALLY_FILLED
            )
            avg = _vwap(executions)
            message = "recovered from executions"
        final = status.is_terminal or all_fills
        fills = [
            Fill(
                exec_id=e.exec_id,
                client_order_id=coid,
                symbol=intent.symbol,
                side=intent.side,
                qty=e.shares,
                price=e.price,
                commission=e.commission if e.commission is not None else Decimal(0),
                ts=e.ts,
            )
            for e in executions
            if e.commission is not None or final
        ]
        return OrderResult(
            client_order_id=coid,
            status=status,
            broker_order_id=order.broker_order_id if order is not None else None,
            filled_qty=filled,
            avg_fill_price=avg if filled > 0 else None,
            fills=fills,
            message=message,
        )

    def lists(self, client_order_id: str) -> bool:
        """Whether the broker lists the order itself (open or completed), not only fills."""
        return client_order_id in self.orders


def _vwap(executions: Sequence[BrokerExecution]) -> Decimal | None:
    qty = sum((e.shares for e in executions), Decimal(0))
    if qty <= 0:
        return None
    return sum((e.shares * e.price for e in executions), Decimal(0)) / qty


@runtime_checkable
class BrokerReader(Protocol):
    """Read-only access to one broker account. Never places or cancels orders."""

    account_id: str

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def snapshot(self, *, account: bool = True) -> BrokerSnapshot:
        """Orders, executions and (with `account`) the account summary and positions."""
        ...
