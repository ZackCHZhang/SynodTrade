"""Decision history per strategy, what became of each decision, stored sentiment lookup."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from quant_core.models import (
    Action,
    AggregatedDecision,
    Fill,
    OrderIntent,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    RiskVerdict,
    SentimentResult,
    Verdict,
)
from quant_database import Repositories

MakeRun = Callable[..., Awaitable[UUID]]
T0 = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)
D = Decimal


def agg(
    run_id: UUID, at: datetime, action: Action = Action.BUY, method: str = "m"
) -> AggregatedDecision:
    return AggregatedDecision(
        run_id=run_id,
        symbol="AAPL",
        final_action=action,
        method=method,
        score=0.3,
        votes=[],
        created_at=at,
    )


async def test_history_is_per_pipeline(repos: Repositories, make_run: MakeRun) -> None:
    mine = await make_run("long_term_stocks", T0)
    other = await make_run("demo_all_modules", T0)
    later = await make_run("long_term_stocks", T0 + timedelta(days=1))
    await repos.decisions.add_aggregated(
        [
            agg(mine, T0),
            agg(other, T0 + timedelta(hours=1)),
            agg(later, T0 + timedelta(days=1), Action.HOLD, "insufficient_data"),
        ]
    )
    everything = await repos.decisions.get_recent_aggregated("AAPL", 10, T0 + timedelta(days=2))
    assert len(everything) == 3
    own = await repos.decisions.get_recent_aggregated(
        "aapl",
        10,
        T0 + timedelta(days=2),
        pipeline_name="long_term_stocks",
        exclude_methods=("insufficient_data",),
    )
    assert [d.run_id for d in own] == [mine]


async def test_outcomes(repos: Repositories, make_run: MakeRun) -> None:
    filled_run = await make_run()
    rejected_run = await make_run()
    unassessed_run = await make_run()
    filled, rejected, unassessed = (
        agg(filled_run, T0),
        agg(rejected_run, T0, Action.STRONG_BUY),
        agg(unassessed_run, T0),
    )
    await repos.decisions.add_aggregated([filled, rejected, unassessed])
    await repos.risk.add_assessments(
        [
            RiskVerdict(
                run_id=filled_run,
                symbol="AAPL",
                source="final",
                decision_id=filled.id,
                verdict=Verdict.APPROVE,
                original_action=Action.BUY,
                adjusted_action=Action.BUY,
                reason="ok",
            ),
            RiskVerdict(
                run_id=rejected_run,
                symbol="AAPL",
                source="rules",  # not the final verdict: ignored
                decision_id=rejected.id,
                verdict=Verdict.APPROVE,
                original_action=Action.STRONG_BUY,
                adjusted_action=Action.STRONG_BUY,
                reason="rules passed",
            ),
            RiskVerdict(
                run_id=rejected_run,
                symbol="AAPL",
                source="final",
                decision_id=rejected.id,
                verdict=Verdict.REJECT,
                original_action=Action.STRONG_BUY,
                adjusted_action=Action.HOLD,
                reason="too large",
            ),
        ]
    )
    intent = OrderIntent(
        client_order_id="c1",
        run_id=filled_run,
        pipeline_name="long_term_stocks",
        symbol="AAPL",
        action=Action.BUY,
        side=OrderSide.BUY,
        quantity=D(3),
        order_type=OrderType.LIMIT,
        limit_price=D(100),
        estimated_notional=D(300),
    )
    await repos.orders.create(intent, created_at=T0)
    await repos.orders.apply_result(
        OrderResult(
            client_order_id="c1",
            status=OrderStatus.FILLED,
            filled_qty=D(3),
            avg_fill_price=D("99.5"),
            fills=[
                Fill(
                    exec_id="e1",
                    client_order_id="c1",
                    symbol="AAPL",
                    side=OrderSide.BUY,
                    qty=D(3),
                    price=D("99.5"),
                    ts=T0,
                )
            ],
        )
    )
    out = await repos.decisions.get_outcomes([filled, rejected, unassessed])
    assert out[filled.id].risk_action is Action.BUY
    assert out[filled.id].order_status == "filled"
    assert out[filled.id].filled_qty == D(3)
    assert out[filled.id].avg_fill_price == D("99.5")
    assert out[rejected.id].risk_action is Action.HOLD
    assert out[rejected.id].risk_reason == "too large"
    assert out[rejected.id].order_status is None
    assert out[unassessed.id].risk_action is None
    assert await repos.decisions.get_outcomes([]) == {}


async def test_latest_sentiment_per_agent(repos: Repositories, make_run: MakeRun) -> None:
    run1 = await make_run()
    run2 = await make_run()

    def result(
        run: UUID, agent: str, value: float, at: datetime, error: str | None = None
    ) -> SentimentResult:
        return SentimentResult(
            run_id=run,
            instance_id=uuid4(),
            agent_id=agent,
            prompt_version="v1",
            symbol="AAPL",
            sentiment=value,
            confidence=0.5,
            summary=f"{agent} {value}",
            created_at=at,
            error=error,
        )

    await repos.sentiment.add_results(
        [
            result(run1, "retail_mood", 0.1, T0 - timedelta(hours=10)),
            result(run2, "retail_mood", 0.4, T0 - timedelta(hours=2)),
            result(run2, "event_extractor", 0.0, T0 - timedelta(hours=2), error="down"),
            result(run1, "event_extractor", -0.2, T0 - timedelta(hours=10)),
            result(run2, "retail_mood", 0.9, T0 + timedelta(hours=1)),  # after as_of
            result(run1, "retail_mood", 0.7, T0 - timedelta(hours=100)),  # too old
        ]
    )
    latest = await repos.sentiment.get_latest_results("AAPL", T0 - timedelta(hours=48), T0)
    assert [(r.agent_id, r.sentiment) for r in latest] == [
        ("event_extractor", -0.2),  # the newer one failed: the last good one is used
        ("retail_mood", 0.4),
    ]
