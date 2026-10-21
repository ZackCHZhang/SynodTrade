"""PipelineContext: the only object passed between pipeline stages."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from synodtrade_core.models.analysis import (
    AggregatedDecision,
    Decision,
    RiskVerdict,
    SelectionResult,
    SentimentResult,
    StockSelection,
)
from synodtrade_core.models.enums import RunMode
from synodtrade_core.models.orders import OrderIntent, OrderResult
from synodtrade_core.timeutil import UtcDatetime, utcnow


class StageError(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: str
    error_type: str
    message: str
    skipped: bool  # True if the failure was tolerated via `on_error: skip`


class PipelineContext(BaseModel):
    """Mutable run state. Stages read earlier outputs and append their own.

    `as_of` is the point in time the run reasons about; all data reads should be
    "as of" this instant so a future replay/backtest mode cannot peek ahead.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    run_id: UUID = Field(default_factory=uuid4)
    pipeline_name: str
    mode: RunMode
    universe: list[str]
    started_at: UtcDatetime = Field(default_factory=utcnow)
    as_of: UtcDatetime = Field(default_factory=utcnow)
    # True when the run reasons about "now" (no explicit as_of): see `snapshot_cutoff`.
    live: bool = False

    selection_results: list[SelectionResult] = Field(default_factory=list)
    selection: StockSelection | None = None  # set by the selection stage (which sets universe)
    sentiment_results: dict[str, list[SentimentResult]] = Field(default_factory=dict)
    decisions: dict[str, list[Decision]] = Field(default_factory=dict)
    aggregated_decisions: dict[str, AggregatedDecision] = Field(default_factory=dict)
    risk_verdicts: dict[str, RiskVerdict] = Field(default_factory=dict)
    order_intents: list[OrderIntent] = Field(default_factory=list)
    order_results: list[OrderResult] = Field(default_factory=list)

    completed_stages: list[str] = Field(default_factory=list)
    errors: list[StageError] = Field(default_factory=list)

    def snapshot_cutoff(self) -> datetime:
        """Latest timestamp of quotes and account snapshots a stage may read.

        A live run fetches them during the run, i.e. after `as_of` (the run's start): it may
        read up to the current time. A replay (explicit as_of) never reads past `as_of`.
        """
        return max(self.as_of, utcnow()) if self.live else self.as_of

    @property
    def aborted(self) -> bool:
        return any(not e.skipped for e in self.errors)
