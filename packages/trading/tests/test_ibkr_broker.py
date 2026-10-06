"""IBKRBroker against a stub `IB` object — no gateway, no orders ever leave the process."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from ib_async import CommissionReport, Contract, Execution, Order, Stock, Trade, TradeLogEntry
from ib_async import Fill as IBFill
from ib_async import OrderStatus as IBOrderStatus
from structlog.testing import capture_logs

from quant_core.config import AccountConfig
from quant_core.models import (
    Action,
    Instrument,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    RunMode,
)
from quant_core.safety import LiveTradingNotAllowedError
from quant_trading import BrokerError, IBKRBroker, is_paper_account
from quant_trading.ibkr import convert_fills, result_from_trade, to_status

D = Decimal
T = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)
AAPL = Instrument(symbol="AAPL", con_id=265598)


def intent(qty: str = "10", order_type: OrderType = OrderType.LIMIT) -> OrderIntent:
    return OrderIntent(
        client_order_id="q-abc",
        run_id=uuid4(),
        pipeline_name="p",
        symbol="AAPL",
        action=Action.BUY,
        side=OrderSide.BUY,
        quantity=D(qty),
        order_type=order_type,
        limit_price=D("100.05") if order_type is OrderType.LIMIT else None,
        estimated_notional=D(1000),
    )


def ib_fill(
    exec_id: str,
    shares: float,
    price: float,
    *,
    commission: float | None = 1.0,
    order_ref: str = "q-abc",
) -> IBFill:
    report = (
        CommissionReport(execId=exec_id, commission=commission)
        if commission is not None
        else CommissionReport()
    )
    return IBFill(
        contract=Stock("AAPL"),
        execution=Execution(
            execId=exec_id, shares=shares, price=price, orderRef=order_ref, avgPrice=price
        ),
        commissionReport=report,
        time=T,
    )


def trade(
    status: str,
    filled: float = 0,
    fills: list[IBFill] | None = None,
    order_ref: str = "q-abc",
    perm_id: int = 555,
) -> Trade:
    order = Order(orderRef=order_ref, permId=perm_id, orderId=7, totalQuantity=10)
    return Trade(
        contract=Stock("AAPL"),
        order=order,
        orderStatus=IBOrderStatus(status=status, filled=filled, avgFillPrice=100.0),
        fills=fills or [],
        log=[TradeLogEntry(time=T, status=status, message="note")],
    )


class StubIB:
    def __init__(self, accounts: list[str] | None = None) -> None:
        self.connected = False
        self.accounts = accounts or ["DU123"]
        self.placed: list[tuple[Contract, Order]] = []
        self.cancelled: list[Order] = []
        self.session_trades: list[Trade] = []
        self.gateway_trades: list[Trade] = []  # only visible after reqAllOpenOrders
        self.executions: list[IBFill] = []
        self.time_fails = False

    def isConnected(self) -> bool:  # noqa: N802 - mirrors ib_async
        return self.connected

    async def connectAsync(self, host: str, port: int, **kw: Any) -> None:  # noqa: N802
        self.connected = True
        self.connect_kw = kw

    def disconnect(self) -> None:
        self.connected = False

    def managedAccounts(self) -> list[str]:  # noqa: N802
        return self.accounts

    async def reqCurrentTimeAsync(self) -> datetime:  # noqa: N802
        if self.time_fails:
            raise ConnectionError("gone")
        return T

    async def qualifyContractsAsync(self, contract: Stock) -> list[Any]:  # noqa: N802
        if contract.symbol == "NOPE":
            return [None]
        contract.conId = 4242
        return [contract]

    def placeOrder(self, contract: Contract, order: Order) -> Trade:  # noqa: N802
        self.placed.append((contract, order))
        t = Trade(contract=contract, order=order, orderStatus=IBOrderStatus(status="PendingSubmit"))
        self.session_trades.append(t)
        return t

    def cancelOrder(self, order: Order) -> None:  # noqa: N802
        self.cancelled.append(order)

    def trades(self) -> list[Trade]:
        return self.session_trades

    async def reqAllOpenOrdersAsync(self) -> list[Trade]:  # noqa: N802
        self.session_trades += self.gateway_trades
        return self.gateway_trades

    async def reqExecutionsAsync(self) -> list[IBFill]:  # noqa: N802
        return self.executions


def broker(
    ib: StubIB,
    mode: RunMode = RunMode.PAPER,
    account: str = "DU123",
    env: dict[str, str] | None = None,
) -> IBKRBroker:
    return IBKRBroker(mode=mode, account_id=account, ib=ib, env=env or {})  # type: ignore[arg-type]


# ------------------------------------------------------------------ safety


def test_is_paper_account() -> None:
    assert is_paper_account("DU1234567")
    assert is_paper_account("df12")
    assert not is_paper_account("U1234567")


def test_construction_guards() -> None:
    with pytest.raises(BrokerError, match="DryRunBroker"):
        IBKRBroker(mode=RunMode.DRY_RUN, account_id="DU1", env={})
    with pytest.raises(LiveTradingNotAllowedError):
        IBKRBroker(mode=RunMode.LIVE, account_id="U1", env={})
    stub: Any = StubIB(["U1"])
    live = IBKRBroker(mode=RunMode.LIVE, account_id="U1", env={"QUANT_ALLOW_LIVE": "1"}, ib=stub)
    assert live.mode is RunMode.LIVE


@pytest.mark.parametrize(
    ("mode", "account", "managed", "message"),
    [
        (RunMode.PAPER, "DU123", ["U999"], "not managed"),
        (RunMode.PAPER, "DU123", ["DU123", "U999"], "live account"),
        (RunMode.LIVE, "DU123", ["DU123"], "paper account"),
    ],
)
async def test_connect_refuses_mode_account_mismatch(
    mode: RunMode, account: str, managed: list[str], message: str
) -> None:
    ib = StubIB(managed)
    b = broker(ib, mode, account, env={"QUANT_ALLOW_LIVE": "1"})
    with pytest.raises(BrokerError, match=message):
        await b.connect()
    assert not ib.connected  # disconnected again


async def test_connect_ok_and_health() -> None:
    ib = StubIB(["DU123"])
    b = broker(ib)
    assert not await b.is_healthy()
    await b.connect()
    await b.connect()  # idempotent
    assert ib.connect_kw["clientId"] == 18
    assert await b.is_healthy()
    ib.time_fails = True
    assert not await b.is_healthy()
    await b.disconnect()
    assert not ib.connected


def test_from_account_uses_its_own_client_id() -> None:
    cfg = AccountConfig(name="ibkr_main", account_id="DU9", host="gw", port=4004, client_id=17)
    b = IBKRBroker.from_account(cfg, RunMode.PAPER, env={})
    assert (b.host, b.port, b.client_id, b.account_id) == ("gw", 4004, 18, "DU9")


async def test_requires_connection() -> None:
    stub: Any = StubIB()
    with pytest.raises(BrokerError, match="not connected"):
        await IBKRBroker(mode=RunMode.PAPER, account_id="DU1", env={}, ib=stub).submit(
            intent(), AAPL
        )


# ------------------------------------------------------------------ orders


async def test_submit_limit_order() -> None:
    ib = StubIB()
    b = broker(ib)
    await b.connect()
    result = await b.submit(intent(), AAPL)
    contract, order = ib.placed[0]
    assert contract.conId == 265598
    assert (order.action, order.totalQuantity, order.lmtPrice) == ("BUY", 10.0, 100.05)
    assert (order.orderType, order.orderRef, order.account, order.tif) == (
        "LMT",
        "q-abc",
        "DU123",
        "DAY",
    )
    assert result.status is OrderStatus.PENDING_SUBMIT


async def test_submit_market_order_and_unresolved_contract() -> None:
    ib = StubIB()
    b = broker(ib)
    await b.connect()
    await b.submit(intent(order_type=OrderType.MARKET), Instrument(symbol="AAPL"))
    contract, order = ib.placed[0]
    assert order.orderType == "MKT"
    assert contract.conId == 4242  # qualified because the instrument had no con_id
    with pytest.raises(BrokerError, match="does not know"):
        await b.submit(intent(), Instrument(symbol="NOPE"))


@pytest.mark.parametrize(
    ("ib_status", "filled", "expected"),
    [
        ("PendingSubmit", 0, OrderStatus.PENDING_SUBMIT),
        ("Submitted", 0, OrderStatus.SUBMITTED),
        ("Submitted", 4, OrderStatus.PARTIALLY_FILLED),
        ("PreSubmitted", 0, OrderStatus.SUBMITTED),
        ("Filled", 10, OrderStatus.FILLED),
        ("Cancelled", 4, OrderStatus.CANCELLED),
        ("ApiCancelled", 0, OrderStatus.CANCELLED),
        ("Inactive", 0, OrderStatus.REJECTED),
        ("SomethingNew", 0, OrderStatus.SUBMITTED),
    ],
)
def test_status_mapping(ib_status: str, filled: int, expected: OrderStatus) -> None:
    assert to_status(ib_status, D(filled)) is expected


def test_fills_wait_for_commission_reports_until_final() -> None:
    fills = [ib_fill("e1", 4, 100.0, commission=0.8), ib_fill("e2", 6, 100.1, commission=None)]
    open_fills = convert_fills(intent(), fills, final=False)
    assert [f.exec_id for f in open_fills] == ["e1"]
    assert open_fills[0].commission == D("0.8")
    final = convert_fills(intent(), fills, final=True)
    assert [(f.exec_id, f.commission) for f in final] == [("e1", D("0.8")), ("e2", D(0))]


def test_result_from_trade() -> None:
    t = trade("Filled", 10, [ib_fill("e1", 10, 100.0)])
    result = result_from_trade(intent(), t)
    assert (result.status, result.filled_qty, result.avg_fill_price) == (
        OrderStatus.FILLED,
        D(10),
        D(100),
    )
    assert result.broker_order_id == "555"
    assert result.message == "note"
    assert result.fills[0].qty == D(10)


async def test_lookup_session_gateway_executions_and_missing() -> None:
    ib = StubIB()
    b = broker(ib)
    await b.connect()
    assert await b.lookup(intent()) is None

    ib.gateway_trades = [trade("Submitted", 0)]  # placed by an earlier session
    found = await b.lookup(intent())
    assert found is not None
    assert found.status is OrderStatus.SUBMITTED

    ib.session_trades, ib.gateway_trades = [], []
    ib.executions = [ib_fill("e1", 4, 100.0), ib_fill("x", 1, 1.0, order_ref="other")]
    recovered = await b.lookup(intent())
    assert recovered is not None
    assert (recovered.status, recovered.filled_qty) == (OrderStatus.PARTIALLY_FILLED, D(4))
    ib.executions.append(ib_fill("e2", 6, 100.0))
    complete = await b.lookup(intent())
    assert complete is not None
    assert complete.status is OrderStatus.FILLED


async def test_cancel() -> None:
    ib = StubIB()
    b = broker(ib)
    await b.connect()
    with pytest.raises(BrokerError, match="no open IBKR order"):
        await b.cancel(intent())
    ib.session_trades = [trade("Submitted")]
    await b.cancel(intent())
    assert len(ib.cancelled) == 1
    ib.session_trades = [trade("Filled", 10)]
    await b.cancel(intent())
    assert len(ib.cancelled) == 1  # done orders are not cancelled


async def test_cancel_waits_for_confirmation() -> None:
    ib = StubIB()
    slept: list[float] = []
    pending = trade("Submitted")

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 2:  # IBKR confirms after half a second
            pending.orderStatus.status = "Cancelled"

    b = IBKRBroker(mode=RunMode.PAPER, account_id="DU123", ib=ib, env={}, sleep=sleep)  # type: ignore[arg-type]
    await b.connect()
    ib.session_trades = [pending]
    result = await b.cancel(intent())
    assert result.status is OrderStatus.CANCELLED  # not the stale "submitted"
    assert slept == [0.25, 0.25]

    stuck = trade("Submitted")
    ib.session_trades = [stuck]
    b.cancel_wait_s = 1.0
    slept.clear()
    unconfirmed = await b.cancel(intent())
    assert unconfirmed.status is OrderStatus.SUBMITTED  # reported as is, never guessed
    assert len(slept) == 4


async def test_order_not_transmitted_is_flagged() -> None:
    ib = StubIB()
    b = broker(ib)
    await b.connect()
    held = trade("PreSubmitted", perm_id=0)
    held.log[0].time = datetime.now(UTC) - timedelta(minutes=2)  # permId stays 0: still inside TWS
    ib.session_trades = [held]
    with capture_logs() as logs:
        await b.lookup(intent())
        await b.lookup(intent())
    warnings = [e for e in logs if e["event"] == "ibkr_broker.not_transmitted"]
    assert len(warnings) == 1  # warned once
    assert "Bypass Order Precautions" in warnings[0]["hint"]
