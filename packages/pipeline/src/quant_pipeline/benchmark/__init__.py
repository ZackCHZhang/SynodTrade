"""Paper-trading benchmark: equity curves from fills, metrics, an SVG chart and README pages."""

from quant_pipeline.benchmark.chart import render_svg
from quant_pipeline.benchmark.compute import (
    PUBLISHED_MODES,
    DayPoint,
    Metrics,
    PipelineCurve,
    build_curve,
    build_curves,
    compute_metrics,
)
from quant_pipeline.benchmark.report import write_benchmark

__all__ = [
    "PUBLISHED_MODES",
    "DayPoint",
    "Metrics",
    "PipelineCurve",
    "build_curve",
    "build_curves",
    "compute_metrics",
    "render_svg",
    "write_benchmark",
]
