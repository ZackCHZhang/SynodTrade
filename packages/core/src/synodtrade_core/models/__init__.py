"""Domain models shared by all packages."""

from synodtrade_core.models.analysis import (
    AgentOutputMeta,
    AggregatedDecision,
    Candidate,
    Decision,
    DecisionOutcome,
    RiskVerdict,
    RuleHit,
    SelectionPick,
    SelectionResult,
    SentimentItem,
    SentimentResult,
    StockSelection,
    Vote,
    WatchlistEntry,
)
from synodtrade_core.models.base import CoreModel
from synodtrade_core.models.context import PipelineContext, StageError
from synodtrade_core.models.enums import (
    ACTION_TO_WEIGHT,
    Action,
    OrderSide,
    OrderStatus,
    OrderType,
    RunMode,
    Timeframe,
    Verdict,
)
from synodtrade_core.models.fundamentals import Fundamentals, InsiderActivity
from synodtrade_core.models.market import AccountSnapshot, Bar, Instrument, Position, Quote
from synodtrade_core.models.orders import Fill, OrderIntent, OrderResult

__all__ = [
    "ACTION_TO_WEIGHT",
    "AccountSnapshot",
    "Action",
    "AgentOutputMeta",
    "AggregatedDecision",
    "Bar",
    "Candidate",
    "CoreModel",
    "Decision",
    "DecisionOutcome",
    "Fill",
    "Fundamentals",
    "InsiderActivity",
    "Instrument",
    "OrderIntent",
    "OrderResult",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PipelineContext",
    "Position",
    "Quote",
    "RiskVerdict",
    "RuleHit",
    "RunMode",
    "SelectionPick",
    "SelectionResult",
    "SentimentItem",
    "SentimentResult",
    "StageError",
    "StockSelection",
    "Timeframe",
    "Verdict",
    "Vote",
    "WatchlistEntry",
]
