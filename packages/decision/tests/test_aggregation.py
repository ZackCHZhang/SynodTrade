from uuid import uuid4

import pytest

from quant_core.models import Action, Decision
from quant_decision import AggregationMethod, AggregationOptions, aggregate, effective_action

RUN = uuid4()
A = Action


def vote(action: Action, confidence: float = 0.8, *, error: str | None = None) -> Decision:
    return Decision(
        run_id=RUN,
        instance_id=uuid4(),
        agent_id="a",
        prompt_version="v1",
        symbol="AAPL",
        action=action,
        confidence=confidence,
        reasoning="r",
        error=error,
    )


def agg(
    votes: list[tuple[Decision, float]], method: str = "weighted_vote", min_confidence: float = 0.0
) -> Action:
    opts = AggregationOptions(method=AggregationMethod(method), min_confidence=min_confidence)
    return aggregate(RUN, "AAPL", votes, opts).final_action


def test_effective_action() -> None:
    assert effective_action(vote(A.BUY, 0.5), 0.6) is A.HOLD
    assert effective_action(vote(A.BUY, 0.6), 0.6) is A.BUY
    assert effective_action(vote(A.BUY, 0.9, error="x"), 0.0) is A.HOLD


# ------------------------------------------------------------------ weighted_vote


@pytest.mark.parametrize(
    ("votes", "expected"),
    [
        ([(vote(A.STRONG_BUY), 1.0)], A.STRONG_BUY),
        ([(vote(A.STRONG_BUY), 1.0), (vote(A.BUY), 1.0)], A.BUY),  # 0.225 -> tie -> BUY
        ([(vote(A.STRONG_BUY, 0.9), 1.0), (vote(A.HOLD, 0.9), 1.0)], A.BUY),  # 0.15
        ([(vote(A.BUY), 1.0), (vote(A.SELL), 1.0)], A.HOLD),  # cancel out
        (
            [(vote(A.STRONG_SELL, 1.0), 2.0), (vote(A.BUY, 0.5), 1.0)],
            A.SELL,
        ),  # -0.21 is nearer -0.15
        ([(vote(A.BUY, 1.0), 1.0), (vote(A.SELL, 0.2), 1.0)], A.BUY),  # confidence weighs
        ([], A.HOLD),
    ],
)
def test_weighted_vote(votes: list[tuple[Decision, float]], expected: Action) -> None:
    assert agg(votes) is expected


def test_weighted_vote_min_confidence_and_failures() -> None:
    votes = [(vote(A.STRONG_BUY, 0.5), 1.0), (vote(A.SELL, 0.7), 1.0)]
    # the low-confidence buy becomes HOLD -> score -0.15*0.7/1.2 = -0.0875 -> SELL
    assert agg(votes, min_confidence=0.6) is A.SELL
    failed = [(vote(A.HOLD, 0.0, error="llm down"), 1.0), (vote(A.HOLD, 0.0, error="x"), 1.0)]
    result = aggregate(RUN, "AAPL", failed, AggregationOptions())
    assert result.final_action is A.HOLD
    assert result.score == 0.0


def test_aggregated_record() -> None:
    votes = [(vote(A.BUY, 0.8), 1.0), (vote(A.STRONG_BUY, 0.6), 0.8)]
    result = aggregate(RUN, "AAPL", votes, AggregationOptions(min_confidence=0.7))
    assert result.method == "weighted_vote(min_confidence=0.7)"
    assert [v.action for v in result.votes] == [A.BUY, A.STRONG_BUY]  # original actions kept
    assert [v.weight for v in result.votes] == [1.0, 0.8]
    assert result.score == pytest.approx(0.15 * 0.8 / (0.8 + 0.48))


# ------------------------------------------------------------------ majority


@pytest.mark.parametrize(
    ("votes", "expected"),
    [
        ([(vote(A.BUY), 1.0), (vote(A.BUY), 1.0), (vote(A.SELL), 1.0)], A.BUY),
        ([(vote(A.STRONG_BUY), 1.0), (vote(A.STRONG_BUY), 1.0), (vote(A.BUY), 1.0)], A.STRONG_BUY),
        ([(vote(A.STRONG_BUY), 1.0), (vote(A.BUY), 1.0), (vote(A.HOLD), 1.0)], A.BUY),  # tie
        ([(vote(A.BUY), 1.0), (vote(A.SELL), 1.0)], A.HOLD),  # 50% is not a majority
        ([(vote(A.BUY), 1.0), (vote(A.HOLD), 1.0), (vote(A.SELL), 1.0)], A.HOLD),
        ([(vote(A.SELL), 3.0), (vote(A.BUY), 1.0), (vote(A.BUY), 1.0)], A.SELL),  # by weight
        ([(vote(A.STRONG_SELL), 1.0), (vote(A.STRONG_SELL), 1.0)], A.STRONG_SELL),
        ([], A.HOLD),
    ],
)
def test_majority(votes: list[tuple[Decision, float]], expected: Action) -> None:
    assert agg(votes, "majority") is expected


def test_majority_counts_failed_agents_as_hold() -> None:
    votes = [(vote(A.BUY), 1.0), (vote(A.HOLD, 0.0, error="down"), 1.0)]
    assert agg(votes, "majority") is A.HOLD


# ------------------------------------------------------------------ unanimous


@pytest.mark.parametrize(
    ("votes", "expected"),
    [
        ([(vote(A.STRONG_BUY), 1.0), (vote(A.BUY), 1.0)], A.BUY),  # least aggressive
        ([(vote(A.STRONG_SELL), 1.0), (vote(A.STRONG_SELL), 1.0)], A.STRONG_SELL),
        ([(vote(A.BUY), 1.0), (vote(A.HOLD), 1.0)], A.HOLD),
        ([(vote(A.BUY), 1.0), (vote(A.SELL), 1.0)], A.HOLD),
        ([(vote(A.HOLD), 1.0)], A.HOLD),
        ([], A.HOLD),
    ],
)
def test_unanimous(votes: list[tuple[Decision, float]], expected: Action) -> None:
    assert agg(votes, "unanimous") is expected


def test_unanimous_respects_min_confidence() -> None:
    votes = [(vote(A.BUY, 0.9), 1.0), (vote(A.BUY, 0.4), 1.0)]
    assert agg(votes, "unanimous", min_confidence=0.5) is A.HOLD


def test_options_validation() -> None:
    with pytest.raises(ValueError, match="method"):
        AggregationOptions.model_validate({"method": "average"})
    with pytest.raises(ValueError, match="less than or equal"):
        AggregationOptions(min_confidence=1.5)


def test_hold_weight_lets_directional_votes_through() -> None:
    """Two specialists buy, four say hold: equal weights keep HOLD; half-weight holds let the
    buy through (the case seen in paper runs: NVDA scored +0.045 < +0.075)."""
    votes = [(vote(A.BUY, 0.6), 1.0), (vote(A.BUY, 0.6), 1.0)] + [
        (vote(A.HOLD, 0.6), 1.0) for _ in range(3)
    ]
    full = AggregationOptions(min_confidence=0.5)
    half = AggregationOptions(min_confidence=0.5, hold_weight=0.5)
    assert aggregate(RUN, "AAPL", votes, full).final_action is A.HOLD
    result = aggregate(RUN, "AAPL", votes, half)
    assert result.final_action is A.BUY
    assert result.method == "weighted_vote(min_confidence=0.5, hold_weight=0.5)"
    assert [v.weight for v in result.votes] == [1.0] * 5  # stored votes keep agent weights
    # majority: buys 2 vs holds 3 x 0.5 -> buys hold more than half of the weight
    maj = AggregationOptions(method=AggregationMethod.MAJORITY, hold_weight=0.5)
    assert aggregate(RUN, "AAPL", votes, maj).final_action is A.BUY
    # all holds stay HOLD even with weight 0 (no division by zero)
    zero = AggregationOptions(hold_weight=0.0)
    assert aggregate(RUN, "AAPL", [(vote(A.HOLD), 1.0)], zero).final_action is A.HOLD
