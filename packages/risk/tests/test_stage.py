import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from synodtrade_core.config import AccountConfig, ConfigStore, PipelineConfig, StageConfig
from synodtrade_core.llm import FakeLLMClient, LLMClientPool, LLMRequest
from synodtrade_core.models import (
    AccountSnapshot,
    Action,
    AggregatedDecision,
    Bar,
    Fill,
    Fundamentals,
    OrderIntent,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    PipelineContext,
    Position,
    Quote,
    RunMode,
    Timeframe,
    Verdict,
)
from synodtrade_core.registry import AGENTS, STAGES
from synodtrade_core.services import Services
from synodtrade_core.timeutil import utcnow
from synodtrade_database import KILL_SWITCH, Repositories
from synodtrade_risk import (
    AlwaysOpenClock,
    RiskAgent,
    RiskStage,
    RiskStageOptions,
    build_risk_stage,
)

D = Decimal
A = Action
NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)  # Thursday 10:00 New York
NewRun = Callable[..., Awaitable[UUID]]
CLAUDE = {"provider": "anthropic", "name": "claude-opus-5"}


def daily_bars(symbol: str, close: str, days: int = 40, volume: int = 1_000_000) -> list[Bar]:
    last_complete = datetime(2026, 9, 23, 4, 0, tzinfo=UTC)  # yesterday 00:00 New York
    c = D(close)
    return [
        Bar(
            symbol=symbol,
            timeframe=Timeframe.D1,
            ts=last_complete - timedelta(days=i),
            open=c,
            high=c + 1,
            low=c - 1,
            close=c,
            volume=D(volume),
        )
        for i in range(days)
    ]


def agg(run_id: UUID, symbol: str, action: Action, score: float) -> AggregatedDecision:
    return AggregatedDecision(
        run_id=run_id,
        symbol=symbol,
        final_action=action,
        method="weighted_vote",
        score=score,
        votes=[],
    )


async def buy_fill(
    repos: Repositories, run_id: UUID, symbol: str, qty: str, price: str, when: datetime
) -> None:
    coid = f"seed-{symbol}-{when.isoformat()}"
    await repos.orders.create(
        OrderIntent(
            client_order_id=coid,
            run_id=run_id,
            pipeline_name="long_term_stocks",
            symbol=symbol,
            action=A.BUY,
            side=OrderSide.BUY,
            quantity=D(qty),
            order_type=OrderType.LIMIT,
            limit_price=D(price),
            estimated_notional=D(qty) * D(price),
        ),
        created_at=when,
    )
    await repos.orders.apply_result(
        OrderResult(
            client_order_id=coid,
            status=OrderStatus.FILLED,
            filled_qty=D(qty),
            fills=[
                Fill(
                    exec_id=f"e-{coid}",
                    client_order_id=coid,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    qty=D(qty),
                    price=D(price),
                    ts=when,
                )
            ],
        )
    )


class ScriptedRiskOfficers:
    """Per symbol: the first agent approves, the second rejects AAPL and approves the rest."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    def __call__(self, request: LLMRequest) -> str:
        prompt = request.messages[0].content
        symbol = prompt.split("Symbol: ", 1)[1].split("\n", 1)[0]
        proposed = prompt.split('the proposed action is "', 1)[1].split('"', 1)[0]
        n = self.calls[symbol] = self.calls.get(symbol, 0) + 1
        if symbol == "AAPL" and n == 2:
            return json.dumps({"verdict": "reject", "adjusted_action": "hold", "reason": "hype"})
        return json.dumps({"verdict": "approve", "adjusted_action": proposed, "reason": "ok"})


def pipeline() -> PipelineConfig:
    return PipelineConfig.model_validate(
        {
            "name": "long_term_stocks",
            "account": "ibkr_main",
            "universe": ["AAPL"],
            "budget": {"max_capital": 5000},
            "stages": [{"type": "risk"}],
        }
    )


def build(
    repos: Repositories,
    store: ConfigStore,
    llm: FakeLLMClient,
    *,
    options: dict[str, Any] | None = None,
    **services: Any,
) -> RiskStage:
    pool = LLMClientPool({}, env={})
    pool.set("anthropic", llm)
    config = StageConfig.model_validate(
        {
            "type": "risk",
            "rules": "default",
            "agents": [{"agent": "conservative_risk_officer", "count": 2, "model": CLAUDE}],
            **(options or {}),
        }
    )
    base: dict[str, Any] = {
        "repos": repos,
        "config_store": store,
        "llm": pool,
        "pipeline": pipeline(),
        "market_clock": AlwaysOpenClock(),
    }
    merged = {k: v for k, v in {**base, **services}.items() if v is not None}
    return build_risk_stage(config, Services(**merged))


async def seed_market(repos: Repositories) -> None:
    await repos.bars.upsert(
        daily_bars("AAPL", "100")
        + daily_bars("MSFT", "400")
        + daily_bars("NVDA", "50")
        + daily_bars("TSLA", "250")
    )
    await repos.quotes.add(
        [
            Quote(symbol="AAPL", ts=NOW - timedelta(minutes=5), bid=D("99.95"), ask=D("100.05")),
            Quote(symbol="MSFT", ts=NOW - timedelta(minutes=5), bid=D(400), ask=D(404)),  # 99 bps
        ]
    )


async def context(
    repos: Repositories,
    run_id: UUID,
    decisions: dict[str, tuple[Action, float]],
    as_of: datetime = NOW,
) -> PipelineContext:
    """What the decision stage hands over, including the persisted aggregated decisions
    (risk assessments reference them)."""
    ctx = PipelineContext(
        run_id=run_id,
        pipeline_name="long_term_stocks",
        mode=RunMode.DRY_RUN,
        universe=list(decisions),
        as_of=as_of,
    )
    for symbol, (action, score) in decisions.items():
        ctx.aggregated_decisions[symbol] = agg(run_id, symbol, action, score)
    await repos.decisions.add_aggregated(list(ctx.aggregated_decisions.values()))
    return ctx


# ------------------------------------------------------------------ end to end


async def test_rules_then_agents_then_final(
    repos: Repositories, store: ConfigStore, new_run: NewRun
) -> None:
    await seed_market(repos)
    seed_run = await new_run(NOW - timedelta(days=5))
    await buy_fill(repos, seed_run, "NVDA", "20", "50", NOW - timedelta(days=5))
    run_id = await new_run()
    llm = FakeLLMClient(default=ScriptedRiskOfficers())
    ctx = await context(
        repos,
        run_id,
        {
            "AAPL": (A.STRONG_BUY, 0.3),
            "MSFT": (A.BUY, 0.15),
            "NVDA": (A.SELL, -0.15),
            "TSLA": (A.HOLD, 0.0),
        },
    )
    ctx = await build(repos, store, llm).run(ctx)
    final = {s: v for s, v in ctx.risk_verdicts.items()}

    # AAPL: cash 4,000 (5,000 budget - 1,000 in NVDA); strong_buy = 1,200 = 24% of the
    # strategy's 5,000 > 20% position limit -> buy (600, 12%); then one of the two risk
    # officers rejects -> most conservative -> hold
    assert (final["AAPL"].verdict, final["AAPL"].adjusted_action) == (Verdict.REJECT, A.HOLD)
    assert {h.rule for h in final["AAPL"].rule_hits if h.blocking} == {"max_position_pct"}
    assert "conservative_risk_officer reject -> hold" in final["AAPL"].reason
    assert len(final["AAPL"].llm_call_ids) == 2
    # MSFT: 99 bps spread > 50 bps -> buy blocked by the rules, agents never asked
    assert final["MSFT"].adjusted_action is A.HOLD
    assert "liquidity_spread" in {h.rule for h in final["MSFT"].rule_hits if h.blocking}
    # NVDA: sell 15% of the 20 held (3 shares) passes everything
    assert (final["NVDA"].verdict, final["NVDA"].adjusted_action) == (Verdict.APPROVE, A.SELL)
    # TSLA: hold stays hold
    assert final["TSLA"].adjusted_action is A.HOLD
    stamped = await repos.risk.get_by_run(run_id)
    assert {v.created_at for v in stamped} == {NOW}  # rules, agents and final alike

    assert len(llm.requests) == 4  # 2 officers x (AAPL, NVDA)
    nvda_prompt = next(
        r.messages[0].content for r in llm.requests if "Symbol: NVDA" in r.messages[0].content
    )
    assert "sell 3 shares" in nvda_prompt

    stored = await repos.risk.get_by_run(run_id)
    assert sorted(v.source for v in stored).count("rules") == 4
    assert sorted(v.source for v in stored).count("final") == 4
    assert sorted(v.source for v in stored).count("conservative_risk_officer") == 4
    instances = await repos.runs.get_agent_instances(run_id)
    assert [i.agent_type for i in instances] == ["risk", "risk"]


async def test_median_combine_and_approve_on_failure(
    repos: Repositories, store: ConfigStore, new_run: NewRun
) -> None:
    await seed_market(repos)
    run_id = await new_run()
    llm = FakeLLMClient(default="not json")  # both officers fail
    stage = build(repos, store, llm, options={"combine": "median", "on_agent_failure": "approve"})
    ctx = await stage.run(await context(repos, run_id, {"AAPL": (A.BUY, 0.15)}))
    assert ctx.risk_verdicts["AAPL"].adjusted_action is A.BUY
    rejecting = build(repos, store, FakeLLMClient(default="not json"))
    run2 = await new_run()
    ctx2 = await rejecting.run(await context(repos, run2, {"AAPL": (A.BUY, 0.15)}))
    assert ctx2.risk_verdicts["AAPL"].adjusted_action is A.HOLD  # default: fail-safe reject


# ------------------------------------------------------------------ portfolio-level rules


async def test_database_kill_switch(
    repos: Repositories, store: ConfigStore, new_run: NewRun
) -> None:
    await seed_market(repos)
    await repos.flags.set(KILL_SWITCH, True, reason="broker incident")
    run_id = await new_run()
    llm = FakeLLMClient(default=ScriptedRiskOfficers())
    ctx = await build(repos, store, llm).run(
        await context(repos, run_id, {"AAPL": (A.BUY, 0.15), "NVDA": (A.SELL, -0.15)})
    )
    assert all(v.adjusted_action is A.HOLD for v in ctx.risk_verdicts.values())
    assert llm.requests == []
    hit = next(h for h in ctx.risk_verdicts["AAPL"].rule_hits if h.rule == "kill_switch")
    assert "broker incident" in hit.message


async def test_daily_loss_breaker_blocks_buys_not_sells(
    repos: Repositories, store: ConfigStore, new_run: NewRun
) -> None:
    await seed_market(repos)
    seed_run = await new_run(NOW - timedelta(days=5))
    await buy_fill(repos, seed_run, "NVDA", "50", "50", NOW - timedelta(days=5))
    # yesterday's close 50 -> value 2,500 + 2,500 = 5,000; now 45 -> 4,750 (-5%)
    await repos.quotes.add([Quote(symbol="NVDA", ts=NOW, bid=D("44.99"), ask=D("45.01"))])
    run_id = await new_run()
    ctx = await build(repos, store, FakeLLMClient(default=ScriptedRiskOfficers())).run(
        await context(repos, run_id, {"AAPL": (A.BUY, 0.15), "NVDA": (A.SELL, -0.15)})
    )
    assert ctx.risk_verdicts["AAPL"].adjusted_action is A.HOLD
    assert "daily_loss_limit" in {h.rule for h in ctx.risk_verdicts["AAPL"].rule_hits}
    assert ctx.risk_verdicts["NVDA"].adjusted_action is A.SELL


async def test_real_calendar_blocks_weekend(
    repos: Repositories, store: ConfigStore, new_run: NewRun
) -> None:
    await seed_market(repos)
    saturday = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)
    run_id = await new_run(saturday)
    stage = build(repos, store, FakeLLMClient(default=ScriptedRiskOfficers()), market_clock=None)
    ctx = await stage.run(await context(repos, run_id, {"AAPL": (A.BUY, 0.15)}, as_of=saturday))
    assert ctx.risk_verdicts["AAPL"].adjusted_action is A.HOLD
    assert "trading_hours" in {h.rule for h in ctx.risk_verdicts["AAPL"].rule_hits}


async def test_one_order_per_symbol_per_day(
    repos: Repositories, store: ConfigStore, new_run: NewRun
) -> None:
    await seed_market(repos)
    earlier = await new_run(NOW - timedelta(hours=2))
    await buy_fill(repos, earlier, "AAPL", "1", "100", NOW - timedelta(hours=2))
    run_id = await new_run()
    ctx = await build(repos, store, FakeLLMClient(default=ScriptedRiskOfficers())).run(
        await context(repos, run_id, {"AAPL": (A.BUY, 0.15)})
    )
    assert ctx.risk_verdicts["AAPL"].adjusted_action is A.HOLD
    assert "one_order_per_symbol_per_day" in {h.rule for h in ctx.risk_verdicts["AAPL"].rule_hits}


async def test_cash_capped_by_real_account(
    repos: Repositories, store: ConfigStore, new_run: NewRun
) -> None:
    await seed_market(repos)
    await repos.accounts.add_snapshot(
        AccountSnapshot(
            account_id="DU1",
            ts=NOW - timedelta(minutes=1),
            nav=D(100_000),
            cash=D(900),
            buying_power=D(900),
            available_funds=D(1000),
        ),
        [],
    )
    run_id = await new_run()
    llm = FakeLLMClient(default=ScriptedRiskOfficers())
    account = AccountConfig(name="ibkr_main", account_id="DU1", port=4002, client_id=1)
    ctx = await build(repos, store, llm, account=account).run(
        await context(repos, run_id, {"AAPL": (A.BUY, 0.15)})
    )
    # 15% of min(5,000 ledger, 1,000 account) = 150 -> 1 share
    assert "buy 1 shares" in llm.requests[0].messages[0].content
    assert ctx.risk_verdicts["AAPL"].adjusted_action is A.HOLD  # second officer rejects AAPL


async def test_stale_quote_falls_back_to_last_close(
    repos: Repositories, store: ConfigStore, new_run: NewRun
) -> None:
    await repos.bars.upsert(daily_bars("AMD", "150"))
    await repos.quotes.add([Quote(symbol="AMD", ts=NOW - timedelta(hours=3), bid=D(1), ask=D(2))])
    run_id = await new_run()
    llm = FakeLLMClient(default=ScriptedRiskOfficers())
    ctx = await build(repos, store, llm).run(await context(repos, run_id, {"AMD": (A.BUY, 0.15)}))
    assert ctx.risk_verdicts["AMD"].adjusted_action is A.BUY
    hits = {h.rule: h for h in ctx.risk_verdicts["AMD"].rule_hits}
    assert not hits["liquidity_spread"].blocking  # no fresh quote: spread unchecked
    assert "buy 5 shares" in llm.requests[0].messages[0].content  # 750 / 150


async def test_nothing_to_assess(repos: Repositories, store: ConfigStore, new_run: NewRun) -> None:
    run_id = await new_run()
    ctx = PipelineContext(
        run_id=run_id,
        pipeline_name="long_term_stocks",
        mode=RunMode.DRY_RUN,
        universe=["AAPL"],
        as_of=NOW,
    )
    assert await build(repos, store, FakeLLMClient()).run(ctx) is ctx
    assert ctx.risk_verdicts == {}


def test_entry_points_and_repo_options() -> None:
    assert STAGES.get("risk") is build_risk_stage
    assert AGENTS.get("risk") is RiskAgent
    repo = ConfigStore(Path(__file__).resolve().parents[3] / "configs", env={"IBKR_ACCOUNT": "x"})
    stage = repo.pipeline("long_term_stocks").stage("risk")
    assert stage is not None
    options = stage.options(RiskStageOptions)
    assert (options.rules, options.combine.value, options.on_agent_failure) == (
        "default",
        "most_conservative",
        "reject",
    )


# ------------------------------------------------------------------ broker position check


async def test_position_mismatch_closes_the_symbol(
    repos: Repositories, store: ConfigStore, new_run: NewRun
) -> None:
    await seed_market(repos)
    seed_run = await new_run(NOW - timedelta(days=3))
    await buy_fill(repos, seed_run, "AAPL", "10", "100", NOW - timedelta(days=3))
    await buy_fill(repos, seed_run, "MSFT", "2", "400", NOW - timedelta(days=3))
    snapshot = NOW - timedelta(minutes=10)
    await repos.accounts.add_snapshot(
        AccountSnapshot(
            account_id="DU1",
            ts=snapshot,
            nav=D(100_000),
            cash=D(50_000),
            buying_power=D(50_000),
        ),
        [
            Position(account_id="DU1", symbol=s, qty=D(q), avg_cost=D(1), ts=snapshot)
            for s, q in (("AAPL", 4), ("MSFT", 5))
        ],
    )
    account = AccountConfig(name="ibkr_main", account_id="DU1", port=4002, client_id=1)
    llm = FakeLLMClient(default=ScriptedRiskOfficers())
    run_id = await new_run()
    ctx = await build(repos, store, llm, account=account).run(
        await context(repos, run_id, {"AAPL": (A.SELL, -0.2), "MSFT": (A.SELL, -0.1)})
    )
    # AAPL: the account holds 4 but the ledger 10 -> nothing may be traded
    aapl = ctx.risk_verdicts["AAPL"]
    assert aapl.adjusted_action is A.HOLD
    hit = next(h for h in aapl.rule_hits if h.rule == "position_mismatch")
    assert hit.blocking
    assert hit.details == {"broker_qty": 4.0, "ledger_qty": 10.0}
    # MSFT: the account holds more than the ledger (e.g. bought by hand): fine
    assert ctx.risk_verdicts["MSFT"].adjusted_action is A.SELL


async def test_position_check_needs_a_recent_snapshot(
    repos: Repositories, store: ConfigStore, new_run: NewRun
) -> None:
    await seed_market(repos)
    seed_run = await new_run(NOW - timedelta(days=3))
    await buy_fill(repos, seed_run, "AAPL", "10", "100", NOW - timedelta(days=3))
    await repos.accounts.add_snapshot(
        AccountSnapshot(
            account_id="DU1", ts=NOW - timedelta(days=1), nav=D(1), cash=D(1), buying_power=D(1)
        ),
        [],
    )
    account = AccountConfig(name="ibkr_main", account_id="DU1", port=4002, client_id=1)
    run_id = await new_run()
    ctx = await build(
        repos, store, FakeLLMClient(default=ScriptedRiskOfficers()), account=account
    ).run(await context(repos, run_id, {"AAPL": (A.SELL, -0.2)}))
    assert "position_mismatch" not in {h.rule for h in ctx.risk_verdicts["AAPL"].rule_hits}


# ------------------------------------------------------------------ agent inputs


async def test_agent_sees_holdings_history_and_fundamentals(
    repos: Repositories, store: ConfigStore, new_run: NewRun
) -> None:
    await seed_market(repos)
    await repos.bars.upsert(daily_bars("SPY", "500", days=300))
    seed_run = await new_run(NOW - timedelta(days=3))
    await buy_fill(repos, seed_run, "NVDA", "20", "45", NOW - timedelta(days=3))
    past = agg(seed_run, "AAPL", A.STRONG_BUY, 0.4).model_copy(
        update={"created_at": NOW - timedelta(days=3)}
    )
    await repos.decisions.add_aggregated([past])
    await repos.fundamentals.add(
        [
            Fundamentals(
                symbol="AAPL",
                as_of=NOW - timedelta(hours=1),
                name="Apple Inc.",
                industry="Electronic Computers",
                eps_diluted=5.0,
                shares_outstanding=1000.0,
                next_earnings_estimate=(NOW + timedelta(days=3)).date(),
            ),
            Fundamentals(symbol="NVDA", as_of=NOW - timedelta(hours=1), industry="Semiconductors"),
        ]
    )
    pipeline_with_benchmark = pipeline().model_copy(update={"benchmark": "SPY"})
    llm = FakeLLMClient(default=ScriptedRiskOfficers())
    run_id = await new_run()
    await build(repos, store, llm, pipeline=pipeline_with_benchmark).run(
        await context(repos, run_id, {"AAPL": (A.BUY, 0.3)})
    )
    prompt = llm.requests[0].messages[0].content
    assert "- NVDA: " in prompt
    assert "industry Semiconductors" in prompt
    assert "in 2 positions" not in prompt
    assert "in 1 positions" in prompt
    assert "Trades today 0 (limit 4); orders in the last 30 days 1." in prompt
    assert "a 2 x ATR(14) adverse move would cost" in prompt
    assert "Benchmark SPY:" in prompt
    assert "Apple Inc., from sec_edgar filings" in prompt
    assert "P/E (TTM diluted EPS): 20.0" in prompt  # quote mid 100.00 / EPS 5
    assert "Next earnings (estimated: last release + one quarter)" in prompt
    assert "strong_buy at" in prompt
    assert "outcome: not executed" in prompt
    assert f"{run_id}" not in prompt  # the current run's own decision is not "history"


async def test_live_run_sees_the_snapshot_it_fetched_after_starting(
    repos: Repositories, store: ConfigStore, new_run: NewRun
) -> None:
    """data_update runs minutes after `as_of` (the run start): a live run must still see the
    account snapshot it took; a replay (explicit as_of) must not see later data."""
    await seed_market(repos)
    seed_run = await new_run(NOW - timedelta(days=3))
    await buy_fill(repos, seed_run, "AAPL", "10", "100", NOW - timedelta(days=3))
    taken = utcnow() - timedelta(minutes=1)  # after the run's as_of (NOW), fresh for a live run
    await repos.accounts.add_snapshot(
        AccountSnapshot(account_id="DU1", ts=taken, nav=D(1), cash=D(1), buying_power=D(1)),
        [Position(account_id="DU1", symbol="AAPL", qty=D(4), avg_cost=D(1), ts=taken)],
    )
    account = AccountConfig(name="ibkr_main", account_id="DU1", port=4002, client_id=1)
    for live, blocked in ((False, False), (True, True)):
        run_id = await new_run()
        ctx = await context(repos, run_id, {"AAPL": (A.SELL, -0.2)})
        ctx.live = live
        ctx = await build(
            repos, store, FakeLLMClient(default=ScriptedRiskOfficers()), account=account
        ).run(ctx)
        rules = {h.rule for h in ctx.risk_verdicts["AAPL"].rule_hits}
        assert ("position_mismatch" in rules) is blocked
