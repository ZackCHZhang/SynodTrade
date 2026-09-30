"""Combine several selection agents' picks into one ranked selection.

Only agents that answered count (a failed agent's empty fallback is not a vote against every
candidate). For each candidate, with w = agent weight and s = the agent's score for it
(0 when the agent did not pick it):

- weighted_score: sum(w * s) / sum(w) — conviction-weighted;
- approval: sum(w * [picked]) / sum(w) — the weighted share of agents that picked it.

Candidates are ranked by that score (ties: the other measure, then symbol), and the best
`top_n` with a score of at least `min_score` (and above 0) are selected.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from quant_core.models import SelectionResult


class SelectionMethod(StrEnum):
    WEIGHTED_SCORE = "weighted_score"
    APPROVAL = "approval"


class SelectionAggregation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: SelectionMethod = SelectionMethod.WEIGHTED_SCORE
    top_n: int = Field(default=5, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)

    def describe(self) -> str:
        return f"{self.method.value}(top_n={self.top_n}, min_score={self.min_score})"


def candidate_scores(
    votes: Sequence[tuple[SelectionResult, float]], candidates: Sequence[str]
) -> dict[str, tuple[float, float]]:
    """{symbol: (weighted_score, approval)} over the agents that answered."""
    answered = [(r, w) for r, w in votes if r.error is None]
    total = sum(w for _, w in answered)
    out: dict[str, tuple[float, float]] = {}
    for symbol in candidates:
        score = approval = 0.0
        for result, weight in answered:
            pick = next((p for p in result.picks if p.symbol == symbol), None)
            if pick is not None:
                score += weight * pick.score
                approval += weight
        out[symbol] = (score / total, approval / total) if total > 0 else (0.0, 0.0)
    return out


def aggregate_selection(
    votes: Sequence[tuple[SelectionResult, float]],
    candidates: Sequence[str],
    options: SelectionAggregation,
) -> tuple[list[str], dict[str, float]]:
    """(selected symbols, best first; the method's score for every candidate)."""
    both = candidate_scores(votes, candidates)
    primary = 0 if options.method is SelectionMethod.WEIGHTED_SCORE else 1
    ranked = sorted(candidates, key=lambda s: (-both[s][primary], -both[s][1 - primary], s))
    scores = {s: round(both[s][primary], 6) for s in candidates}
    selected = [s for s in ranked if scores[s] > 0 and scores[s] >= options.min_score]
    return selected[: options.top_n], scores
