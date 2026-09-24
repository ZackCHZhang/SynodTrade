from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from quant_core.llm import FakeLLMClient, LLMMessage, LLMRequest, complete_structured
from quant_core.models import (
    Action,
    AggregatedDecision,
    Decision,
    RiskVerdict,
    RuleHit,
    SentimentItem,
    SentimentResult,
    Verdict,
    Vote,
)
from quant_database import AgentInstance, Repositories, RunStatus

MakeRun = Callable[..., Awaitable[UUID]]
T0 = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)


# ------------------------------------------------------------------ runs


async def test_run_lifecycle(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    run = await repos.runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.RUNNING
    assert run.started_at == T0
    assert [r.run_id for r in await repos.runs.running_runs("long_term_stocks")] == [run_id]

    await repos.runs.finish_run(run_id, RunStatus.SUCCEEDED, summary={"orders": 2})
    run = await repos.runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.SUCCEEDED
    assert run.ended_at is not None
    assert run.summary == {"orders": 2}
    assert await repos.runs.running_runs("long_term_stocks") == []
    assert await repos.runs.get_run(uuid4()) is None


async def test_finish_run_validation(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    with pytest.raises(ValueError, match="final status"):
        await repos.runs.finish_run(run_id, RunStatus.RUNNING)
    with pytest.raises(KeyError, match="unknown run"):
        await repos.runs.finish_run(uuid4(), RunStatus.FAILED, error="boom")


async def test_agent_instances(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    instances = [
        AgentInstance(
            instance_id=uuid4(),
            run_id=run_id,
            agent_id="value_investor",
            agent_type="decision",
            persona="p",
            prompt_version="v1",
            provider="deepseek",
            model="deepseek-chat",
            config={"weight": 1.0},
        )
        for _ in range(2)
    ]
    await repos.runs.register_agent_instances(instances)
    got = await repos.runs.get_agent_instances(run_id)
    assert {i.instance_id for i in got} == {i.instance_id for i in instances}
    assert got[0].provider == "deepseek"


# ------------------------------------------------------------------ LLM audit


class Out(BaseModel):
    action: str


async def test_llm_calls_are_recorded_through_structured_completion(
    repos: Repositories, make_run: MakeRun
) -> None:
    run_id, instance_id = await make_run(), uuid4()
    fake = FakeLLMClient(["not json", '{"action": "buy"}'])
    req = LLMRequest(model="m", messages=[LLMMessage(role="user", content="q")], max_tokens=50)
    result = await complete_structured(
        fake,
        req,
        Out,
        recorder=repos.llm_calls,
        run_id=run_id,
        instance_id=instance_id,
        agent_id="a",
    )
    assert result.ok

    calls = await repos.llm_calls.get_by_run(run_id)
    assert [c.attempt for c in calls] == [1, 2]
    assert calls[0].error is not None
    assert calls[1].response_text == '{"action": "buy"}'
    assert calls[1].usage is not None
    assert calls[1].request["messages"][0]["content"] == "q"
    assert calls[1].raw_response == {"fake": True, "text": '{"action": "buy"}'}
    assert calls[1].instance_id == instance_id
    assert [c.id for c in await repos.llm_calls.get_many(result.call_ids)] == result.call_ids
    assert await repos.llm_calls.get_many([]) == []


async def test_llm_call_without_usage(repos: Repositories) -> None:
    fake = FakeLLMClient([RuntimeError("never raised")])
    del fake  # transport failures are recorded without usage:
    from quant_core.llm import LLMCallRecord

    record = LLMCallRecord(provider="p", model="m", attempt=1, request={}, error="HTTP 401")
    await repos.llm_calls.record(record)
    [got] = await repos.llm_calls.get_many([record.id])
    assert got.usage is None
    assert got.error == "HTTP 401"
    assert got.run_id is None


# ------------------------------------------------------------------ sentiment


def item(ext: str, symbol: str = "AAPL", score: int = 0, minutes: int = 0) -> SentimentItem:
    return SentimentItem(
        source="reddit",
        external_id=ext,
        symbol=symbol,
        text=f"post {ext}",
        created_at=T0 + timedelta(minutes=minutes),
        score=score,
        metadata={"subreddit": "stocks"},
    )


async def test_sentiment_items_deduplicate(repos: Repositories) -> None:
    assert await repos.sentiment.add_items([item("a"), item("b"), item("a", symbol="MSFT")]) == 3
    assert await repos.sentiment.add_items([item("a"), item("c")]) == 1
    assert await repos.sentiment.add_items([]) == 0


async def test_get_items_order_limit_and_window(repos: Repositories) -> None:
    await repos.sentiment.add_items(
        [
            item("old", minutes=-600),
            item("a", score=5, minutes=1),
            item("b", score=50, minutes=2),
            item("c", score=1, minutes=3),
            item("future", minutes=120),
        ]
    )
    since, as_of = T0 - timedelta(hours=1), T0 + timedelta(hours=1)
    recent = await repos.sentiment.get_items("aapl", since, as_of=as_of)
    assert [i.external_id for i in recent] == ["c", "b", "a"]
    top = await repos.sentiment.get_items("AAPL", since, as_of=as_of, limit=2, order_by="score")
    assert [i.external_id for i in top] == ["b", "a"]
    assert top[0].metadata == {"subreddit": "stocks"}


async def test_sentiment_results(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    result = SentimentResult(
        run_id=run_id,
        instance_id=uuid4(),
        agent_id="retail_mood",
        prompt_version="v1",
        symbol="AAPL",
        sentiment=-0.4,
        confidence=0.7,
        summary="bearish chatter",
        key_events=["earnings miss"],
        item_ids=["a", "b"],
        llm_call_ids=[uuid4()],
        created_at=T0,
    )
    await repos.sentiment.add_results([result])
    assert await repos.sentiment.get_results_by_run(run_id) == [result]
    assert await repos.sentiment.get_sentiment("AAPL", T0 - timedelta(days=1), as_of=T0) == [result]
    assert (
        await repos.sentiment.get_sentiment(
            "AAPL", T0 - timedelta(days=1), as_of=T0 - timedelta(seconds=1)
        )
        == []
    )


# ------------------------------------------------------------------ decisions and risk


async def test_decisions_and_aggregates(repos: Repositories, make_run: MakeRun) -> None:
    run_id = await make_run()
    instances = [uuid4(), uuid4()]
    decisions = [
        Decision(
            run_id=run_id,
            instance_id=inst,
            agent_id="value_investor",
            prompt_version="v1",
            symbol="AAPL",
            action=Action.BUY,
            confidence=0.8,
            reasoning="cheap",
            referenced_data_ids=["bar:2026-09-23"],
            llm_call_ids=[uuid4()],
            created_at=T0,
        )
        for inst in instances
    ]
    await repos.decisions.add_decisions(decisions)
    got = await repos.decisions.get_decisions_by_run(run_id)
    assert sorted(got, key=lambda d: str(d.id)) == sorted(decisions, key=lambda d: str(d.id))
    assert got[0].action is Action.BUY

    agg = AggregatedDecision(
        run_id=run_id,
        symbol="AAPL",
        final_action=Action.BUY,
        method="weighted_vote",
        score=0.15,
        created_at=T0,
        votes=[
            Vote(
                instance_id=i,
                agent_id="value_investor",
                action=Action.BUY,
                confidence=0.8,
                weight=1.0,
            )
            for i in instances
        ],
    )
    await repos.decisions.add_aggregated([agg])
    assert await repos.decisions.get_aggregated_by_run(run_id) == [agg]
    assert await repos.decisions.get_recent_aggregated("AAPL", 5, as_of=T0) == [agg]
    assert await repos.decisions.get_recent_aggregated("AAPL", 5, as_of=T0 - timedelta(1)) == []

    verdicts = [
        RiskVerdict(
            run_id=run_id,
            symbol="AAPL",
            source="rules",
            decision_id=agg.id,
            verdict=Verdict.REDUCE,
            original_action=Action.BUY,
            adjusted_action=Action.HOLD,
            reason="daily loss limit",
            rule_hits=[
                RuleHit(
                    rule="daily_loss", message="-3% today", blocking=True, details={"pnl_pct": -3.1}
                )
            ],
            created_at=T0,
        ),
        RiskVerdict(
            run_id=run_id,
            symbol="AAPL",
            source="conservative_risk_officer",
            instance_id=uuid4(),
            decision_id=agg.id,
            verdict=Verdict.APPROVE,
            original_action=Action.HOLD,
            adjusted_action=Action.HOLD,
            reason="ok",
            llm_call_ids=[uuid4()],
            created_at=T0 + timedelta(seconds=1),
        ),
    ]
    await repos.risk.add_assessments(verdicts)
    assert await repos.risk.get_by_run(run_id) == verdicts
