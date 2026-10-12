"""Orders (idempotent by client_order_id), fills, and the per-pipeline sub-ledger."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from quant_core.models import Fill, OrderIntent, OrderResult, OrderSide, OrderStatus
from quant_core.timeutil import utcnow
from quant_database.models import FillRow, OrderRow
from quant_database.records import LedgerPosition, LedgerState, OrderRecord
from quant_database.repositories.base import (
    Repository,
    as_of_or_now,
    table_of,
    upsert_insert,
)

_OPEN_STATUSES = [s.value for s in OrderStatus if not s.is_terminal]
_INTENT_FIELDS = tuple(OrderIntent.model_fields)


def _to_record(row: OrderRow) -> OrderRecord:
    intent = OrderIntent.model_validate({k: getattr(row, k) for k in _INTENT_FIELDS})
    return OrderRecord(
        id=row.id,
        intent=intent,
        status=OrderStatus(row.status),
        broker_order_id=row.broker_order_id,
        filled_qty=row.filled_qty,
        avg_fill_price=row.avg_fill_price,
        message=row.message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class OrderRepository(Repository):
    async def create(
        self,
        intent: OrderIntent,
        status: OrderStatus = OrderStatus.PENDING_SUBMIT,
        *,
        created_at: datetime | None = None,
    ) -> tuple[OrderRecord, bool]:
        """Insert the order unless its client_order_id already exists.

        Returns (record, created). `created=False` means this intent was already recorded
        (e.g. a re-run of the same run_id) and must NOT be sent to the broker again.
        `created_at` defaults to now; pass the run's `as_of` so replays date orders
        consistently (daily trade counts are based on it).
        """
        now = created_at or utcnow()
        values = {
            **intent.model_dump(mode="python"),
            "status": status.value,
            "filled_qty": Decimal(0),
            "created_at": now,
            "updated_at": now,
        }
        stmt = (
            upsert_insert(self._db.dialect, table_of(OrderRow))
            .values(values)
            .on_conflict_do_nothing(index_elements=["client_order_id"])
            .returning(OrderRow.id)
        )
        async with self._db.transaction() as s:
            created = (await s.execute(stmt)).scalar_one_or_none() is not None
            row = (
                await s.execute(
                    select(OrderRow).where(OrderRow.client_order_id == intent.client_order_id)
                )
            ).scalar_one()
            return _to_record(row), created

    async def get(self, client_order_id: str) -> OrderRecord | None:
        async with self._db.transaction() as s:
            row = (
                await s.execute(select(OrderRow).where(OrderRow.client_order_id == client_order_id))
            ).scalar_one_or_none()
        return None if row is None else _to_record(row)

    async def apply_result(self, result: OrderResult) -> OrderRecord:
        """Update status/fill summary from the broker and store new fills (deduped by exec_id)."""
        async with self._db.transaction() as s:
            row = (
                await s.execute(
                    select(OrderRow).where(OrderRow.client_order_id == result.client_order_id)
                )
            ).scalar_one_or_none()
            if row is None:
                raise KeyError(f"unknown order {result.client_order_id}")
            if OrderStatus(row.status).is_terminal and row.status != result.status.value:
                raise ValueError(
                    f"order {row.client_order_id} is already {row.status}; "
                    f"refusing to change it to {result.status}"
                )
            row.status = result.status.value
            row.broker_order_id = result.broker_order_id or row.broker_order_id
            row.filled_qty = result.filled_qty
            row.avg_fill_price = result.avg_fill_price
            row.message = result.message
            row.updated_at = utcnow()
            await self._insert_fills(s, row, result.fills)
            return _to_record(row)

    async def correct_closed(self, result: OrderResult) -> OrderRecord:
        """Correct an order already closed (cancelled, rejected or filled) with what the
        broker reported later: fills that arrived after it was closed, e.g. an order marked
        cancelled because the broker did not list it, that was in fact executed.

        Unlike `apply_result` this may change a final status, but only to another final
        one, never for dry-run orders, and never lowering the filled quantity.
        """
        if not result.status.is_terminal or result.status is OrderStatus.DRY_RUN:
            raise ValueError(f"a correction needs a final broker status, not {result.status}")
        async with self._db.transaction() as s:
            row = (
                await s.execute(
                    select(OrderRow).where(OrderRow.client_order_id == result.client_order_id)
                )
            ).scalar_one_or_none()
            if row is None:
                raise KeyError(f"unknown order {result.client_order_id}")
            status = OrderStatus(row.status)
            if not status.is_terminal or status is OrderStatus.DRY_RUN:
                raise ValueError(f"order {row.client_order_id} is {row.status}; not correctable")
            if result.filled_qty < row.filled_qty:
                raise ValueError(
                    f"order {row.client_order_id}: refusing to lower the filled quantity "
                    f"from {row.filled_qty} to {result.filled_qty}"
                )
            row.status = result.status.value
            row.broker_order_id = result.broker_order_id or row.broker_order_id
            row.filled_qty = result.filled_qty
            row.avg_fill_price = result.avg_fill_price or row.avg_fill_price
            row.message = result.message
            row.updated_at = utcnow()
            await self._insert_fills(s, row, result.fills)
            return _to_record(row)

    async def _insert_fills(
        self, session: AsyncSession, row: OrderRow, fills: Sequence[Fill]
    ) -> None:
        wrong = [f.exec_id for f in fills if f.client_order_id != row.client_order_id]
        if wrong:
            raise ValueError(f"fills {wrong} do not belong to order {row.client_order_id}")
        if not fills:
            return
        stmt = upsert_insert(self._db.dialect, table_of(FillRow)).on_conflict_do_nothing(
            index_elements=["exec_id"]
        )
        await session.execute(
            stmt,
            [
                {
                    "order_id": row.id,
                    "exec_id": f.exec_id,
                    "symbol": f.symbol,
                    "side": f.side.value,
                    "qty": f.qty,
                    "price": f.price,
                    "commission": f.commission,
                    "ts": f.ts,
                }
                for f in fills
            ],
        )

    async def get_fills(self, client_order_id: str) -> list[Fill]:
        stmt = (
            select(FillRow)
            .join(OrderRow, OrderRow.id == FillRow.order_id)
            .where(OrderRow.client_order_id == client_order_id)
            .order_by(FillRow.ts, FillRow.id)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [
            Fill(
                exec_id=r.exec_id,
                client_order_id=client_order_id,
                symbol=r.symbol,
                side=OrderSide(r.side),
                qty=r.qty,
                price=r.price,
                commission=r.commission,
                ts=r.ts,
            )
            for r in rows
        ]

    async def list_by_run(self, run_id: UUID) -> list[OrderRecord]:
        stmt = select(OrderRow).where(OrderRow.run_id == run_id).order_by(OrderRow.id)
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [_to_record(r) for r in rows]

    async def list_open(self, pipeline_name: str | None = None) -> list[OrderRecord]:
        stmt = select(OrderRow).where(OrderRow.status.in_(_OPEN_STATUSES)).order_by(OrderRow.id)
        if pipeline_name is not None:
            stmt = stmt.where(OrderRow.pipeline_name == pipeline_name)
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [_to_record(r) for r in rows]

    async def list_closed_since(
        self, since: datetime, pipeline_names: Sequence[str] | None = None
    ) -> list[OrderRecord]:
        """Orders sent to a broker that were closed (filled, cancelled, rejected) at or
        after `since` — candidates for fills reported late."""
        closed = [s.value for s in OrderStatus if s.is_terminal and s is not OrderStatus.DRY_RUN]
        stmt = (
            select(OrderRow)
            .where(OrderRow.status.in_(closed), OrderRow.updated_at >= since)
            .order_by(OrderRow.id)
        )
        if pipeline_names is not None:
            stmt = stmt.where(OrderRow.pipeline_name.in_(list(pipeline_names)))
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [_to_record(r) for r in rows]

    async def count_since(
        self, pipeline_name: str, since: datetime, *, symbol: str | None = None
    ) -> int:
        """Orders created since `since` (any status except rejected) — for trade-count limits."""
        stmt = select(func.count(OrderRow.id)).where(
            OrderRow.pipeline_name == pipeline_name,
            OrderRow.created_at >= since,
            OrderRow.status != OrderStatus.REJECTED.value,
        )
        if symbol is not None:
            stmt = stmt.where(OrderRow.symbol == symbol.upper())
        async with self._db.transaction() as s:
            return int((await s.execute(stmt)).scalar_one())


class LedgerRepository(Repository):
    """Derives a pipeline's virtual sub-account from its own orders and fills.

    All arithmetic is done in Python with Decimal (see `quant_database.column_types`).
    """

    async def get_state(
        self, pipeline_name: str, max_capital: Decimal, as_of: datetime | None = None
    ) -> LedgerState:
        cutoff = as_of_or_now(as_of)
        fills_stmt = (
            select(FillRow)
            .join(OrderRow, OrderRow.id == FillRow.order_id)
            .where(OrderRow.pipeline_name == pipeline_name, FillRow.ts <= cutoff)
            .order_by(FillRow.ts, FillRow.id)
        )
        open_stmt = select(OrderRow).where(
            OrderRow.pipeline_name == pipeline_name,
            OrderRow.side == OrderSide.BUY.value,
            OrderRow.status.in_(_OPEN_STATUSES),
            OrderRow.created_at <= cutoff,
        )
        async with self._db.transaction() as s:
            fills = (await s.execute(fills_stmt)).scalars().all()
            open_buys = (await s.execute(open_stmt)).scalars().all()

        state = LedgerState(pipeline_name=pipeline_name, max_capital=max_capital, cash=max_capital)
        for f in fills:
            pos = state.positions.setdefault(f.symbol, LedgerPosition(symbol=f.symbol))
            state.commissions += f.commission
            if f.side == OrderSide.BUY.value:
                state.cash -= f.qty * f.price + f.commission
                pos.qty += f.qty
                pos.cost_basis += f.qty * f.price + f.commission
            else:
                sold = min(f.qty, pos.qty)  # the ledger never goes short
                cost_released = pos.avg_cost * sold
                proceeds = f.qty * f.price - f.commission
                state.cash += proceeds
                state.realized_pnl += proceeds - cost_released
                pos.cost_basis -= cost_released
                pos.qty -= sold
            if pos.qty == 0:
                pos.cost_basis = Decimal(0)
        state.positions = {k: v for k, v in state.positions.items() if v.qty != 0}

        for order in open_buys:
            remaining = max(Decimal(0), order.quantity - order.filled_qty)
            unit = order.limit_price or order.estimated_notional / order.quantity
            state.reserved_cash += remaining * unit
        return state
