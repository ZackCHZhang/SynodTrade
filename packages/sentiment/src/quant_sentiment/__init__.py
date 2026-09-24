"""舆情：数据源采集（Reddit/Stocktwits）+ 多 agent 分析"""

from quant_sentiment.agent import SentimentAgent, SentimentOutput
from quant_sentiment.prefilter import PrefilterOptions, clean_text, prefilter
from quant_sentiment.stage import (
    SentimentError,
    SentimentOptions,
    SentimentStage,
    build_sentiment_stage,
)

__version__ = "0.1.0"

__all__ = [
    "PrefilterOptions",
    "SentimentAgent",
    "SentimentError",
    "SentimentOptions",
    "SentimentOutput",
    "SentimentStage",
    "__version__",
    "build_sentiment_stage",
    "clean_text",
    "prefilter",
]
