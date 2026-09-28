"""Combine several agents' decisions on one symbol into a final five-tier action.

Before any method runs, a vote counts as HOLD if its confidence is below `min_confidence`
or its agent failed (fell back to HOLD). Methods:

- weighted_vote: average of tier weights, weighted by agent weight x confidence, mapped
  back to the nearest tier (ties toward HOLD). Zero total weight -> HOLD.
- majority: one direction (buy / hold / sell) must hold strictly more than half of the
  total agent weight; the tier is the weighted mean of that side's tiers, rounded toward
  HOLD on ties. Otherwise HOLD.
- unanimous: every vote must point the same (non-HOLD) direction; the least aggressive of
  their tiers is taken. Otherwise HOLD.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from quant_core.models import Action, AggregatedDecision, Decision, Vote
from quant_core.timeutil import utcnow


class AggregationMethod(StrEnum):
    WEIGHTED_VOTE = "weighted_vote"
    MAJORITY = "majority"
    UNANIMOUS = "unanimous"


class AggregationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: AggregationMethod = AggregationMethod.WEIGHTED_VOTE
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


def effective_action(decision: Decision, min_confidence: float) -> Action:
    if decision.error is not None or decision.confidence < min_confidence:
        return Action.HOLD
    return decision.action


def _nearest_in_direction(direction: int, mean_abs_weight: float) -> Action:
    tiers = [a for a in Action if a.direction == direction]
    return min(tiers, key=lambda a: (abs(float(abs(a.weight)) - mean_abs_weight), abs(a.weight)))


def aggregate(
    run_id: UUID,
    symbol: str,
    votes: Sequence[tuple[Decision, float]],
    options: AggregationOptions,
    created_at: datetime | None = None,
) -> AggregatedDecision:
    """`votes` are (decision, agent weight) pairs for one symbol. `created_at` should be
    the run's `as_of`, so later runs "as of" a moment see exactly what existed then."""
    effective = [(effective_action(d, options.min_confidence), d, w) for d, w in votes]

    if options.method is AggregationMethod.WEIGHTED_VOTE:
        total = sum(w * d.confidence for _, d, w in effective)
        score = (
            sum(w * d.confidence * float(a.weight) for a, d, w in effective) / total
            if total > 0
            else 0.0
        )
        final = Action.nearest(Decimal(str(round(score, 10))))
    else:
        total_weight = sum(w for _, _, w in effective)
        score = (
            sum(w * float(a.weight) for a, _, w in effective) / total_weight
            if total_weight > 0
            else 0.0
        )
        final = Action.HOLD
        if options.method is AggregationMethod.MAJORITY:
            for direction in (1, -1):
                side = [(a, w) for a, _, w in effective if a.direction == direction]
                side_weight = sum(w for _, w in side)
                if side_weight > total_weight / 2:
                    mean = sum(float(abs(a.weight)) * w for a, w in side) / side_weight
                    final = _nearest_in_direction(direction, mean)
        else:  # unanimous
            directions = {a.direction for a, _, _ in effective}
            if len(directions) == 1 and 0 not in directions:
                final = min((a for a, _, _ in effective), key=lambda a: abs(a.weight))

    return AggregatedDecision(
        created_at=created_at or utcnow(),
        run_id=run_id,
        symbol=symbol,
        final_action=final,
        method=f"{options.method.value}(min_confidence={options.min_confidence})",
        score=score,
        votes=[
            Vote(
                instance_id=d.instance_id,
                agent_id=d.agent_id,
                action=d.action,
                confidence=d.confidence,
                weight=w,
            )
            for d, w in votes
        ],
    )
