from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from quant_core.config import AccountConfig, ConfigStore, PipelineConfig, StageConfig
from quant_core.models import (
    AccountSnapshot,
    Action,
    AggregatedDecision,
    Instrument,
    OrderIntent,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    PipelineContext,
    Quote,
    RiskVerdict,
    RunMode,
    Verdict,
)
from quant_core.models import (
    Instrument as Inst,
)
from quant_core.registry import STAGES
from quant_core.safety import LiveTradingNotAllowedError
from quant_core.services import Services
from quant_database import KILL_SWITCH, Repositories
from quant_trading import (
    BrokerError,
    DryRunBroker,
    IBKRBroker,
    SimulatedBroker,
    TradingError,
    TradingOptions,
    TradingStage,
    build_trading_stage,
    client_order_id,
    create_broker,
    limit_price,
    tick_size,
)

D = Decimal
A = Action
NOW = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)
NewRun = Callable[..., Awaitable[UUID]]
Seed = Callable[..., Awaitable[None]]


# ------------------------------------------------------------------ pricing


def test_tick_size() -> None:
    assert tick_size(D("1")) == D("0.01")
    assert tick_size(D("0.9999")) == D("0.0001")


@pytest.mark.parametrize(
    ("side", "quote", "reference", "bps", "expected"),
    [
        (OrderSide.BUY, ("99.95", "100.05"), "100", "5", "100.11"),  # 100.1000025 -> up
        (OrderSide.SELL, ("99.95", "100.05"), "100", "5", "99.90"),  # 99.900025 -> down
        (OrderSide.BUY, None, "100", "0", "100.00"),
        (OrderSide.SELL, None, "50", "10", "49.95"),
        (OrderSide.BUY, ("0.5", "0.5012"), "0.5", "5", "0.5015"),  # sub-dollar tick
        (OrderSide.SELL, None, "0.0001", "500", "0.0001"),  # never below one tick
    ],
)
def test_limit_price(
    side: OrderSide, quote: tuple[str, str] | None, reference: str, bps: str, expected: str
) -> None:
    q = Quote(symbol="X", ts=NOW, bid=D(quote[0]), ask=D(quote[1])) if quote else None
    assert limit_price(side, q, D(reference), D(bps)) == D(expected)


# ------------------------------------------------------------------ helpers


def verdict(run_id: UUID, symbol: str, action: Action) -> RiskVerdict:
    return RiskVerdict(
        run_id=run_id,
        symbol=symbol,
        source="final",
        verdict=Verdict.APPROVE,
        original_action=action,
        adjusted_action=action,
        reason="ok",
    )


def context(
    run_id: UUID, actions: dict[str, Action], mode: RunMode = RunMode.DRY_RUN
) -> PipelineContext:
    ctx = PipelineContext(
        run_id=run_id,
        pipeline_name="long_term_stocks",
        mode=mode,
        universe=list(actions),
        as_of=NOW,
    )
    for i, (symbol, action) in enumerate(actions.items()):
        ctx.risk_verdicts[symbol] = verdict(run_id, symbol, action)
        ctx.aggregated_decisions[symbol] = AggregatedDecision(
            run_id=run_id,
            symbol=symbol,
            final_action=action,
            method="m",
            score=0.1 * (i + 1),
            votes=[],
        )
    return ctx


def pipeline(max_capital: int = 10_000) -> PipelineConfig:
    return PipelineConfig.model_validate(
        {
            "name": "long_term_stocks",
            "account": "ibkr_main",
            "universe": ["AAPL"],
            "budget": {"max_capital": max_capital},
            "stages": [{"type": "risk"}, {"type": "trading"}],
        }
    )


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 1.0)


def build(
    repos: Repositories,
    broker: Any,
    *,
    options: dict[str, Any] | None = None,
    clock: FakeClock | None = None,
    **services: Any,
) -> TradingStage:
    config = StageConfig.model_validate({"type": "trading", **(options or {})})
    stage = build_trading_stage(
        config, Services(repos=repos, broker=broker, pipeline=pipeline(), **services)
    )
    clock = clock or FakeClock()
    stage._sleep, stage._monotonic = clock.sleep, clock
    return stage


async def filled_position(
    repos: Repositories, new_run: NewRun, symbol: str, qty: str, price: str
) -> None:
    run = await new_run(NOW - timedelta(days=3))
    order = OrderIntent(
        client_order_id=f"seed-{symbol}",
        run_id=run,
        pipeline_name="long_term_stocks",
        symbol=symbol,
        action=A.BUY,
        side=OrderSide.BUY,
        quantity=D(qty),
        order_type=OrderType.LIMIT,
        limit_price=D(price),
        estimated_notional=D(qty) * D(price),
    )
    await repos.orders.create(order, created_at=NOW - timedelta(days=3))
    sim = SimulatedBroker(commission=D(0))
    await repos.orders.apply_result(await sim.submit(order, Inst(symbol=symbol)))


# ------------------------------------------------------------------ planning + execution


async def test_end_to_end_with_simulated_fills(
    repos: Repositories, new_run: NewRun, seed_market: Seed
) -> None:
    await seed_market(
        {"AAPL": "100", "MSFT": "400", "NVDA": "50"}, quotes={"AAPL": ("99.95", "100.05")}
    )
    await repos.instruments.upsert(Instrument(symbol="AAPL", con_id=265598))
    await filled_position(repos, new_run, "NVDA", "40", "50")  # cash 10,000 - 2,000 = 8,000
    run_id = await new_run()
    broker = SimulatedBroker(commission=D(1))
    stage = build(repos, broker)
    ctx = context(run_id, {"AAPL": A.STRONG_BUY, "MSFT": A.BUY, "NVDA": A.SELL, "TSLA": A.HOLD})
    ctx = await stage.run(ctx)

    intents = {i.symbol: i for i in ctx.order_intents}
    # sells first, then buys by conviction (MSFT score 0.2 before AAPL 0.1)
    assert [i.symbol for i in ctx.order_intents] == ["NVDA", "MSFT", "AAPL"]
    nvda, msft, aapl = intents["NVDA"], intents["MSFT"], intents["AAPL"]
    assert (nvda.side, nvda.quantity, nvda.limit_price) == (OrderSide.SELL, D(6), D("49.97"))
    # MSFT: 15% of 8,000 = 1,200 at limit 400.20 -> 2 shares (800.40);
    # AAPL: 30% of the remaining 7,199.60 = 2,159.88 at limit 100.11 -> 21 shares
    assert (msft.quantity, msft.limit_price) == (D(2), D("400.20"))
    assert (aapl.quantity, aapl.limit_price) == (D(21), D("100.11"))
    assert aapl.client_order_id == client_order_id(run_id, "AAPL", A.STRONG_BUY)
    assert "TSLA" not in intents

    assert {r.status for r in ctx.order_results} == {OrderStatus.FILLED}
    ledger = await repos.ledger.get_state("long_term_stocks", D(10_000))
    assert ledger.position_qty("AAPL") == D(21)
    assert ledger.position_qty("NVDA") == D(34)
    assert len(await repos.orders.get_fills(aapl.client_order_id)) == 1

    # re-running the same run_id sends nothing twice
    submitted = broker.submit_count
    again = await build(repos, broker).run(context(run_id, {"AAPL": A.STRONG_BUY}))
    assert broker.submit_count == submitted
    assert again.order_results[0].status is OrderStatus.FILLED


async def test_dry_run_records_but_sends_nothing(
    repos: Repositories, new_run: NewRun, seed_market: Seed
) -> None:
    await seed_market({"AAPL": "100"})
    run_id = await new_run()
    broker = DryRunBroker()
    ctx = await build(repos, broker).run(context(run_id, {"AAPL": A.BUY}))
    assert [r.status for r in ctx.order_results] == [OrderStatus.DRY_RUN]
    [record] = await repos.orders.list_by_run(run_id)
    assert record.status is OrderStatus.DRY_RUN
    ledger = await repos.ledger.get_state("long_term_stocks", D(10_000))
    assert ledger.positions == {}  # nothing filled


async def test_partial_fill_is_cancelled_after_timeout(
    repos: Repositories, new_run: NewRun, seed_market: Seed
) -> None:
    await seed_market({"AAPL": "100"})
    run_id = await new_run()
    broker = SimulatedBroker("partial")
    clock = FakeClock()
    ctx = await build(
        repos, broker, clock=clock, options={"cancel_after_minutes": 1, "poll_interval_seconds": 10}
    ).run(context(run_id, {"AAPL": A.BUY}))
    [result] = ctx.order_results
    assert result.status is OrderStatus.CANCELLED
    assert result.filled_qty == D(7)  # 15 ordered (1,500 / 100.05), half filled
    assert clock.now >= 60
    ledger = await repos.ledger.get_state("long_term_stocks", D(10_000))
    assert ledger.position_qty("AAPL") == D(7)


async def test_rejected_orders_and_skips(
    repos: Repositories, new_run: NewRun, seed_market: Seed
) -> None:
    await seed_market({"AAPL": "100", "BRK": "700000"})
    run_id = await new_run()
    ctx = await build(repos, SimulatedBroker("reject")).run(
        context(run_id, {"AAPL": A.BUY, "BRK": A.BUY, "GHOST": A.BUY, "MSFT": A.SELL})
    )
    assert [
        (r.status, i.symbol) for r, i in zip(ctx.order_results, ctx.order_intents, strict=True)
    ] == [(OrderStatus.REJECTED, "AAPL")]


async def test_no_wait_and_reconcile_later(
    repos: Repositories, new_run: NewRun, seed_market: Seed
) -> None:
    await seed_market({"AAPL": "100"})
    run_id = await new_run()
    broker = SimulatedBroker("never")
    ctx = await build(repos, broker, options={"wait_for_fills": False}).run(
        context(run_id, {"AAPL": A.BUY})
    )
    assert ctx.order_results[0].status is OrderStatus.SUBMITTED

    # the broker fills it later; the next run reconciles before doing anything else
    coid = ctx.order_intents[0].client_order_id
    sim_order = broker.orders[coid]
    fill_result = await SimulatedBroker().submit(sim_order.intent, Inst(symbol="AAPL"))
    sim_order.result = fill_result
    next_run = await new_run()
    await build(repos, broker).run(context(next_run, {}))
    record = await repos.orders.get(coid)
    assert record is not None
    assert record.status is OrderStatus.FILLED


async def test_pending_order_is_looked_up_before_resending(
    repos: Repositories, new_run: NewRun, seed_market: Seed
) -> None:
    await seed_market({"AAPL": "100"})
    run_id = await new_run()
    broker = SimulatedBroker()
    # a previous attempt recorded the order and sent it, then crashed before saving the result
    stage = build(repos, broker)
    ctx = context(run_id, {"AAPL": A.BUY})
    planned, _ = await stage.planner.plan(ctx)
    await repos.orders.create(planned[0].intent, created_at=NOW)
    await broker.submit(planned[0].intent, planned[0].instrument)
    ctx = await stage.run(ctx)
    assert broker.submit_count == 1  # found at the broker, not sent again
    assert ctx.order_results[0].status is OrderStatus.FILLED


async def test_submit_failure_leaves_order_pending(
    repos: Repositories, new_run: NewRun, seed_market: Seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_market({"AAPL": "100"})
    run_id = await new_run()
    broker = SimulatedBroker()

    async def boom(*_: Any) -> OrderResult:
        raise ConnectionError("socket closed")

    monkeypatch.setattr(broker, "submit", boom)
    with pytest.raises(TradingError, match="AAPL"):
        await build(repos, broker).run(context(run_id, {"AAPL": A.BUY}))
    [record] = await repos.orders.list_by_run(run_id)
    assert record.status is OrderStatus.PENDING_SUBMIT
    assert "socket closed" in (record.message or "")


async def test_cancel_failure_is_logged_not_raised(
    repos: Repositories, new_run: NewRun, seed_market: Seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_market({"AAPL": "100"})
    run_id = await new_run()
    broker = SimulatedBroker("never")

    async def cannot(*_: Any) -> OrderResult:
        raise BrokerError("already gone")

    monkeypatch.setattr(broker, "cancel", cannot)
    ctx = await build(repos, broker, options={"cancel_after_minutes": 0.01}).run(
        context(run_id, {"AAPL": A.BUY})
    )
    assert ctx.order_results[0].status is OrderStatus.SUBMITTED


# ------------------------------------------------------------------ safety


async def test_kill_switch_stops_new_orders(
    repos: Repositories, new_run: NewRun, seed_market: Seed
) -> None:
    await seed_market({"AAPL": "100"})
    await repos.flags.set(KILL_SWITCH, True, "stop")
    broker = SimulatedBroker()
    ctx = await build(repos, broker).run(context(await new_run(), {"AAPL": A.BUY}))
    assert broker.submit_count == 0
    assert ctx.order_intents == []


async def test_broker_mode_must_match_run_mode(repos: Repositories, new_run: NewRun) -> None:
    run_id = await new_run(mode=RunMode.PAPER)
    with pytest.raises(TradingError, match="broker simulated is for mode dry_run"):
        await build(repos, SimulatedBroker()).run(
            context(run_id, {"AAPL": A.BUY}, mode=RunMode.PAPER)
        )


async def test_live_run_needs_env_flag(
    repos: Repositories, new_run: NewRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("QUANT_ALLOW_LIVE", raising=False)
    run_id = await new_run(mode=RunMode.LIVE)
    with pytest.raises(LiveTradingNotAllowedError):
        await build(repos, SimulatedBroker()).run(
            context(run_id, {"AAPL": A.BUY}, mode=RunMode.LIVE)
        )


async def test_account_caps_cash(repos: Repositories, new_run: NewRun, seed_market: Seed) -> None:
    await seed_market({"AAPL": "100"})
    await repos.accounts.add_snapshot(
        AccountSnapshot(
            account_id="DU1",
            ts=NOW,
            nav=D(1e6),
            cash=D(500),
            buying_power=D(500),
            available_funds=D(1000),
        ),
        [],
    )
    account = AccountConfig(name="ibkr_main", account_id="DU1", port=4002, client_id=1)
    ctx = await build(repos, SimulatedBroker(), account=account).run(
        context(await new_run(), {"AAPL": A.STRONG_BUY})
    )
    assert ctx.order_intents[0].quantity == D(2)  # 30% of 1,000 at 100.05


async def test_market_orders_and_stale_quotes(
    repos: Repositories, new_run: NewRun, seed_market: Seed
) -> None:
    await seed_market({"AAPL": "100"})
    await repos.quotes.add([Quote(symbol="AAPL", ts=NOW - timedelta(hours=2), bid=D(1), ask=D(2))])
    ctx = await build(
        repos, SimulatedBroker(market_price=D(100)), options={"order_type": "market"}
    ).run(context(await new_run(), {"AAPL": A.BUY}))
    [intent] = ctx.order_intents
    assert (intent.order_type, intent.limit_price, intent.quantity) == (
        OrderType.MARKET,
        None,
        D(15),
    )  # stale quote ignored: 1,500 / last close 100


# ------------------------------------------------------------------ factories


def test_create_broker() -> None:
    assert isinstance(create_broker(RunMode.DRY_RUN, None), DryRunBroker)
    account = AccountConfig(name="ibkr_main", account_id="DU1", port=4002, client_id=17)
    paper = create_broker(RunMode.PAPER, account, env={})
    assert isinstance(paper, IBKRBroker)
    assert (paper.mode, paper.client_id) == (RunMode.PAPER, 18)
    with pytest.raises(TradingError, match="needs an IBKR account"):
        create_broker(RunMode.PAPER, None)
    with pytest.raises(LiveTradingNotAllowedError):
        create_broker(RunMode.LIVE, account, env={})


def test_entry_point_and_repo_options() -> None:
    assert STAGES.get("trading") is build_trading_stage
    repo = ConfigStore(Path(__file__).resolve().parents[3] / "configs", env={"IBKR_ACCOUNT": "x"})
    stage = repo.pipeline("long_term_stocks").stage("trading")
    assert stage is not None
    options = stage.options(TradingOptions)
    assert (options.order_type, options.limit_offset_bps, options.cancel_after_minutes) == (
        OrderType.LIMIT,
        D(5),
        30,
    )


async def test_pending_order_unknown_to_broker_is_sent_once(
    repos: Repositories, new_run: NewRun, seed_market: Seed
) -> None:
    await seed_market({"AAPL": "100"})
    run_id = await new_run()
    broker = SimulatedBroker()
    stage = build(repos, broker)
    ctx = context(run_id, {"AAPL": A.BUY})
    planned, _ = await stage.planner.plan(ctx)
    await repos.orders.create(planned[0].intent, created_at=NOW)  # crashed before sending
    ctx = await stage.run(ctx)
    assert broker.submit_count == 1
    assert ctx.order_results[0].status is OrderStatus.FILLED


async def test_pending_order_still_pending_at_broker_is_not_resent(
    repos: Repositories, new_run: NewRun, seed_market: Seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_market({"AAPL": "100"})
    run_id = await new_run()
    broker = SimulatedBroker("never")
    stage = build(repos, broker, options={"wait_for_fills": False})
    ctx = context(run_id, {"AAPL": A.BUY})
    planned, _ = await stage.planner.plan(ctx)
    intent = planned[0].intent
    await repos.orders.create(intent, created_at=NOW)

    async def pending(order: OrderIntent) -> OrderResult:
        return OrderResult(
            client_order_id=order.client_order_id,
            status=OrderStatus.PENDING_SUBMIT,
            broker_order_id="ib-1",
        )

    monkeypatch.setattr(broker, "lookup", pending)
    ctx = await stage.run(ctx)
    assert broker.submit_count == 0
    record = await repos.orders.get(intent.client_order_id)
    assert record is not None
    assert record.broker_order_id == "ib-1"
