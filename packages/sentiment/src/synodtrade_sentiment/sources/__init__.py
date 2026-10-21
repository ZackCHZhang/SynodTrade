"""Sentiment data sources (implement `synodtrade_core.interfaces.SentimentSource`)."""

from synodtrade_sentiment.sources.base import FakeSentimentSource, SourceConfigError, SourceError
from synodtrade_sentiment.sources.ibkr_news import (
    IBKRNewsOptions,
    IBKRNewsSource,
    build_ibkr_news_source,
)
from synodtrade_sentiment.sources.reddit import RedditOptions, RedditSource, build_reddit_source
from synodtrade_sentiment.sources.stocktwits import (
    StocktwitsOptions,
    StocktwitsSource,
    build_stocktwits_source,
)
from synodtrade_sentiment.sources.tickers import AMBIGUOUS_TICKERS, mentions

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
