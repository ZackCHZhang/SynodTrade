"""IBKRAccountReader against a stub `IB` object — no gateway; nothing is ever sent."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from ib_async import (
    CommissionReport,
    Execution,
    ExecutionFilter,
    LimitOrder,
    Order,
    Stock,
    Trade,
    TradeLogEntry,
)
from ib_async import Fill as IBFill
from ib_async import OrderStatus as IBOrderStatus

from quant_account_sync import CLIENT_ID_OFFSET, AccountSyncError, IBKRAccountReader
from quant_account_sync.ibkr import order_from_trade
from quant_core.config import AccountConfig
from quant_core.models import OrderStatus

D = Decimal
T = datetime(2026, 10, 12, 14, 0, tzinfo=UTC)
ACCOUNT = "DU123"


def trade(
    ref: str, status: str, *, filled: float = 0, account: str = ACCOUNT, **order: Any
) -> Trade:
    o = LimitOrder("BUY", 10, 100.0, orderRef=ref, account=account, permId=555, orderId=7, **order)
    return Trade(
        contract=Stock("AAPL"),
        order=o,
        orderStatus=IBOrderStatus(status=status, filled=filled, avgFillPrice=99.5 if filled else 0),
        log=[TradeLogEntry(time=T, status=status, message="note")],
    )


def fill(
    exec_id: str, ref: str, shares: float, *, report: bool = True, account: str = ACCOUNT
) -> IBFill:
    return IBFill(
        contract=Stock("AAPL"),
        execution=Execution(
            execId=exec_id, orderRef=ref, shares=shares, price=99.5, side="BOT", acctNumber=account
        ),
        commissionReport=CommissionReport(execId=exec_id, commission=1.0)
        if report
        else CommissionReport(),
        time=T,
    )


class StubIB:
    def __init__(self) -> None:
        self.connected = False
        self.accounts = [ACCOUNT]
        self.open: list[Trade] = []
        self.completed: list[Trade] = []
        self.fills: list[IBFill] = []
        self.placed: list[Any] = []
        self.exec_filter: ExecutionFilter | None = None

    def isConnected(self) -> bool:  # noqa: N802 - mirrors ib_async
        return self.connected

    async def connectAsync(self, host: str, port: int, **kw: Any) -> None:  # noqa: N802
        self.connected = True
        self.connect_kw = kw

    def disconnect(self) -> None:
        self.connected = False

    def managedAccounts(self) -> list[str]:  # noqa: N802
        return self.accounts

    async def reqAllOpenOrdersAsync(self) -> list[Trade]:  # noqa: N802
        return self.open

    async def reqCompletedOrdersAsync(self, apiOnly: bool) -> list[Trade]:  # noqa: N802, N803
        assert apiOnly is False  # orders placed in TWS by hand count too
        return self.completed

    async def reqExecutionsAsync(self, execFilter: ExecutionFilter | None = None) -> list[IBFill]:  # noqa: N802, N803
        self.exec_filter = execFilter
        return self.fills

    def placeOrder(self, *args: Any) -> None:  # noqa: N802 - must never be called
        self.placed.append(args)


async def no_sleep(_: float) -> None:
    return None


def reader(ib: StubIB) -> IBKRAccountReader:
    return IBKRAccountReader(account_id=ACCOUNT, ib=ib, sleep=no_sleep, commission_wait_s=0.5)  # type: ignore[arg-type]


def test_from_account_uses_its_own_client_id() -> None:
    account = AccountConfig(name="a", account_id=ACCOUNT, client_id=17, port=7497)
    r = IBKRAccountReader.from_account(account)
    assert r.client_id == 17 + CLIENT_ID_OFFSET
    assert (r.port, r.account_id) == (7497, ACCOUNT)


async def test_connect_checks_the_account() -> None:
    ib = StubIB()
    ib.accounts = ["DU999"]
    with pytest.raises(AccountSyncError, match="not managed"):
        await reader(ib).connect()
    assert not ib.connected


async def test_snapshot_merges_open_completed_and_executions() -> None:
    ib = StubIB()
    ib.open = [
        trade("q-open", "Submitted", filled=4),
        trade("", "Submitted"),  # placed by hand in TWS
        trade("q-other-account", "Submitted", account="DU999"),
    ]
    ib.completed = [
        trade("q-done", "Filled", filledQuantity=10.0),
        trade("q-open", "Cancelled"),  # an older state of the same order: open wins
    ]
    ib.fills = [
        fill("e1", "q-open", 4),
        fill("e2", "q-done", 10, report=False),
        fill("e2", "q-done", 10, report=False),  # duplicates are dropped
        fill("e3", "q-x", 1, account="DU999"),
    ]
    r = reader(ib)
    await r.connect()
    snap = await r.snapshot(account=False)
    await r.disconnect()

    assert ib.connect_kw["clientId"] == 21
    assert not ib.placed
    assert ib.exec_filter is not None
    assert ib.exec_filter.acctCode == ACCOUNT
    assert set(snap.orders) == {"q-open", "q-done"}
    assert snap.orders["q-open"].status is OrderStatus.PARTIALLY_FILLED
    assert snap.orders["q-open"].open
    done = snap.orders["q-done"]
    assert done.status is OrderStatus.FILLED
    assert done.filled == 10
    assert done.broker_order_id == "555"
    assert [o.ref for o in snap.open_orders] == ["q-open", ""]
    assert [e.exec_id for e in snap.executions["q-done"]] == ["e2"]
    assert snap.executions["q-done"][0].commission is None  # no report (yet)
    assert snap.executions["q-open"][0].commission == 1
    assert "q-x" not in snap.executions
    assert snap.account is None
    assert snap.account_error is None


def test_unset_quantities_count_as_zero() -> None:
    t = trade("q-1", "Cancelled")
    assert t.order.filledQuantity > 1e300  # ib_async's "unset" marker
    order = order_from_trade(t, is_open=False)
    assert order.filled == 0
    assert order.status is OrderStatus.CANCELLED
    assert order.limit_price == D(100)
    assert (
        order_from_trade(
            Trade(contract=Stock("AAPL"), order=Order(orderRef="m")), is_open=False
        ).quantity
        == 0
    )


async def test_account_summary_failure_is_reported_not_raised() -> None:
    ib = StubIB()
    r = reader(ib)
    await r.connect()
    snap = await r.snapshot(account=True)  # the stub has no account summary
    assert snap.account is None
    assert snap.account_error is not None
