"""`trading` pipeline stage: plan -> record (idempotent) -> submit -> track -> cancel on timeout."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable, Mapping

from quant_core.config import AccountConfig, PipelineConfig, StageConfig
from quant_core.logging import get_logger
from quant_core.models import OrderResult, OrderStatus, PipelineContext, RunMode
from quant_core.safety import ensure_mode_allowed
from quant_core.services import Services
from quant_database import OrderRecord, Repositories
from quant_trading.broker import Broker, BrokerError, DryRunBroker
from quant_trading.ibkr import IBKRBroker
from quant_trading.planner import OrderPlanner, PlannedOrder, TradingOptions

log = get_logger(__name__)


class TradingError(RuntimeError):
    pass


def create_broker(
    mode: RunMode, account: AccountConfig | None, env: Mapping[str, str] | None = None
) -> Broker:
    """The broker a run mode calls for: dry_run -> DryRunBroker, paper/live -> IBKRBroker."""
    if mode is RunMode.DRY_RUN:
        return DryRunBroker()
    if account is None:
        raise TradingError(f"mode {mode.value} needs an IBKR account config")
    return IBKRBroker.from_account(account, mode, env=dict(os.environ if env is None else env))


class TradingStage:
    name = "trading"

    def __init__(
        self,
        options: TradingOptions,
        planner: OrderPlanner,
        broker: Broker,
        repos: Repositories,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.options = options
        self.planner = planner
        self.broker = broker
        self._repos = repos
        self._sleep = sleep
        self._monotonic = monotonic

    async def _apply(self, result: OrderResult) -> OrderRecord:
        return await self._repos.orders.apply_result(result)

    async def reconcile(self, pipeline_name: str) -> int:
        """Bring orders left open by earlier runs up to date with the broker."""
        updated = 0
        for record in await self._repos.orders.list_open(pipeline_name):
            result = await self.broker.lookup(record.intent)
            if (result is not None and result.status is not record.status) or (
                result is not None and result.filled_qty != record.filled_qty
            ):
                await self._apply(result)
                updated += 1
        return updated

    async def _submit(self, planned: PlannedOrder, ctx: PipelineContext) -> OrderRecord | None:
        record, created = await self._repos.orders.create(planned.intent, created_at=ctx.as_of)
        if not created and record.status is not OrderStatus.PENDING_SUBMIT:
            log.info(
                "trading.already_sent",
                client_order_id=record.client_order_id,
                status=record.status.value,
            )
            return record
        if not created:
            # Recorded but maybe never sent (e.g. a crash): only send if the broker lacks it.
            existing = await self.broker.lookup(planned.intent)
            if existing is not None:
                return await self._apply(existing)
        try:
            result = await self.broker.submit(planned.intent, planned.instrument)
        except Exception as exc:  # keep it pending: the next run looks it up before resending
            log.error(
                "trading.submit_failed",
                client_order_id=planned.intent.client_order_id,
                error=str(exc),
            )
            await self._apply(
                OrderResult(
                    client_order_id=planned.intent.client_order_id,
                    status=OrderStatus.PENDING_SUBMIT,
                    message=f"submit failed: {type(exc).__name__}: {exc}",
                )
            )
            return None
        return await self._apply(result)

    async def _track(self, records: list[OrderRecord]) -> list[OrderRecord]:
        """Poll until every order is done; cancel whatever is still open at the deadline."""
        latest = {r.client_order_id: r for r in records}
        deadline = self._monotonic() + self.options.cancel_after_minutes * 60

        def still_open() -> list[OrderRecord]:
            return [r for r in latest.values() if not r.status.is_terminal]

        while still_open() and self._monotonic() < deadline:
            await self._sleep(self.options.poll_interval_seconds)
            for record in still_open():
                result = await self.broker.lookup(record.intent)
                if result is not None:
                    latest[record.client_order_id] = await self._apply(result)
        for record in still_open():
            log.info("trading.cancel_on_timeout", client_order_id=record.client_order_id)
            try:
                result = await self.broker.cancel(record.intent)
            except BrokerError as exc:
                log.error(
                    "trading.cancel_failed", client_order_id=record.client_order_id, error=str(exc)
                )
                continue
            latest[record.client_order_id] = await self._apply(result)
        return list(latest.values())

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        ensure_mode_allowed(ctx.mode)
        if self.broker.mode is not ctx.mode:
            raise TradingError(
                f"broker {self.broker.name} is for mode {self.broker.mode.value}, "
                f"but the run is {ctx.mode.value}"
            )
        await self.broker.connect()
        reconciled = await self.reconcile(ctx.pipeline_name)
        if await self._repos.flags.kill_switch_active():
            log.warning("trading.kill_switch_active: no orders sent")
            return ctx

        planned, skipped = await self.planner.plan(ctx)
        records: list[OrderRecord] = []
        failed: list[str] = []
        for order in planned:
            ctx.order_intents.append(order.intent)
            record = await self._submit(order, ctx)
            if record is None:
                failed.append(order.intent.symbol)
            else:
                records.append(record)
        if self.options.wait_for_fills:
            records = await self._track(records)
        for record in records:
            ctx.order_results.append(
                OrderResult(
                    client_order_id=record.client_order_id,
                    status=record.status,
                    broker_order_id=record.broker_order_id,
                    filled_qty=record.filled_qty,
                    avg_fill_price=record.avg_fill_price,
                    message=record.message,
                )
            )
        log.info(
            "trading.done",
            orders={r.intent.symbol: r.status.value for r in records},
            skipped={s.symbol: s.reason for s in skipped},
            reconciled=reconciled,
        )
        if failed:
            raise TradingError(f"order submission failed for {failed} (left pending)")
        return ctx


def build_trading_stage(config: StageConfig, services: Services) -> TradingStage:
    """Stage factory (entry point `quant.stages: trading`).

    Services: `repos`, `broker` (Broker; see `create_broker`), `pipeline` (PipelineConfig:
    budget and sizing); optional `account` (AccountConfig: caps cash by the real account).
    """
    options = config.options(TradingOptions)
    repos = services.get("repos", Repositories)
    pipeline = services.get("pipeline", PipelineConfig)
    account = services.optional("account", AccountConfig)
    planner = OrderPlanner(
        repos,
        options,
        pipeline.sizing,
        max_capital=pipeline.budget.max_capital,
        account_id=account.account_id if account else None,
    )
    return TradingStage(options, planner, services.get("broker", Broker), repos)
