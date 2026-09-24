from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from quant_core.models import (
    Action,
    Fill,
    OrderIntent,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
)
from quant_database import KILL_SWITCH, Repositories

D = Decimal
MakeRun = Callable[..., Awaitable[UUID]]
T0 = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)


def intent(
    run_id: UUID,
    coid: str,
    *,
    symbol: str = "AAPL",
    action: Action = Action.BUY,
    qty: str = "10",
    price: str = "100",
    pipeline: str = "long_term_stocks",
) -> OrderIntent:
    side = OrderSide.BUY if action.direction > 0 else OrderSide.SELL
    return OrderIntent(
        client_order_id=coid,
        run_id=run_id,
        pipeline_name=pipeline,
        symbol=symbol,
        action=action,
        side=side,
        quantity=D(qty),
        order_type=OrderType.LIMIT,
        limit_price=D(price),
        estimated_notional=D(qty) * D(price),
    )


def fill(
    coid: str,
    exec_id: str,
    qty: str,
    price: str,
    *,
    side: OrderSide = OrderSide.BUY,
    symbol: str = "AAPL",
    commission: str = "1",
    minutes: int = 0,
) -> Fill:
    return Fill(
        exec_id=exec_id,
        client_order_id=coid,
        symbol=symbol,
        side=side,
        qty=D(qty),
        price=D(price),
        commission=D(commission),
        ts=T0 + timedelta(minutes=minutes),
    )


# ------------------------------------------------------------------ orders


async def test_create_is_idempotent(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    order_intent = intent(run_id, "coid-1")
    record, created = await repos.orders.create(order_intent)
    assert created
    assert record.status is OrderStatus.PENDING_SUBMIT
    assert record.intent == order_intent
    assert record.remaining_qty == D(10)

    again, created_again = await repos.orders.create(order_intent)
    assert not created_again
    assert again.id == record.id
    assert len(await repos.orders.list_by_run(run_id)) == 1


async def test_apply_result_and_fills(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    await repos.orders.create(intent(run_id, "c1"))
    partial = OrderResult(
        client_order_id="c1",
        status=OrderStatus.PARTIALLY_FILLED,
        broker_order_id="42",
        filled_qty=D(4),
        avg_fill_price=D("99.5"),
        fills=[fill("c1", "e1", "4", "99.5")],
    )
    rec = await repos.orders.apply_result(partial)
    assert rec.status is OrderStatus.PARTIALLY_FILLED
    assert rec.broker_order_id == "42"
    assert rec.remaining_qty == D(6)

    done = OrderResult(
        client_order_id="c1",
        status=OrderStatus.FILLED,
        filled_qty=D(10),
        avg_fill_price=D("99.8"),
        fills=[fill("c1", "e1", "4", "99.5"), fill("c1", "e2", "6", "100", minutes=1)],
    )
    rec = await repos.orders.apply_result(done)
    assert rec.status is OrderStatus.FILLED
    assert rec.broker_order_id == "42"  # kept when the update doesn't repeat it
    assert [f.exec_id for f in await repos.orders.get_fills("c1")] == ["e1", "e2"]
    assert await repos.orders.list_open() == []


async def test_terminal_orders_cannot_change(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    await repos.orders.create(intent(run_id, "c1"))
    await repos.orders.apply_result(OrderResult(client_order_id="c1", status=OrderStatus.CANCELLED))
    with pytest.raises(ValueError, match="already cancelled"):
        await repos.orders.apply_result(
            OrderResult(client_order_id="c1", status=OrderStatus.FILLED, filled_qty=D(10))
        )
    # repeating the same terminal status is harmless (e.g. duplicate broker callbacks)
    await repos.orders.apply_result(OrderResult(client_order_id="c1", status=OrderStatus.CANCELLED))


async def test_apply_result_validation(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    with pytest.raises(KeyError, match="unknown order"):
        await repos.orders.apply_result(OrderResult(client_order_id="x", status=OrderStatus.FILLED))
    await repos.orders.create(intent(run_id, "c1"))
    with pytest.raises(ValueError, match="do not belong"):
        await repos.orders.apply_result(
            OrderResult(
                client_order_id="c1",
                status=OrderStatus.FILLED,
                fills=[fill("other", "e9", "1", "1")],
            )
        )


async def test_open_orders_and_counts(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    await repos.orders.create(intent(run_id, "a"))
    await repos.orders.create(intent(run_id, "b", symbol="MSFT"))
    await repos.orders.create(intent(run_id, "c", pipeline="etf_allocation"))
    await repos.orders.create(intent(run_id, "d"), status=OrderStatus.REJECTED)
    assert {o.client_order_id for o in await repos.orders.list_open()} == {"a", "b", "c"}
    assert {o.client_order_id for o in await repos.orders.list_open("long_term_stocks")} == {
        "a",
        "b",
    }
    since = T0 - timedelta(days=365)
    assert await repos.orders.count_since("long_term_stocks", since) == 2  # rejected not counted
    assert await repos.orders.count_since("long_term_stocks", since, symbol="msft") == 1
    assert await repos.orders.count_since("long_term_stocks", datetime.now(UTC) + timedelta(1)) == 0
    assert await repos.orders.get("zzz") is None


# ------------------------------------------------------------------ ledger


async def test_ledger_tracks_cash_positions_and_pnl(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    cap = D(5000)
    await repos.orders.create(intent(run_id, "buy1", qty="10", price="100"))
    await repos.orders.apply_result(
        OrderResult(
            client_order_id="buy1",
            status=OrderStatus.FILLED,
            filled_qty=D(10),
            fills=[fill("buy1", "e1", "10", "100", commission="1")],
        )
    )
    await repos.orders.create(intent(run_id, "sell1", action=Action.SELL, qty="4", price="110"))
    await repos.orders.apply_result(
        OrderResult(
            client_order_id="sell1",
            status=OrderStatus.FILLED,
            filled_qty=D(4),
            fills=[
                fill("sell1", "e2", "4", "110", side=OrderSide.SELL, commission="1", minutes=60)
            ],
        )
    )

    state = await repos.ledger.get_state("long_term_stocks", cap, as_of=T0 + timedelta(days=1))
    # buy: 5000 - 1000 - 1 = 3999; sell: +440 - 1 = 4438
    assert state.cash == D(4438)
    pos = state.positions["AAPL"]
    assert pos.qty == D(6)
    assert pos.avg_cost == D("100.1")  # (1000 + 1) / 10
    assert state.realized_pnl == D(439) - D("400.4")  # proceeds 439 - cost 4 * 100.1
    assert state.commissions == D(2)
    assert state.position_qty("aapl") == D(6)
    assert state.position_qty("MSFT") == D(0)
    assert state.nav({"AAPL": D(120)}) == D(4438) + 6 * D(120)
    assert state.nav({}) == D(4438) + pos.cost_basis

    before_sell = await repos.ledger.get_state(
        "long_term_stocks", cap, as_of=T0 + timedelta(minutes=30)
    )
    assert before_sell.position_qty("AAPL") == D(10)
    assert before_sell.cash == D(3999)


async def test_ledger_reserves_cash_for_open_buys(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    await repos.orders.create(intent(run_id, "open", qty="10", price="50"))
    await repos.orders.apply_result(
        OrderResult(
            client_order_id="open",
            status=OrderStatus.PARTIALLY_FILLED,
            filled_qty=D(4),
            fills=[fill("open", "e1", "4", "50", commission="0")],
        )
    )
    await repos.orders.create(intent(run_id, "sell", action=Action.SELL, qty="1", price="50"))
    state = await repos.ledger.get_state("long_term_stocks", D(1000))
    assert state.cash == D(800)
    assert state.reserved_cash == D(300)  # 6 remaining * 50
    assert state.available_cash == D(500)


async def test_ledgers_are_isolated_per_pipeline(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    await repos.orders.create(intent(run_id, "etf", symbol="SPY", pipeline="etf_allocation"))
    await repos.orders.apply_result(
        OrderResult(
            client_order_id="etf",
            status=OrderStatus.FILLED,
            filled_qty=D(10),
            fills=[fill("etf", "e1", "10", "100", symbol="SPY")],
        )
    )
    stocks = await repos.ledger.get_state("long_term_stocks", D(5000))
    assert stocks.positions == {}
    assert stocks.cash == D(5000)
    assert stocks.available_cash == D(5000)
    etf = await repos.ledger.get_state("etf_allocation", D(5000))
    assert etf.position_qty("SPY") == D(10)


async def test_ledger_closes_position_fully(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    await repos.orders.create(intent(run_id, "b", qty="3", price="10"))
    await repos.orders.apply_result(
        OrderResult(
            client_order_id="b",
            status=OrderStatus.FILLED,
            filled_qty=D(3),
            fills=[fill("b", "e1", "3", "10", commission="0")],
        )
    )
    await repos.orders.create(intent(run_id, "s", action=Action.STRONG_SELL, qty="3", price="12"))
    await repos.orders.apply_result(
        OrderResult(
            client_order_id="s",
            status=OrderStatus.FILLED,
            filled_qty=D(3),
            fills=[fill("s", "e2", "3", "12", side=OrderSide.SELL, commission="0", minutes=1)],
        )
    )
    state = await repos.ledger.get_state("long_term_stocks", D(100))
    assert state.positions == {}
    assert state.realized_pnl == D(6)
    assert state.cash == D(106)


# ------------------------------------------------------------------ flags


async def test_kill_switch(repos: Repositories) -> None:
    assert not await repos.flags.kill_switch_active()
    await repos.flags.set(KILL_SWITCH, True, reason="manual stop")
    assert await repos.flags.kill_switch_active()
    assert await repos.flags.get_reason(KILL_SWITCH) == "manual stop"
    await repos.flags.set(KILL_SWITCH, False)
    assert not await repos.flags.kill_switch_active()
    assert await repos.flags.get_reason("unknown") is None


async def test_created_at_can_be_given(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    yesterday = T0 - timedelta(days=1)
    record, _ = await repos.orders.create(intent(run_id, "old"), created_at=yesterday)
    assert record.created_at == yesterday
    assert await repos.orders.count_since("long_term_stocks", T0) == 0
    assert await repos.orders.count_since("long_term_stocks", yesterday) == 1
