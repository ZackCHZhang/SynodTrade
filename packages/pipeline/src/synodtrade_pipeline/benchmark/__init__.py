"""Paper-trading benchmark: equity curves from fills, metrics, an SVG chart and README pages."""

from synodtrade_pipeline.benchmark.chart import render_svg
from synodtrade_pipeline.benchmark.compute import (
    PUBLISHED_MODES,
    DayPoint,
    LLMSpend,
    Metrics,
    PipelineCurve,
    build_curve,
    build_curves,
    compute_metrics,
    llm_spend,
    pipeline_models,
)
from synodtrade_pipeline.benchmark.report import write_benchmark

__all__ = [
    "PUBLISHED_MODES",
    "DayPoint",
    "LLMSpend",
    "Metrics",
    "PipelineCurve",
    "build_curve",
    "build_curves",
    "compute_metrics",
    "llm_spend",
    "pipeline_models",
    "render_svg",
    "write_benchmark",
]
