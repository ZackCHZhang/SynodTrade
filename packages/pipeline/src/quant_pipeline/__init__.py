"""Orchestration: build pipelines from YAML, multi-instance stages, failure policies, CLI"""

from quant_pipeline.offline import (
    offline_llm,
    offline_market_data,
    offline_sentiment_sources,
    schema_reply,
)
from quant_pipeline.runner import (
    STAGE_ALIASES,
    PipelineBusyError,
    PipelineRunner,
    RunOptions,
    RunReport,
    select_stages,
    summarize,
)

__version__ = "0.1.0"

__all__ = [
    "STAGE_ALIASES",
    "PipelineBusyError",
    "PipelineRunner",
    "RunOptions",
    "RunReport",
    "__version__",
    "offline_llm",
    "offline_market_data",
    "offline_sentiment_sources",
    "schema_reply",
    "select_stages",
    "summarize",
]
