"""The decision prompt gets everything earlier stages and runs produced."""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from quant_core.config import ConfigStore, PipelineConfig, StageConfig
from quant_core.llm import FakeLLMClient, LLMClientPool, LLMRequest
from quant_core.models import (
    Action,
    AggregatedDecision,
    Bar,
    Fundamentals,
    PipelineContext,
    Quote,
    RunMode,
    SelectionPick,
    SelectionResult,
    SentimentResult,
    StockSelection,
)
from quant_core.services import Services
from quant_database import PipelineRun, Repositories
from quant_decision import build_decision_stage

D = Decimal
NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)
NewRun = Callable[..., Awaitable[UUID]]
MakeBars = Callable[..., list[Bar]]
CLAUDE = {"provider": "anthropic", "name": "claude-opus-5"}


def reply(request: LLMRequest) -> str:
    prompt = request.messages[0].content
    cited = [i for i in ("quote:AAPL", "fund:pe", "mkt:SPY", "sel:AAPL") if f"[{i}]" in prompt]
    return json.dumps(
        {"action": "hold", "confidence": 0.5, "reasoning": "r", "referenced_data_ids": cited}
    )


async def other_pipeline_run(repos: Repositories, at: datetime) -> UUID:
    run_id = uuid4()
    await repos.runs.start_run(
        PipelineRun(
            run_id=run_id,
            pipeline_name="demo_all_modules",
            mode=RunMode.DRY_RUN,
            config_hash="0" * 64,
            config={},
            as_of=at,
            started_at=at,
        )
    )
    return run_id


def build(repos: Repositories, store: ConfigStore, llm: FakeLLMClient, **options: object):  # type: ignore[no-untyped-def]
    pool = LLMClientPool({}, env={})
    pool.set("anthropic", llm)
    pipeline = PipelineConfig.model_validate(
        {
            "name": "long_term_stocks",
            "account": "ibkr_main",
            "universe": ["AAPL"],
            "benchmark": "SPY",
            "budget": {"max_capital": 5000},
            "stages": [{"type": "decision"}],
        }
    )
    config = StageConfig.model_validate(
        {
            "type": "decision",
            "agents": [{"agent": "value_investor", "count": 1, "model": CLAUDE}],
            **options,
        }
    )
    services = Services(repos=repos, config_store=store, llm=pool, pipeline=pipeline)
    return build_decision_stage(config, services)


async def test_prompt_uses_every_upstream_output(
    repos: Repositories, store: ConfigStore, new_run: NewRun, make_bars: MakeBars
) -> None:
    await repos.bars.upsert(make_bars("AAPL", [100 + i * 0.5 for i in range(300)]))
    await repos.bars.upsert(make_bars("SPY", [400 + i * 0.2 for i in range(300)]))
    await repos.quotes.add(
        [Quote(symbol="AAPL", ts=NOW - timedelta(minutes=5), bid=D("251.00"), ask=D("251.20"))]
    )
    await repos.fundamentals.add(
        [
            Fundamentals(
                symbol="AAPL",
                as_of=NOW - timedelta(hours=3),
                name="Apple Inc.",
                industry="Electronic Computers",
                period_end=date(2026, 6, 27),
                shares_outstanding=100.0,
                eps_diluted=10.0,
                revenue=1000.0,
                revenue_prev=900.0,
            )
        ]
    )
    earlier = await new_run(NOW - timedelta(days=1))
    await repos.selection.add_selection(
        StockSelection(
            run_id=earlier,
            pipeline_name="long_term_stocks",
            method="weighted_score",
            candidates=["AAPL", "MSFT"],
            selected=["AAPL"],
            scores={"AAPL": 0.7},
            created_at=NOW - timedelta(days=1),
        )
    )
    await repos.selection.add_results(
        [
            SelectionResult(
                run_id=earlier,
                instance_id=uuid4(),
                agent_id="momentum_screener",
                prompt_version="v1",
                pipeline_name="long_term_stocks",
                picks=[SelectionPick(symbol="AAPL", score=0.8, reason="leader near highs")],
                created_at=NOW - timedelta(days=1),
            )
        ]
    )
    await repos.sentiment.add_results(
        [
            SentimentResult(
                run_id=earlier,
                instance_id=uuid4(),
                agent_id="retail_mood",
                prompt_version="v1",
                symbol="AAPL",
                sentiment=0.3,
                confidence=0.6,
                summary="cautiously upbeat",
                key_events=["product launch"],
                created_at=NOW - timedelta(hours=5),
            )
        ]
    )
    own = AggregatedDecision(
        run_id=earlier,
        symbol="AAPL",
        final_action=Action.BUY,
        method="weighted_vote",
        score=0.3,
        votes=[],
        created_at=NOW - timedelta(days=1),
    )
    foreign = own.model_copy(
        update={"id": uuid4(), "run_id": await other_pipeline_run(repos, NOW - timedelta(hours=2))}
    )
    await repos.decisions.add_aggregated([own, foreign])

    llm = FakeLLMClient(default=reply)
    ctx = PipelineContext(
        run_id=await new_run(),
        pipeline_name="long_term_stocks",
        mode=RunMode.DRY_RUN,
        universe=["AAPL"],
        as_of=NOW,
    )
    ctx = await build(repos, store, llm).run(ctx)
    prompt = llm.requests[0].messages[0].content

    assert "[quote:AAPL] 251.10 (bid 251.00, ask 251.20)" in prompt
    assert "[mkt:SPY] Benchmark SPY: above its 200-day average" in prompt
    assert "AAPL against SPY: beta 1y" in prompt
    assert "[fund:pe] P/E (TTM diluted EPS): 25.1" in prompt  # 251.10 / 10
    assert "Apple Inc., from sec_edgar filings" in prompt
    assert "[sel:AAPL] Selection of 2026-09-23: selected, rank 1 of 1" in prompt
    assert "momentum_screener (score 0.80): leader near highs" in prompt
    assert "## Sentiment from earlier runs (newest per analyst)" in prompt
    assert "retail_mood (5 h ago): sentiment +0.30" in prompt
    assert "Events: product launch." in prompt
    assert f"[hist:{own.id}]" in prompt
    assert f"[hist:{foreign.id}]" not in prompt  # another strategy's decision
    assert "outcome: not executed, no risk review recorded" in prompt
    assert ctx.decisions["AAPL"][0].referenced_data_ids == [
        "quote:AAPL",
        "fund:pe",
        "mkt:SPY",
        "sel:AAPL",
    ]


async def test_stale_quote_and_disabled_fallbacks(
    repos: Repositories, store: ConfigStore, new_run: NewRun, make_bars: MakeBars
) -> None:
    await repos.bars.upsert(make_bars("AAPL", [100 + i * 0.5 for i in range(300)]))
    await repos.quotes.add([Quote(symbol="AAPL", ts=NOW - timedelta(hours=3), last=D(250))])
    earlier = await new_run(NOW - timedelta(days=1))
    await repos.sentiment.add_results(
        [
            SentimentResult(
                run_id=earlier,
                instance_id=uuid4(),
                agent_id="retail_mood",
                prompt_version="v1",
                symbol="AAPL",
                sentiment=0.3,
                confidence=0.6,
                summary="old news",
                created_at=NOW - timedelta(hours=5),
            )
        ]
    )
    llm = FakeLLMClient(default=reply)
    ctx = PipelineContext(
        run_id=await new_run(),
        pipeline_name="long_term_stocks",
        mode=RunMode.DRY_RUN,
        universe=["AAPL"],
        as_of=NOW,
    )
    await build(repos, store, llm, stored_sentiment_hours=0, fundamentals=False).run(ctx)
    prompt = llm.requests[0].messages[0].content
    assert "No fresh quote" in prompt
    assert "old news" not in prompt
    assert "No sentiment data is available." in prompt
    assert "No market benchmark data." in prompt  # SPY has no bars
    assert "No fundamental data" in prompt
    assert "has no stock selection" in prompt
