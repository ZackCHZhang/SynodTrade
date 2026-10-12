"""Account synchronisation against a fake broker reader and a real (SQLite) database."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from quant_account_sync import (
    AccountSyncConfig,
    AccountSyncService,
    BrokerExecution,
    BrokerOrder,
    BrokerSnapshot,
    PeriodicSync,
    load_sync_config,
)
from quant_core.config import ConfigStore
from quant_core.models import (
    AccountSnapshot,
    Action,
    OrderIntent,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    RunMode,
)
from quant_database import (
    AccountSync,
    OrderRecord,
    PipelineRun,
    Repositories,
    RunStatus,
    SyncStatus,
)

D = Decimal
NOW = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)
ACCOUNT = "DU1234567"
PIPELINE = "long_term_stocks"


# ------------------------------------------------------------------ helpers


def broker_order(
    record: OrderRecord, status: OrderStatus, *, filled: str = "0", ref: str | None = None
) -> BrokerOrder:
    return BrokerOrder(
        ref=record.client_order_id if ref is None else ref,
        symbol=record.intent.symbol,
        side=record.intent.side.value,
        quantity=record.intent.quantity,
        status=status,
        broker_status=status.value,
        filled=D(filled),
        avg_fill_price=D("99.5") if D(filled) > 0 else None,
        perm_id=777,
        open=not status.is_terminal,
    )


def execution(
    record: OrderRecord, exec_id: str, shares: str, *, commission: str | None = "1"
) -> BrokerExecution:
    return BrokerExecution(
        exec_id=exec_id,
        ref=record.client_order_id,
        symbol=record.intent.symbol,
        side=record.intent.side.value,
        shares=D(shares),
        price=D("99.5"),
        ts=NOW - timedelta(minutes=30),
        commission=D(commission) if commission is not None else None,
    )


def snapshot(
    orders: Sequence[BrokerOrder] = (),
    executions: Sequence[BrokerExecution] = (),
    *,
    positions: dict[str, str] | None = None,
    foreign: Sequence[BrokerOrder] = (),
) -> BrokerSnapshot:
    snap = BrokerSnapshot(account_id=ACCOUNT, fetched_at=NOW)
    for o in orders:
        snap.orders[o.ref] = o
    snap.open_orders = [o for o in [*orders, *foreign] if o.open]
    for e in executions:
        snap.executions.setdefault(e.ref, []).append(e)
    if positions is not None:
        snap.account = AccountSnapshot(
            account_id=ACCOUNT, ts=NOW, nav=D(100000), cash=D(50000), buying_power=D(200000)
        )
        snap.positions = [
            Position(account_id=ACCOUNT, symbol=s, qty=D(q), avg_cost=D(100), ts=NOW)
            for s, q in positions.items()
        ]
    return snap


@dataclass
class FakeReader:
    snap: BrokerSnapshot | None = None
    fail: Exception | None = None
    account_id: str = ACCOUNT
    calls: list[str] = field(default_factory=list)

    async def connect(self) -> None:
        self.calls.append("connect")
        if self.fail is not None:
            raise self.fail

    async def disconnect(self) -> None:
        self.calls.append("disconnect")

    async def snapshot(self, *, account: bool = True) -> BrokerSnapshot:
        self.calls.append("snapshot")
        return self.snap or BrokerSnapshot(account_id=self.account_id, fetched_at=NOW)


NewOrder = Callable[..., Awaitable[OrderRecord]]


@pytest.fixture
def new_order(repos: Repositories) -> NewOrder:
    """Record an order of a finished run, created (and last updated) `age` before NOW."""

    async def create(
        symbol: str = "AAPL",
        qty: str = "10",
        *,
        status: OrderStatus = OrderStatus.SUBMITTED,
        age: timedelta = timedelta(hours=2),
        pipeline: str = PIPELINE,
        run_status: RunStatus = RunStatus.SUCCEEDED,
    ) -> OrderRecord:
        created = NOW - age
        run_id = uuid4()
        await repos.runs.start_run(
            PipelineRun(
                run_id=run_id,
                pipeline_name=pipeline,
                mode=RunMode.PAPER,
                config_hash="0" * 64,
                config={},
                as_of=created,
                started_at=created,
            )
        )
        if run_status is not RunStatus.RUNNING:
            await repos.runs.finish_run(run_id, run_status)
        intent = OrderIntent(
            client_order_id=f"q-{uuid4().hex[:12]}",
            run_id=run_id,
            pipeline_name=pipeline,
            symbol=symbol,
            action=Action.BUY,
            side=OrderSide.BUY,
            quantity=D(qty),
            order_type=OrderType.LIMIT,
            limit_price=D(100),
            estimated_notional=D(qty) * 100,
        )
        record, _ = await repos.orders.create(intent, status, created_at=created)
        return record

    return create


Sync = Callable[..., Awaitable[AccountSync]]


@pytest.fixture
def sync(store: ConfigStore, repos: Repositories) -> Sync:
    """Synchronise the (single) test account once against `snap`."""

    async def run(snap: BrokerSnapshot | None = None, **config: object) -> AccountSync:
        service = AccountSyncService(
            store,
            repos,
            reader_factory=lambda _: FakeReader(snap),
            config=AccountSyncConfig.model_validate(config),
            clock=lambda: NOW,
        )
        [result] = await service.sync_all(trigger="manual")
        return result

    return run


async def order(repos: Repositories, record: OrderRecord) -> OrderRecord:
    found = await repos.orders.get(record.client_order_id)
    assert found is not None
    return found


# ------------------------------------------------------------------ the broker's view


def test_result_for_waits_for_commissions_until_the_order_is_final() -> None:
    intent = OrderIntent(
        client_order_id="q-1",
        run_id=uuid4(),
        pipeline_name="p",
        symbol="AAPL",
        action=Action.BUY,
        side=OrderSide.BUY,
        quantity=D(10),
        order_type=OrderType.LIMIT,
        limit_price=D(100),
        estimated_notional=D(1000),
    )
    rec = OrderRecord(
        id=1, intent=intent, status=OrderStatus.SUBMITTED, created_at=NOW, updated_at=NOW
    )
    assert snapshot().result_for(intent) is None

    partial = snapshot(
        [broker_order(rec, OrderStatus.SUBMITTED, filled="6")],
        [execution(rec, "e1", "4"), execution(rec, "e2", "2", commission=None)],
    )
    result = partial.result_for(intent)
    assert result is not None
    assert result.status is OrderStatus.PARTIALLY_FILLED
    assert result.filled_qty == 6
    assert [f.exec_id for f in result.fills] == ["e1"]  # e2's commission is still on its way
    everything = partial.result_for(intent, all_fills=True)
    assert everything is not None
    assert len(everything.fills) == 2
    assert everything.fills[1].commission == 0

    executions_only = snapshot([], [execution(rec, "e1", "6"), execution(rec, "e2", "4")])
    result = executions_only.result_for(intent)
    assert result is not None
    assert result.status is OrderStatus.FILLED
    assert result.avg_fill_price == D("99.5")
    assert result.message == "recovered from executions"


# ------------------------------------------------------------------ open orders


async def test_filled_order_gets_status_and_fills(
    sync: Sync, repos: Repositories, new_order: NewOrder
) -> None:
    rec = await new_order()
    snap = snapshot(
        [broker_order(rec, OrderStatus.FILLED, filled="10")],
        [execution(rec, "e1", "6"), execution(rec, "e2", "4")],
    )
    result = await sync(snap)
    assert result.status is SyncStatus.OK
    assert (result.orders_checked, result.orders_updated, result.fills_added) == (1, 1, 2)
    [change] = result.report["orders"]
    assert change["from_status"] == "submitted"
    assert change["to_status"] == "filled"

    updated = await order(repos, rec)
    assert updated.status is OrderStatus.FILLED
    assert updated.filled_qty == 10
    assert len(await repos.orders.get_fills(rec.client_order_id)) == 2
    ledger = await repos.ledger.get_state(PIPELINE, D(100000))
    assert ledger.position_qty("AAPL") == 10

    again = await sync(snap)  # nothing new: nothing written
    assert again.orders_checked == 0
    assert again.orders_updated == 0


async def test_partial_fill_stays_open_and_fills_follow_their_commission(
    sync: Sync, repos: Repositories, new_order: NewOrder
) -> None:
    rec = await new_order()
    working = broker_order(rec, OrderStatus.SUBMITTED, filled="6")
    first = await sync(snapshot([working], [execution(rec, "e1", "6", commission=None)]))
    assert first.orders_updated == 1
    assert first.fills_added == 0
    updated = await order(repos, rec)
    assert updated.status is OrderStatus.PARTIALLY_FILLED
    assert updated.filled_qty == 6
    assert await repos.orders.get_fills(rec.client_order_id) == []

    second = await sync(snapshot([working], [execution(rec, "e1", "6")]))
    assert second.orders_updated == 1
    assert second.fills_added == 1
    [fill] = await repos.orders.get_fills(rec.client_order_id)
    assert fill.commission == 1


async def test_order_unknown_to_the_broker_waits_then_is_cancelled(
    sync: Sync, repos: Repositories, new_order: NewOrder
) -> None:
    young = await new_order("MSFT", age=timedelta(minutes=10))
    old = await new_order("NVDA", age=timedelta(hours=2))
    result = await sync(snapshot(), gone_after_minutes=30)
    assert [w["symbol"] for w in result.report["waiting"]] == ["MSFT"]
    assert (await order(repos, young)).status is OrderStatus.SUBMITTED
    closed = await order(repos, old)
    assert closed.status is OrderStatus.CANCELLED
    assert closed.message is not None
    assert "not found at the broker" in closed.message
    ledger = await repos.ledger.get_state(PIPELINE, D(100000))
    assert ledger.reserved_cash == D(1000)  # only MSFT's cash is still reserved


async def test_executions_without_an_open_order_close_with_what_filled(
    sync: Sync, repos: Repositories, new_order: NewOrder
) -> None:
    rec = await new_order()
    result = await sync(snapshot([], [execution(rec, "e1", "4", commission=None)]))
    assert result.fills_added == 1
    closed = await order(repos, rec)
    assert closed.status is OrderStatus.CANCELLED
    assert closed.filled_qty == 4
    [fill] = await repos.orders.get_fills(rec.client_order_id)
    assert fill.qty == 4


async def test_orders_of_running_runs_are_left_to_their_trading_stage(
    sync: Sync, repos: Repositories, new_order: NewOrder
) -> None:
    rec = await new_order(age=timedelta(minutes=40), run_status=RunStatus.RUNNING)
    result = await sync(snapshot())
    assert result.report["skipped_running"] == [rec.client_order_id]
    assert result.orders_checked == 0
    assert (await order(repos, rec)).status is OrderStatus.SUBMITTED


# ------------------------------------------------------------------ late fills


async def test_late_fills_correct_an_order_closed_as_cancelled(
    sync: Sync, repos: Repositories, new_order: NewOrder
) -> None:
    rec = await new_order(status=OrderStatus.CANCELLED, age=timedelta(hours=5))
    stale = await new_order("MSFT", status=OrderStatus.CANCELLED, age=timedelta(days=5))
    snap = snapshot(
        [],
        [
            execution(rec, "e1", "10", commission=None),
            execution(stale, "e9", "10"),
        ],
    )
    result = await sync(snap, recheck_days=3)
    assert result.status is SyncStatus.OK
    [late] = result.report["late_fills"]
    assert late["client_order_id"] == rec.client_order_id
    assert (late["from_status"], late["to_status"]) == ("cancelled", "filled")
    assert any("recorded after the order was closed" in w for w in result.report["warnings"])
    corrected = await order(repos, rec)
    assert corrected.status is OrderStatus.FILLED
    assert corrected.filled_qty == 10
    assert len(await repos.orders.get_fills(rec.client_order_id)) == 1
    assert (await order(repos, stale)).status is OrderStatus.CANCELLED  # beyond recheck_days

    again = await sync(snap, recheck_days=3)
    assert again.report["late_fills"] == []


async def test_correct_closed_guards(repos: Repositories, new_order: NewOrder) -> None:
    rec = await new_order(status=OrderStatus.FILLED)
    await repos.orders.apply_result(
        OrderResult(
            client_order_id=rec.client_order_id, status=OrderStatus.FILLED, filled_qty=D(10)
        )
    )
    with pytest.raises(ValueError, match="lower the filled quantity"):
        await repos.orders.correct_closed(
            OrderResult(
                client_order_id=rec.client_order_id,
                status=OrderStatus.CANCELLED,
                filled_qty=D(4),
            )
        )
    with pytest.raises(ValueError, match="final broker status"):
        await repos.orders.correct_closed(
            OrderResult(client_order_id=rec.client_order_id, status=OrderStatus.SUBMITTED)
        )
    open_order = await new_order("MSFT")
    with pytest.raises(ValueError, match="not correctable"):
        await repos.orders.correct_closed(
            OrderResult(client_order_id=open_order.client_order_id, status=OrderStatus.FILLED)
        )


# ------------------------------------------------------------------ account and checks


async def test_snapshot_positions_and_untracked_orders(
    sync: Sync, repos: Repositories, new_order: NewOrder
) -> None:
    rec = await new_order()
    manual = BrokerOrder(
        ref="",
        symbol="TSLA",
        side="sell",
        quantity=D(3),
        status=OrderStatus.SUBMITTED,
        broker_status="Submitted",
        perm_id=4242,
        open=True,
    )
    snap = snapshot(
        [broker_order(rec, OrderStatus.FILLED, filled="10")],
        [execution(rec, "e1", "10")],
        positions={"AAPL": "8", "MSFT": "5"},
        foreign=[manual],
    )
    result = await sync(snap)
    positions = {p["symbol"]: p for p in result.report["positions"]}
    assert positions["AAPL"]["state"] == "broker_less"
    assert positions["AAPL"]["pipelines"] == {PIPELINE: 10.0}
    assert positions["MSFT"]["state"] == "broker_more"
    assert any("AAPL: IBKR holds 8" in w for w in result.report["warnings"])
    [untracked] = result.report["untracked_open_orders"]
    assert untracked["symbol"] == "TSLA"
    assert untracked["perm_id"] == 4242
    assert result.report["account"]["nav"] == 100000

    saved = await repos.accounts.get_latest_positions(ACCOUNT)
    assert saved is not None
    assert {p.symbol: p.qty for p in saved} == {"AAPL": 8, "MSFT": 5}

    no_snapshot = await sync(snap, snapshot=False)  # reported, not stored
    assert no_snapshot.report["account"] is not None


async def test_unreachable_gateway_is_recorded_as_failed(
    store: ConfigStore, repos: Repositories
) -> None:
    reader = FakeReader(fail=ConnectionRefusedError("connection refused"))
    service = AccountSyncService(store, repos, reader_factory=lambda _: reader, clock=lambda: NOW)
    [result] = await service.sync_all(trigger="auto")
    assert result.status is SyncStatus.FAILED
    assert result.error is not None
    assert "ConnectionRefusedError" in result.error
    assert reader.calls == ["connect", "disconnect"]
    [stored] = await repos.account_syncs.recent()
    assert stored.id is not None
    assert stored.status is SyncStatus.FAILED
    [latest] = await repos.account_syncs.latest()
    assert latest.id == stored.id


# ------------------------------------------------------------------ service


def test_pipelines_are_grouped_by_broker_account(store: ConfigStore, repos: Repositories) -> None:
    service = AccountSyncService(store, repos)
    [target] = service.targets()
    assert target.account_id == ACCOUNT
    assert set(target.account_names) == {"ibkr_main", "ibkr_etf"}
    assert set(target.pipeline_names) == set(store.list("pipelines"))

    only_etf = service.targets(AccountSyncConfig(accounts=["ibkr_etf"]))
    assert [t.pipeline_names for t in only_etf] == [["etf_allocation"]]
    assert service.target_for(store.pipeline(PIPELINE)).pipeline_names == target.pipeline_names


async def test_sync_pipeline_records_its_run(store: ConfigStore, repos: Repositories) -> None:
    service = AccountSyncService(
        store, repos, reader_factory=lambda _: FakeReader(), clock=lambda: NOW
    )
    run_id: UUID = uuid4()
    result = await service.sync_pipeline(store.pipeline(PIPELINE), run_id=run_id)
    assert (result.trigger, result.pipeline_name, result.run_id) == ("pipeline", PIPELINE, run_id)
    assert result.status is SyncStatus.OK


def test_config_file_and_defaults(store: ConfigStore, configs: Path) -> None:
    config = load_sync_config(store)
    assert config.enabled
    assert config.interval_minutes == 20
    assert config.before_pipeline
    (configs / "account_sync.yaml").unlink()
    assert load_sync_config(store) == AccountSyncConfig()


async def test_periodic_sync_schedule(
    store: ConfigStore, repos: Repositories, configs: Path
) -> None:
    clock = [NOW]
    service = AccountSyncService(
        store, repos, reader_factory=lambda _: FakeReader(), clock=lambda: clock[0]
    )
    periodic = PeriodicSync(service, tick_seconds=0.01)
    assert periodic.next_due() == NOW  # never synchronised: due now
    periodic.start()
    for _ in range(200):
        if periodic.last_finished is not None:
            break
        await asyncio.sleep(0.01)
    await periodic.stop()
    assert not periodic.running
    assert periodic.next_due() == NOW + timedelta(minutes=20)
    assert len(await repos.account_syncs.recent()) == 1

    text = (configs / "account_sync.yaml").read_text(encoding="utf-8")
    (configs / "account_sync.yaml").write_text(
        text.replace("enabled: true", "enabled: false"), encoding="utf-8"
    )
    assert periodic.next_due() is None  # settings are re-read: disabled at once
    [manual] = await periodic.run_once(trigger="manual")
    assert manual.trigger == "manual"
