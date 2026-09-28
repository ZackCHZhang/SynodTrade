"""主流程编排：从 YAML 构建流水线、多实例化、失败策略、CLI"""

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
