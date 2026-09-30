"""Selection, sentiment, decision and risk records produced by agents during a run."""

from __future__ import annotations

from typing import Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from quant_core.models.base import CoreModel, Probability, SentimentScore, Symbol
from quant_core.models.enums import Action, Verdict
from quant_core.timeutil import UtcDatetime, utcnow


class SentimentItem(CoreModel):
    """One raw post/message from a sentiment source. Unique by (source, external_id)."""

    source: str
    external_id: str
    symbol: Symbol
    text: str
    created_at: UtcDatetime
    author: str | None = None
    score: int = 0  # upvotes / likes
    url: str | None = None
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class AgentOutputMeta(CoreModel):
    """Traceability fields shared by every agent output."""

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    instance_id: UUID
    agent_id: str
    prompt_version: str
    created_at: UtcDatetime = Field(default_factory=utcnow)
    llm_call_ids: list[UUID] = Field(default_factory=list)
    error: str | None = None  # set when the agent fell back to its default output


class Candidate(CoreModel):
    """A symbol proposed for stock selection by a candidate source."""

    symbol: Symbol
    source: str
    rank: int | None = None  # position in the source's own ranking (e.g. a scanner), 0 = top
    note: str | None = None


class SelectionPick(CoreModel):
    symbol: Symbol
    score: Probability  # how strongly the agent wants the symbol in the universe
    reason: str


class SelectionResult(AgentOutputMeta):
    """One selection agent's picks from the screened candidates."""

    pipeline_name: str
    picks: list[SelectionPick] = Field(default_factory=list)
    summary: str = ""
    candidates: list[str] = Field(default_factory=list)  # what the agent was shown


class StockSelection(CoreModel):
    """The aggregated selection of one run: the universe the later stages trade."""

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    pipeline_name: str
    method: str
    candidates: list[str]  # after screening, i.e. shown to the agents
    selected: list[str]  # picked, best first
    holdings: list[str] = Field(default_factory=list)  # kept because the strategy holds them
    scores: dict[str, float] = Field(default_factory=dict)  # aggregated score per candidate
    rejected: dict[str, str] = Field(default_factory=dict)  # symbol -> screening reason
    created_at: UtcDatetime = Field(default_factory=utcnow)

    @property
    def universe(self) -> list[str]:
        return self.selected + [s for s in self.holdings if s not in self.selected]


class SentimentResult(AgentOutputMeta):
    symbol: Symbol
    sentiment: SentimentScore
    confidence: Probability
    summary: str
    key_events: list[str] = Field(default_factory=list)
    item_ids: list[str] = Field(default_factory=list)  # SentimentItem.external_id values used


class Decision(AgentOutputMeta):
    symbol: Symbol
    action: Action
    confidence: Probability
    reasoning: str
    referenced_data_ids: list[str] = Field(default_factory=list)


class Vote(CoreModel):
    instance_id: UUID
    agent_id: str
    action: Action
    confidence: Probability
    weight: float = Field(gt=0)


class AggregatedDecision(CoreModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    symbol: Symbol
    final_action: Action
    method: str
    score: float  # method-specific; for weighted_vote the ordinal weight-space score
    votes: list[Vote]
    created_at: UtcDatetime = Field(default_factory=utcnow)


class RuleHit(CoreModel):
    rule: str
    message: str
    blocking: bool  # True if the rule forced reject/reduce, False if informational
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class RiskVerdict(CoreModel):
    """Outcome of the risk layer. The model itself enforces "risk can only be reduced"."""

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    symbol: Symbol
    source: str  # "rules" for the deterministic engine, else the risk agent_id
    instance_id: UUID | None = None  # None for the deterministic rule engine
    decision_id: UUID | None = None  # the AggregatedDecision being assessed
    verdict: Verdict
    original_action: Action
    adjusted_action: Action
    reason: str
    rule_hits: list[RuleHit] = Field(default_factory=list)
    llm_call_ids: list[UUID] = Field(default_factory=list)
    created_at: UtcDatetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _only_reduce_risk(self) -> Self:
        original, adjusted = self.original_action, self.adjusted_action
        if not adjusted.is_reduction_of(original):
            raise ValueError(f"risk layer may not change {original} to {adjusted}")
        if self.verdict is Verdict.APPROVE and adjusted is not original:
            raise ValueError("approve must keep the original action")
        if self.verdict is Verdict.REJECT and adjusted is not Action.HOLD:
            raise ValueError("reject must set the action to hold")
        if self.verdict is Verdict.REDUCE and adjusted is original:
            raise ValueError("reduce must change the action")
        return self
