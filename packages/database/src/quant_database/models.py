"""ORM tables (spec §4.2). Internal to this package: other packages use the repositories,
which accept and return `quant_core` models.

Enum-like columns are plain strings (the `quant_core` enum values) so adding a value never
needs a database enum migration. Every per-run record carries `run_id`; every agent output
carries `instance_id`. Raw LLM input/output lives in `llm_calls`, referenced by
`llm_call_ids` from the rows that used them.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from quant_core.timeutil import utcnow
from quant_database.column_types import BigIntPK, DecimalType, JSONType, UtcDateTime

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

SYMBOL = String(32)
SHORT = String(32)
NAME = String(64)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 - read by SQLAlchemy at class creation
        Decimal: DecimalType(),
        datetime: UtcDateTime(),
        dict[str, Any]: JSONType,
        list[Any]: JSONType,
        UUID: Uuid(),
    }


# ------------------------------------------------------------------ market data


class InstrumentRow(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    symbol: Mapped[str] = mapped_column(SYMBOL, unique=True)
    sec_type: Mapped[str] = mapped_column(SHORT, default="STK")
    exchange: Mapped[str] = mapped_column(SHORT, default="SMART")
    primary_exchange: Mapped[str | None] = mapped_column(SHORT)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    con_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    lot_size: Mapped[Decimal] = mapped_column(default=Decimal(1))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class MarketBarRow(Base):
    __tablename__ = "market_bars"
    __table_args__ = (UniqueConstraint("instrument_id", "timeframe", "ts"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    timeframe: Mapped[str] = mapped_column(String(8))
    ts: Mapped[datetime]
    open: Mapped[Decimal]
    high: Mapped[Decimal]
    low: Mapped[Decimal]
    close: Mapped[Decimal]
    volume: Mapped[Decimal]


class QuoteSnapshotRow(Base):
    __tablename__ = "quote_snapshots"
    __table_args__ = (Index(None, "instrument_id", "ts"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    ts: Mapped[datetime]
    bid: Mapped[Decimal | None]
    ask: Mapped[Decimal | None]
    last: Mapped[Decimal | None]
    bid_size: Mapped[Decimal | None]
    ask_size: Mapped[Decimal | None]


class AccountSnapshotRow(Base):
    __tablename__ = "account_snapshots"
    __table_args__ = (Index(None, "account_id", "ts"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    account_id: Mapped[str] = mapped_column(NAME)
    ts: Mapped[datetime]
    currency: Mapped[str] = mapped_column(String(8))
    nav: Mapped[Decimal]
    cash: Mapped[Decimal]
    buying_power: Mapped[Decimal]
    available_funds: Mapped[Decimal | None]


class PositionSnapshotRow(Base):
    __tablename__ = "position_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "ts", "instrument_id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    account_id: Mapped[str] = mapped_column(NAME)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    ts: Mapped[datetime]
    qty: Mapped[Decimal]
    avg_cost: Mapped[Decimal]
    market_price: Mapped[Decimal | None]


class FundamentalsSnapshotRow(Base):
    """Company fundamentals as known at `as_of` (a serialized `quant_core` Fundamentals)."""

    __tablename__ = "fundamentals_snapshots"
    __table_args__ = (Index(None, "symbol", "as_of"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    symbol: Mapped[str] = mapped_column(SYMBOL)
    as_of: Mapped[datetime]
    source: Mapped[str] = mapped_column(SHORT)
    available: Mapped[bool] = mapped_column(Boolean)
    period_end: Mapped[str | None] = mapped_column(String(10))  # ISO date
    data: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


# ------------------------------------------------------------------ runs and agents


class PipelineRunRow(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (Index(None, "pipeline_name", "status"),)

    run_id: Mapped[UUID] = mapped_column(primary_key=True)
    pipeline_name: Mapped[str] = mapped_column(NAME)
    mode: Mapped[str] = mapped_column(SHORT)
    config_hash: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict[str, Any]]
    as_of: Mapped[datetime]
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(SHORT)
    error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict[str, Any] | None]


class AgentInstanceRow(Base):
    __tablename__ = "agent_instances"

    instance_id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_runs.run_id"), index=True)
    agent_id: Mapped[str] = mapped_column(NAME)
    agent_type: Mapped[str] = mapped_column(SHORT)  # role: sentiment / decision / risk
    persona: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(SHORT)
    provider: Mapped[str] = mapped_column(NAME)
    model: Mapped[str] = mapped_column(NAME)
    config: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class LLMCallRow(Base):
    __tablename__ = "llm_calls"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID | None] = mapped_column(index=True)
    instance_id: Mapped[UUID | None] = mapped_column(index=True)
    agent_id: Mapped[str | None] = mapped_column(NAME)
    provider: Mapped[str] = mapped_column(NAME)
    model: Mapped[str] = mapped_column(NAME)
    attempt: Mapped[int]
    request: Mapped[dict[str, Any]]
    response_text: Mapped[str | None] = mapped_column(Text)
    raw_response: Mapped[dict[str, Any] | None]
    stop_reason: Mapped[str | None] = mapped_column(SHORT)
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    cache_read_input_tokens: Mapped[int | None]
    cache_creation_input_tokens: Mapped[int | None]
    latency_ms: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime]


# ------------------------------------------------------------------ stock selection


class SelectionResultRow(Base):
    __tablename__ = "selection_results"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_runs.run_id"), index=True)
    pipeline_name: Mapped[str] = mapped_column(NAME)
    instance_id: Mapped[UUID]
    agent_id: Mapped[str] = mapped_column(NAME)
    prompt_version: Mapped[str] = mapped_column(SHORT)
    picks: Mapped[list[Any]]  # [{symbol, score, reason}]
    summary: Mapped[str] = mapped_column(Text)
    candidates: Mapped[list[Any]]
    llm_call_ids: Mapped[list[Any]]
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime]


class WatchlistRow(Base):
    """One row per (pipeline, symbol); removal only sets `removed_at`."""

    __tablename__ = "watchlist_entries"
    __table_args__ = (UniqueConstraint("pipeline_name", "symbol"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    pipeline_name: Mapped[str] = mapped_column(NAME)
    symbol: Mapped[str] = mapped_column(SYMBOL)
    added_at: Mapped[datetime]
    last_selected_at: Mapped[datetime | None]
    times_selected: Mapped[int] = mapped_column(Integer, default=0)
    last_score: Mapped[float | None] = mapped_column(Float)
    last_reason: Mapped[str | None] = mapped_column(Text)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    removed_at: Mapped[datetime | None]
    removed_reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class StockSelectionRow(Base):
    __tablename__ = "stock_selections"
    __table_args__ = (Index(None, "pipeline_name", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_runs.run_id"), unique=True)
    pipeline_name: Mapped[str] = mapped_column(NAME)
    method: Mapped[str] = mapped_column(NAME)
    candidates: Mapped[list[Any]]
    selected: Mapped[list[Any]]
    holdings: Mapped[list[Any]]
    # server_default: lets create_all() add the column to a table made before it existed
    watchlist: Mapped[list[Any]] = mapped_column(default=list, server_default="[]")
    scores: Mapped[dict[str, Any]]
    rejected: Mapped[dict[str, Any]]
    created_at: Mapped[datetime]


# ------------------------------------------------------------------ sentiment


class SentimentItemRow(Base):
    __tablename__ = "sentiment_items"
    # One post mentioning several tickers is stored once per symbol.
    __table_args__ = (
        UniqueConstraint("source", "external_id", "symbol"),
        Index(None, "symbol", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    source: Mapped[str] = mapped_column(SHORT)
    external_id: Mapped[str] = mapped_column(String(128))
    symbol: Mapped[str] = mapped_column(SYMBOL)
    text: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime]
    score: Mapped[int] = mapped_column(default=0)
    url: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata")
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow)


class SentimentResultRow(Base):
    __tablename__ = "sentiment_results"
    __table_args__ = (Index(None, "symbol", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_runs.run_id"), index=True)
    instance_id: Mapped[UUID]
    agent_id: Mapped[str] = mapped_column(NAME)
    prompt_version: Mapped[str] = mapped_column(SHORT)
    symbol: Mapped[str] = mapped_column(SYMBOL)
    sentiment: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    summary: Mapped[str] = mapped_column(Text)
    key_events: Mapped[list[Any]]
    item_ids: Mapped[list[Any]]
    llm_call_ids: Mapped[list[Any]]
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime]


# ------------------------------------------------------------------ decisions and risk


class DecisionRow(Base):
    __tablename__ = "decisions"
    __table_args__ = (Index(None, "symbol", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_runs.run_id"), index=True)
    instance_id: Mapped[UUID]
    agent_id: Mapped[str] = mapped_column(NAME)
    prompt_version: Mapped[str] = mapped_column(SHORT)
    symbol: Mapped[str] = mapped_column(SYMBOL)
    action: Mapped[str] = mapped_column(SHORT)
    confidence: Mapped[float] = mapped_column(Float)
    reasoning: Mapped[str] = mapped_column(Text)
    referenced_data_ids: Mapped[list[Any]]
    llm_call_ids: Mapped[list[Any]]
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime]


class AggregatedDecisionRow(Base):
    __tablename__ = "aggregated_decisions"
    __table_args__ = (UniqueConstraint("run_id", "symbol"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_runs.run_id"))
    symbol: Mapped[str] = mapped_column(SYMBOL)
    final_action: Mapped[str] = mapped_column(SHORT)
    # includes the options, e.g. "weighted_vote(min_confidence=0.6)", so no length limit
    method: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float)
    votes: Mapped[list[Any]]
    created_at: Mapped[datetime]


class RiskAssessmentRow(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_runs.run_id"), index=True)
    symbol: Mapped[str] = mapped_column(SYMBOL)
    source: Mapped[str] = mapped_column(NAME)
    instance_id: Mapped[UUID | None]
    decision_id: Mapped[UUID | None] = mapped_column(ForeignKey("aggregated_decisions.id"))
    verdict: Mapped[str] = mapped_column(SHORT)
    original_action: Mapped[str] = mapped_column(SHORT)
    adjusted_action: Mapped[str] = mapped_column(SHORT)
    reason: Mapped[str] = mapped_column(Text)
    rule_hits: Mapped[list[Any]]
    llm_call_ids: Mapped[list[Any]]
    created_at: Mapped[datetime]


# ------------------------------------------------------------------ orders


class OrderRow(Base):
    __tablename__ = "orders"
    __table_args__ = (Index(None, "pipeline_name", "created_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True)  # idempotency key
    run_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_runs.run_id"), index=True)
    pipeline_name: Mapped[str] = mapped_column(NAME)
    symbol: Mapped[str] = mapped_column(SYMBOL)
    action: Mapped[str] = mapped_column(SHORT)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[Decimal]
    order_type: Mapped[str] = mapped_column(String(16))
    limit_price: Mapped[Decimal | None]
    time_in_force: Mapped[str] = mapped_column(String(8))
    estimated_notional: Mapped[Decimal]
    status: Mapped[str] = mapped_column(SHORT)
    broker_order_id: Mapped[str | None] = mapped_column(String(64))
    filled_qty: Mapped[Decimal] = mapped_column(default=Decimal(0))
    avg_fill_price: Mapped[Decimal | None]
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class FillRow(Base):
    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    exec_id: Mapped[str] = mapped_column(String(128), unique=True)
    symbol: Mapped[str] = mapped_column(SYMBOL)
    side: Mapped[str] = mapped_column(String(8))
    qty: Mapped[Decimal]
    price: Mapped[Decimal]
    commission: Mapped[Decimal]
    ts: Mapped[datetime]


# ------------------------------------------------------------------ system


class SystemFlagRow(Base):
    """Operational switches, e.g. the global kill switch (spec §8)."""

    __tablename__ = "system_flags"

    key: Mapped[str] = mapped_column(NAME, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
