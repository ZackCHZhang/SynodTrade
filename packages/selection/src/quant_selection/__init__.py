"""选股：候选来源（固定列表 / IBKR 扫描器）+ 量化初筛 + 多 agent 选股与聚合"""

from quant_selection.agent import PickOutput, SelectionAgent, SelectionOutput, candidate_inputs
from quant_selection.aggregation import (
    SelectionAggregation,
    SelectionMethod,
    aggregate_selection,
    candidate_scores,
)
from quant_selection.scanner import IBKRScannerOptions, IBKRScannerSource
from quant_selection.screen import CandidateProfile, ScreenOptions, avg_dollar_volume, screen
from quant_selection.sources import (
    CandidateSourceError,
    FakeCandidateSource,
    StaticCandidateSource,
    StaticSourceOptions,
)
from quant_selection.stage import (
    CandidateSourceConfig,
    SelectionError,
    SelectionFallback,
    SelectionOptions,
    SelectionStage,
    build_selection_stage,
)

__version__ = "0.1.0"

__all__ = [
    "CandidateProfile",
    "CandidateSourceConfig",
    "CandidateSourceError",
    "FakeCandidateSource",
    "IBKRScannerOptions",
    "IBKRScannerSource",
    "PickOutput",
    "ScreenOptions",
    "SelectionAgent",
    "SelectionAggregation",
    "SelectionError",
    "SelectionFallback",
    "SelectionMethod",
    "SelectionOptions",
    "SelectionOutput",
    "SelectionStage",
    "StaticCandidateSource",
    "StaticSourceOptions",
    "__version__",
    "aggregate_selection",
    "avg_dollar_volume",
    "build_selection_stage",
    "candidate_inputs",
    "candidate_scores",
    "screen",
]
