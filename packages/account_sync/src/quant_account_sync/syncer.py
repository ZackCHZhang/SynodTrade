"""Synchronise one IBKR account with the database.

1. Open orders (pending, submitted, partially filled) of every pipeline on the account get
   the broker's status, filled quantity and fills. An order the broker no longer knows (not
   open, not completed, no executions) is closed as cancelled once it has not changed for
   `gone_after_minutes`; one with executions but no longer open is closed with what filled.
2. Orders closed in the last `recheck_days` are checked again for fills reported late.
3. The account summary and positions are saved as a snapshot, and the held symbols'
   market prices as quotes (so valuations follow the market between pipeline runs).
4. Differences are reported: broker positions vs the sum of the pipelines' ledgers, and
   open broker orders the database does not know (placed by hand, or by another database).

Orders of runs still in progress are left alone: their trading stage is tracking them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from quant_account_sync.config import AccountSyncConfig
from quant_account_sync.snapshot import BrokerReader, BrokerSnapshot
from quant_core.config import AccountConfig, PipelineConfig
from quant_core.logging import get_logger
from quant_core.models import OrderResult, OrderStatus, Quote
from quant_core.timeutil import utcnow
from quant_database import AccountSync, OrderRecord, Repositories, SyncStatus

log = get_logger(__name__)

# A run older than this that never finished is crashed, not running (as the runner sees it).
MAX_RUN_MINUTES = 180


@dataclass(frozen=True, slots=True)
class SyncTarget:
    """One broker account and every pipeline trading on it (possibly through several
    account configs, e.g. separate client ids for the same IBKR account)."""

    account_id: str
    account: AccountConfig  # connection settings used for the synchronisation
    account_names: tuple[str, ...]
    pipelines: tuple[PipelineConfig, ...]

    @property
    def pipeline_names(self) -> list[str]:
        return [p.name for p in self.pipelines]


def _num(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


@dataclass(slots=True)
class _Report:
    orders: list[dict[str, Any]] = field(default_factory=list)
    waiting: list[dict[str, Any]] = field(default_factory=list)
    late_fills: list[dict[str, Any]] = field(default_factory=list)
    skipped_running: list[str] = field(default_factory=list)
    untracked_open_orders: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    account: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    checked: int = 0
    updated: int = 0
    fills_added: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "orders": self.orders,
            "waiting": self.waiting,
            "late_fills": self.late_fills,
            "skipped_running": self.skipped_running,
            "untracked_open_orders": self.untracked_open_orders,
            "positions": self.positions,
            "account": self.account,
            "warnings": self.warnings,
            "errors": self.errors,
        }


def _change(record: OrderRecord, result: OrderResult, new_fills: int) -> dict[str, Any]:
    intent = record.intent
    return {
        "client_order_id": record.client_order_id,
        "pipeline": intent.pipeline_name,
        "run_id": str(intent.run_id),
        "symbol": intent.symbol,
        "side": intent.side.value,
        "quantity": float(intent.quantity),
        "from_status": record.status.value,
        "to_status": result.status.value,
        "filled_qty": float(result.filled_qty),
        "avg_fill_price": _num(result.avg_fill_price),
        "new_fills": new_fills,
        "message": result.message,
    }


class AccountSyncer:
    def __init__(
        self,
        repos: Repositories,
        config: AccountSyncConfig,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._repos = repos
        self.config = config
        self._clock = clock

    async def sync(
        self,
        target: SyncTarget,
        reader: BrokerReader,
        *,
        trigger: str,
        pipeline_name: str | None = None,
        run_id: UUID | None = None,
    ) -> AccountSync:
        started = self._clock()
        report = _Report()
        error: str | None = None
        snap: BrokerSnapshot | None = None
        try:
            await reader.connect()
            snap = await reader.snapshot(account=self.config.snapshot)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            log.warning("account_sync.failed", account=target.account_id, error=error)
        finally:
            try:
                await reader.disconnect()  # everything needed is read: release the gateway
            except Exception as exc:  # never hide the outcome behind a disconnect problem
                log.warning("account_sync.disconnect_failed", error=str(exc))
        if snap is not None:
            await self._apply(target, snap, report)

        if snap is None:
            status = SyncStatus.FAILED
        elif report.errors:
            status = SyncStatus.PARTIAL
            error = "; ".join(report.errors)[:2000]
        else:
            status = SyncStatus.OK
        record = await self._repos.account_syncs.add(
            AccountSync(
                account_id=target.account_id,
                trigger=trigger,
                pipeline_name=pipeline_name,
                run_id=run_id,
                started_at=started,
                finished_at=self._clock(),
                status=status,
                orders_checked=report.checked,
                orders_updated=report.updated,
                fills_added=report.fills_added,
                error=error,
                report={
                    "account_names": list(target.account_names),
                    "pipelines": target.pipeline_names,
                    **report.as_dict(),
                },
            )
        )
        log.info(
            "account_sync.done",
            account=target.account_id,
            trigger=trigger,
            status=status.value,
            checked=report.checked,
            updated=report.updated,
            fills_added=report.fills_added,
            warnings=len(report.warnings),
        )
        return record

    # ------------------------------------------------------------ steps

    async def _apply(self, target: SyncTarget, snap: BrokerSnapshot, report: _Report) -> None:
        running = await self._running_runs()
        await self._open_orders(target, snap, report, running)
        await self._late_fills(target, snap, report, running)
        await self._snapshot(snap, report)
        await self._untracked(snap, report)
        await self._positions(target, snap, report)

    async def _running_runs(self) -> set[UUID]:
        cutoff = self._clock() - timedelta(minutes=MAX_RUN_MINUTES)
        return {r.run_id for r in await self._repos.runs.running_runs() if r.started_at > cutoff}

    async def _new_fills(self, record: OrderRecord, result: OrderResult) -> int:
        if not result.fills:
            return 0
        stored = {f.exec_id for f in await self._repos.orders.get_fills(record.client_order_id)}
        return sum(1 for f in result.fills if f.exec_id not in stored)

    async def _open_orders(
        self, target: SyncTarget, snap: BrokerSnapshot, report: _Report, running: set[UUID]
    ) -> None:
        now = self._clock()
        gone_after = timedelta(minutes=self.config.gone_after_minutes)
        for name in target.pipeline_names:
            for record in await self._repos.orders.list_open(name):
                if record.intent.run_id in running:
                    report.skipped_running.append(record.client_order_id)
                    continue
                report.checked += 1
                try:
                    result = snap.result_for(record.intent)
                    # neither open nor completed at the broker: done, with or without fills
                    if result is None or (
                        not result.status.is_terminal and not snap.lists(record.client_order_id)
                    ):
                        if now - record.updated_at < gone_after:
                            report.waiting.append(
                                {
                                    "client_order_id": record.client_order_id,
                                    "pipeline": name,
                                    "symbol": record.intent.symbol,
                                    "status": record.status.value,
                                    "since": record.updated_at.isoformat(),
                                }
                            )
                            continue
                        result = self._gone(record, snap)
                        log.warning(
                            "account_sync.order_gone", client_order_id=record.client_order_id
                        )
                    new_fills = await self._new_fills(record, result)
                    if (
                        result.status is record.status
                        and result.filled_qty == record.filled_qty
                        and not new_fills
                    ):
                        continue
                    await self._repos.orders.apply_result(result)
                    report.updated += 1
                    report.fills_added += new_fills
                    report.orders.append(_change(record, result, new_fills))
                except Exception as exc:  # e.g. the trading stage closed it meanwhile
                    report.errors.append(f"{record.client_order_id}: {type(exc).__name__}: {exc}")
                    log.warning(
                        "account_sync.order_failed",
                        client_order_id=record.client_order_id,
                        error=str(exc),
                    )

    @staticmethod
    def _gone(record: OrderRecord, snap: BrokerSnapshot) -> OrderResult:
        """Close an order the broker no longer lists, with whatever it executed."""
        seen = snap.result_for(record.intent, all_fills=True)
        if seen is None:
            return OrderResult(
                client_order_id=record.client_order_id,
                status=OrderStatus.CANCELLED,
                filled_qty=record.filled_qty,
                avg_fill_price=record.avg_fill_price,
                message="not found at the broker (no open order, no execution): "
                "cancelled, expired or never transmitted",
            )
        filled = max(seen.filled_qty, record.filled_qty)
        return seen.model_copy(
            update={
                "status": OrderStatus.FILLED
                if filled >= record.intent.quantity
                else OrderStatus.CANCELLED,
                "filled_qty": filled,
                "message": "no longer open at the broker; closed with the executed quantity",
            }
        )

    async def _late_fills(
        self, target: SyncTarget, snap: BrokerSnapshot, report: _Report, running: set[UUID]
    ) -> None:
        if self.config.recheck_days <= 0 or not snap.executions:
            return
        since = self._clock() - timedelta(days=self.config.recheck_days)
        for record in await self._repos.orders.list_closed_since(since, target.pipeline_names):
            if record.intent.run_id in running or record.client_order_id not in snap.executions:
                continue
            try:
                await self._correct(record, snap, report)
            except Exception as exc:
                report.errors.append(f"{record.client_order_id}: {type(exc).__name__}: {exc}")

    async def _correct(self, record: OrderRecord, snap: BrokerSnapshot, report: _Report) -> None:
        # the order is closed, so every execution counts (commission report or not)
        seen = snap.result_for(record.intent, all_fills=True)
        if seen is None:
            return
        new_fills = await self._new_fills(record, seen)
        if not new_fills and seen.filled_qty <= record.filled_qty:
            return
        if seen.filled_qty < record.filled_qty:
            report.warnings.append(
                f"{record.client_order_id}: IBKR reports {seen.filled_qty} filled, the "
                f"database {record.filled_qty}; left unchanged"
            )
            return
        if seen.filled_qty >= record.intent.quantity:
            status = OrderStatus.FILLED
        elif seen.status in (OrderStatus.CANCELLED, OrderStatus.FILLED):
            status = seen.status
        else:  # rejected but partly executed, or (still) open at the broker
            status = OrderStatus.CANCELLED
        if not seen.status.is_terminal:
            report.warnings.append(
                f"{record.intent.symbol} {record.client_order_id}: open at IBKR "
                f"({seen.status.value}) but closed as {record.status.value} in the database; "
                "its fills are recorded, later fills only by the next synchronisation"
            )
        result = seen.model_copy(
            update={
                "status": status,
                "message": "corrected by account sync: fills reported after the order was "
                f"closed as {record.status.value}",
            }
        )
        await self._repos.orders.correct_closed(result)
        report.updated += 1
        report.fills_added += new_fills
        change = _change(record, result, new_fills)
        report.late_fills.append(change)
        report.warnings.append(
            f"{record.intent.symbol} {record.client_order_id}: {new_fills} fill(s) recorded "
            f"after the order was closed as {record.status.value}"
        )
        log.warning("account_sync.late_fills", **change)

    async def _snapshot(self, snap: BrokerSnapshot, report: _Report) -> None:
        if snap.account_error:
            report.errors.append(f"account summary: {snap.account_error}")
        if snap.account is None:
            return
        account = snap.account
        report.account = {
            "ts": account.ts.isoformat(),
            "currency": account.currency,
            "nav": float(account.nav),
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "available_funds": _num(account.available_funds),
            "positions": [
                {
                    "symbol": p.symbol,
                    "qty": float(p.qty),
                    "avg_cost": float(p.avg_cost),
                    "market_price": _num(p.market_price),
                }
                for p in snap.positions
            ],
        }
        # the held symbols' current prices, so valuations (the ledgers' NAV and market
        # values) follow the market between pipeline runs
        quotes = [
            Quote(symbol=p.symbol, ts=account.ts, last=p.market_price)
            for p in snap.positions
            if p.market_price is not None
        ]
        try:
            await self._repos.quotes.add(quotes)
        except Exception as exc:
            report.errors.append(f"prices: {type(exc).__name__}: {exc}")
        if not self.config.snapshot:
            return
        try:
            await self._repos.accounts.add_snapshot(account, snap.positions)
        except Exception as exc:
            report.errors.append(f"account snapshot: {type(exc).__name__}: {exc}")

    async def _untracked(self, snap: BrokerSnapshot, report: _Report) -> None:
        for order in snap.open_orders:
            known = bool(order.ref) and await self._repos.orders.get(order.ref) is not None
            if known:
                continue
            report.untracked_open_orders.append(
                {
                    "ref": order.ref or None,
                    "symbol": order.symbol,
                    "side": order.side,
                    "quantity": float(order.quantity),
                    "filled": float(order.filled),
                    "limit_price": _num(order.limit_price),
                    "status": order.broker_status,
                    "perm_id": order.perm_id or None,
                }
            )
        if report.untracked_open_orders:
            report.warnings.append(
                f"{len(report.untracked_open_orders)} open order(s) at IBKR not placed by "
                "this database (by hand, or by another database)"
            )

    async def _positions(self, target: SyncTarget, snap: BrokerSnapshot, report: _Report) -> None:
        if snap.account is None:
            return
        broker = {p.symbol: p.qty for p in snap.positions}
        ledgers: dict[str, dict[str, Decimal]] = {}
        for pipeline in target.pipelines:
            state = await self._repos.ledger.get_state(
                pipeline.name, pipeline.budget.max_capital, as_of=self._clock()
            )
            for symbol, pos in state.positions.items():
                ledgers.setdefault(symbol, {})[pipeline.name] = pos.qty
        for symbol in sorted(set(broker) | set(ledgers)):
            held = broker.get(symbol, Decimal(0))
            by_pipeline = ledgers.get(symbol, {})
            booked = sum(by_pipeline.values(), Decimal(0))
            verdict = "ok" if held == booked else "broker_more" if held > booked else "broker_less"
            report.positions.append(
                {
                    "symbol": symbol,
                    "broker_qty": float(held),
                    "ledger_qty": float(booked),
                    "pipelines": {k: float(v) for k, v in by_pipeline.items()},
                    "state": verdict,
                }
            )
            if verdict == "broker_less":
                report.warnings.append(
                    f"{symbol}: IBKR holds {held}, the pipelines' ledgers {booked} "
                    "(sells of it are blocked until this is resolved)"
                )


def group_targets(
    pipelines: Sequence[tuple[PipelineConfig, str, AccountConfig]],
) -> list[SyncTarget]:
    """(pipeline, account config name, account config) -> one target per broker account."""
    grouped: dict[str, list[tuple[PipelineConfig, str, AccountConfig]]] = {}
    for item in pipelines:
        grouped.setdefault(item[2].account_id, []).append(item)
    return [
        SyncTarget(
            account_id=account_id,
            account=items[0][2],
            account_names=tuple(dict.fromkeys(name for _, name, _ in items)),
            pipelines=tuple(p for p, _, _ in items),
        )
        for account_id, items in sorted(grouped.items())
    ]
