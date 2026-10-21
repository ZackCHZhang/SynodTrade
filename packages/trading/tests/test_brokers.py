from decimal import Decimal
from uuid import uuid4

import pytest

from synodtrade_core.models import (
    Action,
    Instrument,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    RunMode,
)
from synodtrade_trading import BrokerError, DryRunBroker, SimulatedBroker, client_order_id

D = Decimal
AAPL = Instrument(symbol="AAPL", con_id=265598)


def intent(
    qty: str = "10", order_type: OrderType = OrderType.LIMIT, action: Action = Action.BUY
) -> OrderIntent:
    return OrderIntent(
        client_order_id=f"c-{uuid4().hex[:8]}",
        run_id=uuid4(),
        pipeline_name="p",
        symbol="AAPL",
        action=action,
        side=OrderSide.BUY if action.direction > 0 else OrderSide.SELL,
        quantity=D(qty),
        order_type=order_type,
        limit_price=D("100.05") if order_type is OrderType.LIMIT else None,
        estimated_notional=D(qty) * 100,
    )


def test_client_order_id_is_deterministic() -> None:
    run = uuid4()
    a = client_order_id(run, "aapl", Action.BUY)
    assert a == client_order_id(run, "AAPL", Action.BUY)
    assert a.startswith("q-")
    assert len(a) == 26
    assert a != client_order_id(run, "AAPL", Action.STRONG_BUY)
    assert a != client_order_id(uuid4(), "AAPL", Action.BUY)


async def test_dry_run_broker_never_sends() -> None:
    broker = DryRunBroker()
    await broker.connect()
    assert broker.mode is RunMode.DRY_RUN
    assert await broker.is_healthy()
    order = intent()
    result = await broker.submit(order, AAPL)
    assert result.status is OrderStatus.DRY_RUN
    assert result.status.is_terminal
    assert result.fills == []
    assert broker.submitted == [order]
    assert await broker.lookup(order) is None
    assert (await broker.cancel(order)).status is OrderStatus.DRY_RUN
    await broker.disconnect()


async def test_simulated_immediate_fill() -> None:
    broker = SimulatedBroker(commission=D("0.5"))
    await broker.connect()
    order = intent()
    result = await broker.submit(order, AAPL)
    assert result.status is OrderStatus.FILLED
    assert (result.filled_qty, result.avg_fill_price) == (D(10), D("100.05"))
    assert result.fills[0].commission == D("0.5")
    assert await broker.lookup(order) == result
    assert (await broker.cancel(order)).status is OrderStatus.FILLED  # done orders stay done
    await broker.disconnect()


async def test_simulated_partial_never_reject() -> None:
    partial = SimulatedBroker("partial")
    p = intent("7")
    first = await partial.submit(p, AAPL)
    assert (first.status, first.filled_qty) == (OrderStatus.PARTIALLY_FILLED, D(3))
    cancelled = await partial.cancel(p)
    assert (cancelled.status, cancelled.filled_qty) == (OrderStatus.CANCELLED, D(3))
    one = await SimulatedBroker("partial").submit(intent("1"), AAPL)
    assert (one.status, one.fills) == (OrderStatus.SUBMITTED, [])

    never = SimulatedBroker("never")
    n = intent()
    assert (await never.submit(n, AAPL)).status is OrderStatus.SUBMITTED
    assert (await never.cancel(n)).status is OrderStatus.CANCELLED

    rejected = await SimulatedBroker("reject").submit(intent(), AAPL)
    assert rejected.status is OrderStatus.REJECTED

    sim = SimulatedBroker()
    sim.healthy = False
    assert not await sim.is_healthy()
    assert await sim.lookup(intent()) is None
    with pytest.raises(BrokerError, match="unknown order"):
        await sim.cancel(intent())


async def test_simulated_market_orders() -> None:
    with pytest.raises(BrokerError, match="market_price"):
        await SimulatedBroker().submit(intent(order_type=OrderType.MARKET), AAPL)
    result = await SimulatedBroker(market_price=D(99)).submit(
        intent(order_type=OrderType.MARKET), AAPL
    )
    assert result.avg_fill_price == D(99)
