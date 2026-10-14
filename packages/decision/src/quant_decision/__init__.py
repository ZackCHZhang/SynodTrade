"""Decision agents, technical indicators, multi-agent decision aggregation"""

from quant_decision.agent import DecisionAgent, DecisionOutput
from quant_decision.aggregation import (
    AggregationMethod,
    AggregationOptions,
    aggregate,
    effective_action,
)
from quant_decision.context import HistoryEntry, SymbolContext, history_entries
from quant_decision.indicators import TechnicalSnapshot, compute_indicators
from quant_decision.stage import DecisionOptions, DecisionStage, build_decision_stage

__version__ = "0.1.0"

__all__ = [
    "AggregationMethod",
    "AggregationOptions",
    "DecisionAgent",
    "DecisionOptions",
    "DecisionOutput",
    "DecisionStage",
    "HistoryEntry",
    "SymbolContext",
    "TechnicalSnapshot",
    "__version__",
    "aggregate",
    "build_decision_stage",
    "compute_indicators",
    "effective_action",
    "history_entries",
]
