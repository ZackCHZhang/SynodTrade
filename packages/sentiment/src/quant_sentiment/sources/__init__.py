"""Sentiment data sources (implement `quant_core.interfaces.SentimentSource`)."""

from quant_sentiment.sources.base import FakeSentimentSource, SourceConfigError, SourceError
from quant_sentiment.sources.ibkr_news import (
    IBKRNewsOptions,
    IBKRNewsSource,
    build_ibkr_news_source,
)
from quant_sentiment.sources.reddit import RedditOptions, RedditSource, build_reddit_source
from quant_sentiment.sources.stocktwits import (
    StocktwitsOptions,
    StocktwitsSource,
    build_stocktwits_source,
)
from quant_sentiment.sources.tickers import AMBIGUOUS_TICKERS, mentions

__all__ = [
    "AMBIGUOUS_TICKERS",
    "FakeSentimentSource",
    "IBKRNewsOptions",
    "IBKRNewsSource",
    "RedditOptions",
    "RedditSource",
    "SourceConfigError",
    "SourceError",
    "StocktwitsOptions",
    "StocktwitsSource",
    "build_ibkr_news_source",
    "build_reddit_source",
    "build_stocktwits_source",
    "mentions",
]
