import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from quant_core.config import ConfigStore, LLMModelConfig, PipelineConfig, StageConfig
from quant_core.llm import FakeLLMClient, LLMClientPool, LLMRequest
from quant_core.models import (
    Action,
    AggregatedDecision,
    Bar,
    Fill,
    OrderIntent,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    PipelineContext,
    RunMode,
    SentimentResult,
)
from quant_core.registry import AGENTS, STAGES
from quant_core.services import Services
from quant_database import LedgerPosition, LedgerState, Repositories
from quant_decision import (
    DecisionAgent,
    DecisionStage,
    SymbolContext,
    build_decision_stage,
    compute_indicators,
    history_entries,
)

D = Decimal
NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)
CLAUDE = {"provider": "anthropic", "name": "claude-opus-5"}
NewRun = Callable[..., Awaitable[UUID]]
MakeBars = Callable[..., list[Bar]]


def sentiment(symbol: str, run_id: UUID, *, error: str | None = None) -> SentimentResult:
    return SentimentResult(
        run_id=run_id,
        instance_id=uuid4(),
        agent_id="retail_mood",
        prompt_version="v1",
        symbol=symbol,
        sentiment=0.4,
        confidence=0.6,
        summary="Upbeat chatter" if error is None else "failed",
        key_events=["earnings beat"],
        error=error,
    )


# ------------------------------------------------------------------ context


def test_context_inputs_and_ids(make_bars: MakeBars) -> None:
    bars = make_bars("AAPL", [100 + i for i in range(60)])
    ledger = LedgerState(
        pipeline_name="p",
        max_capital=D(5000),
        cash=D(4000),
        positions={"AAPL": LedgerPosition("AAPL", D(10), D(1000))},
    )
    run_id = uuid4()
    ok, failed = sentiment("AAPL", run_id), sentiment("AAPL", run_id, error="down")
    past = AggregatedDecision(
        run_id=uuid4(),
        symbol="AAPL",
        final_action=Action.BUY,
        method="m",
        score=0.1,
        votes=[],
        created_at=bars[40].ts + timedelta(hours=30),
    )
    context = SymbolContext(
        symbol="AAPL",
        as_of=NOW,
        bars=bars,
        indicators=compute_indicators(bars),
        ledger=ledger,
        nav=D(5590),
        sentiment=[ok, failed],
        history=history_entries([past], bars, timedelta(days=1)),
        recent_bars_in_prompt=5,
    )
    inputs, ids = context.to_inputs()

    assert inputs["position"] == {
        "id": "pos:AAPL",
        "qty": "10",
        "avg_cost": "100.00",
        "market_value": "1,590.00",
        "unrealized": "+59.00%",
        "weight": "+28.44%",
    }
    assert inputs["cash"] == {
        "available": "4,000.00",
        "nav": "5,590.00",
        "max_capital": "5,000.00",
    }
    assert [b["close"] for b in inputs["bars"]] == [
        "155.00",
        "156.00",
        "157.00",
        "158.00",
        "159.00",
    ]
    indicators = {i["id"]: i["value"] for i in inputs["indicators"]}
    assert indicators["ind:return_1d"] == "+0.63%"
    assert indicators["ind:rsi_14"] == "100.0"
    assert "ind:sma_200" not in indicators  # not enough history
    assert [s["id"] for s in inputs["sentiment"]] == [f"sent:{ok.id}"]  # failed one dropped
    [hist] = inputs["history"]
    assert hist["price_then"] == "140.00"  # last bar completed before the decision
    assert hist["change_since"] == "+13.57%"  # 159 / 140 - 1
    assert {"pos:AAPL", f"sent:{ok.id}", f"hist:{past.id}", "bar:2025-03-01"} <= ids
    assert f"sent:{failed.id}" not in ids


def test_context_without_position(make_bars: MakeBars) -> None:
    bars = make_bars("MSFT", [300] * 40)
    ledger = LedgerState(pipeline_name="p", max_capital=D(1000), cash=D(1000))
    context = SymbolContext(
        symbol="MSFT",
        as_of=NOW,
        bars=bars,
        indicators=compute_indicators(bars),
        ledger=ledger,
        nav=D(1000),
    )
    inputs, ids = context.to_inputs()
    assert inputs["position"] is None
    assert inputs["sentiment"] == []
    assert inputs["history"] == []
    assert not any(i.startswith("pos:") for i in ids)
    assert history_entries([], [], timedelta(days=1)) == []


# ------------------------------------------------------------------ stage


def llm_reply(request: LLMRequest) -> str:
    """Trend follower is bullish, value investor holds; both cite an id or two + a bogus one."""
    prompt = request.messages[0].content
    cited = [i for i in ("ind:rsi_14", "pos:AAPL") if f"[{i}]" in prompt]
    trend = "trend follower" in (request.system or "")
    return json.dumps(
        {
            "action": "strong_buy" if trend else "hold",
            "confidence": 0.9 if trend else 0.7,
            "reasoning": "trend is up" if trend else "no margin of safety",
            "referenced_data_ids": [*cited, "ind:made_up"],
        }
    )


def stage_config() -> StageConfig:
    return StageConfig.model_validate(
        {
            "type": "decision",
            "agents": [
                {"agent": "value_investor", "count": 2, "weight": 1.0, "model": CLAUDE},
                {"agent": "trend_follower", "count": 1, "weight": 0.8, "model": CLAUDE},
            ],
            "aggregation": {"method": "weighted_vote", "min_confidence": 0.6},
        }
    )


def pipeline_config() -> PipelineConfig:
    return PipelineConfig.model_validate(
        {
            "name": "long_term_stocks",
            "account": "ibkr_main",
            "universe": ["AAPL"],
            "budget": {"max_capital": 5000},
            "stages": [{"type": "decision"}],
        }
    )


async def seed(repos: Repositories, new_run: NewRun, make_bars: MakeBars) -> None:
    await repos.bars.upsert(make_bars("AAPL", [100 + i for i in range(300)]))
    await repos.bars.upsert(make_bars("MSFT", [400 - i / 2 for i in range(300)]))
    await repos.bars.upsert(make_bars("NVDA", [50] * 10))  # too short -> no decision
    run = await new_run(NOW - timedelta(days=30))
    intent = OrderIntent(
        client_order_id="seed",
        run_id=run,
        pipeline_name="long_term_stocks",
        symbol="AAPL",
        action=Action.BUY,
        side=OrderSide.BUY,
        quantity=D(5),
        order_type=OrderType.LIMIT,
        limit_price=D(150),
        estimated_notional=D(750),
    )
    await repos.orders.create(intent)
    await repos.orders.apply_result(
        OrderResult(
            client_order_id="seed",
            status=OrderStatus.FILLED,
            filled_qty=D(5),
            fills=[
                Fill(
                    exec_id="e1",
                    client_order_id="seed",
                    symbol="AAPL",
                    side=OrderSide.BUY,
                    qty=D(5),
                    price=D(150),
                    ts=NOW - timedelta(days=30),
                )
            ],
        )
    )


def build(repos: Repositories, store: ConfigStore, llm: FakeLLMClient) -> DecisionStage:
    pool = LLMClientPool({}, env={})
    pool.set("anthropic", llm)
    services = Services(repos=repos, config_store=store, llm=pool, pipeline=pipeline_config())
    return build_decision_stage(stage_config(), services)


async def test_end_to_end(
    repos: Repositories, store: ConfigStore, new_run: NewRun, make_bars: MakeBars
) -> None:
    await seed(repos, new_run, make_bars)
    run_id = await new_run()
    llm = FakeLLMClient(default=llm_reply)
    stage = build(repos, store, llm)
    ctx = PipelineContext(
        run_id=run_id,
        pipeline_name="long_term_stocks",
        mode=RunMode.DRY_RUN,
        universe=["AAPL", "MSFT", "NVDA"],
        as_of=NOW,
    )
    ctx.sentiment_results["AAPL"] = [
        sentiment("AAPL", run_id),
        sentiment("AAPL", run_id, error="x"),
    ]
    ctx = await stage.run(ctx)

    # 3 agent instances x 2 symbols with enough data
    assert len(llm.requests) == 6
    aapl = ctx.aggregated_decisions["AAPL"]
    # 2 x (hold, 0.7, w1) + (strong_buy, 0.9, w0.8): score 0.216 / 2.12 = 0.102 -> BUY
    assert aapl.final_action is Action.BUY
    assert aapl.method == "weighted_vote(min_confidence=0.6)"
    assert len(aapl.votes) == 3
    nvda = ctx.aggregated_decisions["NVDA"]
    assert (nvda.final_action, nvda.method, nvda.votes) == (Action.HOLD, "insufficient_data", [])

    decisions = ctx.decisions["AAPL"]
    trend = next(d for d in decisions if d.agent_id == "trend_follower")
    assert trend.action is Action.STRONG_BUY
    assert trend.referenced_data_ids == ["ind:rsi_14", "pos:AAPL"]  # bogus id dropped
    msft_trend = next(d for d in ctx.decisions["MSFT"] if d.agent_id == "trend_follower")
    assert msft_trend.referenced_data_ids == ["ind:rsi_14"]  # no MSFT position

    prompt = next(
        r.messages[0].content for r in llm.requests if "Symbol: AAPL" in r.messages[0].content
    )
    assert "Position [pos:AAPL]: 5 shares, average cost 150.00" in prompt
    assert "Available cash: 4,250.00" in prompt
    assert "[ind:sma_200] SMA 200: 299.50" in prompt
    assert "Upbeat chatter" in prompt
    assert "failed" not in prompt  # failed sentiment is not shown
    assert "untrusted" in prompt
    assert "Previous final decisions" in prompt
    assert "None." in prompt

    assert len(await repos.decisions.get_decisions_by_run(run_id)) == 6
    stored = {a.symbol: a for a in await repos.decisions.get_aggregated_by_run(run_id)}
    assert set(stored) == {"AAPL", "MSFT", "NVDA"}
    instances = await repos.runs.get_agent_instances(run_id)
    assert sorted(i.agent_id for i in instances) == [
        "trend_follower",
        "value_investor",
        "value_investor",
    ]
    assert len(await repos.llm_calls.get_by_run(run_id)) == 6

    # the next run sees this run's final decision, with the price move since
    later_run = await new_run(NOW + timedelta(days=2))
    llm2 = FakeLLMClient(default=llm_reply)
    ctx2 = PipelineContext(
        run_id=later_run,
        pipeline_name="long_term_stocks",
        mode=RunMode.DRY_RUN,
        universe=["AAPL"],
        as_of=NOW + timedelta(days=2),
    )
    await build(repos, store, llm2).run(ctx2)
    later_prompt = llm2.requests[0].messages[0].content
    assert f"[hist:{aapl.id}]" in later_prompt
    assert re.search(r"buy at 399\.00; price change since \+0\.00%", later_prompt)


async def test_llm_failure_means_hold(
    repos: Repositories, store: ConfigStore, new_run: NewRun, make_bars: MakeBars
) -> None:
    await repos.bars.upsert(make_bars("AAPL", [100 + i for i in range(60)]))
    run_id = await new_run()
    llm = FakeLLMClient(default="not json")
    ctx = PipelineContext(
        run_id=run_id,
        pipeline_name="long_term_stocks",
        mode=RunMode.DRY_RUN,
        universe=["AAPL"],
        as_of=NOW,
    )
    ctx = await build(repos, store, llm).run(ctx)
    assert ctx.aggregated_decisions["AAPL"].final_action is Action.HOLD
    assert all(d.error is not None and d.action is Action.HOLD for d in ctx.decisions["AAPL"])


def test_entry_points() -> None:
    assert STAGES.get("decision") is build_decision_stage
    assert AGENTS.get("decision") is DecisionAgent


def test_repo_pipeline_decision_options() -> None:
    from pathlib import Path

    from quant_decision import AggregationMethod, DecisionOptions

    repo = ConfigStore(Path(__file__).resolve().parents[3] / "configs", env={"IBKR_ACCOUNT": "x"})
    stage = repo.pipeline("long_term_stocks").stage("decision")
    assert stage is not None
    options = stage.options(DecisionOptions)
    assert options.aggregation.method is AggregationMethod.WEIGHTED_VOTE
    assert options.aggregation.min_confidence == 0.6
    assert options.bars_lookback == 260


# ------------------------------------------------------------------ choosing the model


async def test_model_chosen_when_instantiating_in_code(
    store: ConfigStore, make_bars: MakeBars
) -> None:
    bars = make_bars("AAPL", [100 + i for i in range(60)])
    context = SymbolContext(
        symbol="AAPL",
        as_of=NOW,
        bars=bars,
        indicators=compute_indicators(bars),
        ledger=LedgerState(pipeline_name="p", max_capital=D(1000), cash=D(1000)),
        nav=D(1000),
    )
    deepseek = FakeLLMClient(default=llm_reply)
    agent = DecisionAgent(
        store.agent("value_investor"),  # the config itself names no model
        deepseek,
        model=LLMModelConfig(provider="deepseek", name="deepseek-chat", max_tokens=800),
        prompt_root=store.agents_dir,
    )
    decision = await agent.decide(context, run_id=uuid4())
    assert decision.action is Action.HOLD
    [request] = deepseek.requests
    assert (request.model, request.max_tokens) == ("deepseek-chat", 800)

    with pytest.raises(ValueError, match="no model given"):
        DecisionAgent(store.agent("value_investor"), deepseek, prompt_root=store.agents_dir)


async def test_each_pipeline_agent_reference_picks_its_model(
    repos: Repositories, store: ConfigStore, new_run: NewRun, make_bars: MakeBars
) -> None:
    await repos.bars.upsert(make_bars("AAPL", [100 + i for i in range(60)]))
    claude, deepseek = FakeLLMClient(default=llm_reply), FakeLLMClient(default=llm_reply)
    pool = LLMClientPool({}, env={})
    pool.set("anthropic", claude)
    pool.set("deepseek", deepseek)
    config = StageConfig.model_validate(
        {
            "type": "decision",
            "agents": [
                {"agent": "value_investor", "model": CLAUDE},
                {
                    "agent": "value_investor",
                    "model": {"provider": "deepseek", "name": "deepseek-reasoner"},
                },
                {
                    "agent": "trend_follower",
                    "model": {"provider": "deepseek", "name": "deepseek-chat", "effort": "low"},
                },
            ],
        }
    )
    services = Services(repos=repos, config_store=store, llm=pool, pipeline=pipeline_config())
    run_id = await new_run()
    ctx = PipelineContext(
        run_id=run_id,
        pipeline_name="long_term_stocks",
        mode=RunMode.DRY_RUN,
        universe=["AAPL"],
        as_of=NOW,
    )
    await build_decision_stage(config, services).run(ctx)

    assert [r.model for r in claude.requests] == ["claude-opus-5"]
    assert sorted((r.model, r.effort) for r in deepseek.requests) == [
        ("deepseek-chat", "low"),
        ("deepseek-reasoner", None),
    ]
    instances = await repos.runs.get_agent_instances(run_id)
    assert sorted((i.agent_id, i.provider, i.model) for i in instances) == [
        ("trend_follower", "deepseek", "deepseek-chat"),
        ("value_investor", "anthropic", "claude-opus-5"),
        ("value_investor", "deepseek", "deepseek-reasoner"),
    ]
