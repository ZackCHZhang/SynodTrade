"""Sentiment: source collection (Reddit/Stocktwits) + multi-agent analysis"""

from synodtrade_sentiment.agent import SentimentAgent, SentimentOutput
from synodtrade_sentiment.prefilter import PrefilterOptions, clean_text, prefilter
from synodtrade_sentiment.stage import (
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
