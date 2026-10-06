"""Selection, sentiment, decision and risk records produced by agents during a run."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
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


class WatchlistEntry(CoreModel):
    """A stock a pipeline keeps following across runs (one per pipeline and symbol).

    Stock selection adds its picks; an entry leaves after `max_age_days` without being picked
    again, unless it is pinned or held. Removed entries keep their row (`removed_at`).
    """

    pipeline_name: str
    symbol: Symbol
    added_at: UtcDatetime
    last_selected_at: UtcDatetime | None = None  # None: added by hand, never picked
    times_selected: int = Field(default=0, ge=0)
    last_score: float | None = None
    last_reason: str | None = None
    pinned: bool = False  # never expires
    note: str | None = None
    removed_at: UtcDatetime | None = None
    removed_reason: str | None = None

    @property
    def active(self) -> bool:
        return self.removed_at is None

    @property
    def last_seen(self) -> datetime:
        """When it last earned its place: last pick, else when it was added."""
        return self.last_selected_at or self.added_at


class StockSelection(CoreModel):
    """The aggregated selection of one run: the universe the later stages trade."""

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    pipeline_name: str
    method: str
    candidates: list[str]  # after screening, i.e. shown to the agents
    selected: list[str]  # picked, best first
    holdings: list[str] = Field(default_factory=list)  # kept because the strategy holds them
    watchlist: list[str] = Field(default_factory=list)  # still followed from earlier runs
    scores: dict[str, float] = Field(default_factory=dict)  # aggregated score per candidate
    rejected: dict[str, str] = Field(default_factory=dict)  # symbol -> screening reason
    created_at: UtcDatetime = Field(default_factory=utcnow)

    @property
    def universe(self) -> list[str]:
        """Picks first, then watchlist entries from earlier runs, then held stocks."""
        return list(dict.fromkeys([*self.selected, *self.watchlist, *self.holdings]))


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


class DecisionOutcome(CoreModel):
    """What became of a final decision: the risk layer's final action and the order (if any)."""

    risk_action: Action | None = None  # after the risk layer; None: never assessed
    risk_reason: str | None = None
    order_status: str | None = None  # OrderStatus value; None: no order was placed
    filled_qty: Decimal = Decimal(0)
    avg_fill_price: Decimal | None = None


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
