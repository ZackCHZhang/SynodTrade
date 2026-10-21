"""Reddit via the official API (asyncpraw, read-only "script" app credentials)."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import asyncpraw
from pydantic import BaseModel, ConfigDict, Field

from synodtrade_core.logging import get_logger
from synodtrade_core.models import SentimentItem
from synodtrade_core.timeutil import utcnow
from synodtrade_sentiment.sources.base import SourceConfigError
from synodtrade_sentiment.sources.tickers import mentions

log = get_logger(__name__)

ENV_CLIENT_ID = "REDDIT_CLIENT_ID"
ENV_CLIENT_SECRET = "REDDIT_CLIENT_SECRET"
ENV_USER_AGENT = "REDDIT_USER_AGENT"


class RedditOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subreddits: list[str] = Field(
        default_factory=lambda: ["stocks", "investing", "wallstreetbets"], min_length=1
    )
    # search: one search per (subreddit, symbol), newest first. Finds older mentions in busy
    #         subreddits. new: one listing per subreddit, filtered locally (fewer calls).
    mode: Literal["search", "new"] = "search"
    limit: int = Field(default=50, ge=1, le=100)  # posts per request
    min_upvotes: int = 0
    include_nsfw: bool = False
    aliases: dict[str, list[str]] = Field(default_factory=dict)  # e.g. {AAPL: [Apple]}


def time_filter(since: datetime, now: datetime) -> str:
    age = now - since
    for label, limit in (
        ("hour", timedelta(hours=1)),
        ("day", timedelta(days=1)),
        ("week", timedelta(days=7)),
        ("month", timedelta(days=31)),
        ("year", timedelta(days=366)),
    ):
        if age <= limit:
            return label
    return "all"


class RedditSource:
    name = "reddit"

    def __init__(self, options: RedditOptions, reddit: Any) -> None:
        self.options = options
        self._reddit = reddit

    @classmethod
    def from_env(cls, options: RedditOptions, env: Mapping[str, str] | None = None) -> RedditSource:
        env = os.environ if env is None else env
        missing = [k for k in (ENV_CLIENT_ID, ENV_CLIENT_SECRET, ENV_USER_AGENT) if not env.get(k)]
        if missing:
            raise SourceConfigError(f"reddit: environment variables not set: {missing}")
        reddit = asyncpraw.Reddit(
            client_id=env[ENV_CLIENT_ID],
            client_secret=env[ENV_CLIENT_SECRET],
            user_agent=env[ENV_USER_AGENT],
        )
        reddit.read_only = True
        return cls(options, reddit)

    async def aclose(self) -> None:
        await self._reddit.close()

    async def fetch(self, symbols: Sequence[str], since: datetime) -> list[SentimentItem]:
        symbols = [s.upper() for s in symbols]
        items: dict[tuple[str, str], SentimentItem] = {}
        for sub_name in self.options.subreddits:
            subreddit = await self._reddit.subreddit(sub_name)
            if self.options.mode == "search":
                for symbol in symbols:
                    terms = [symbol, *self.options.aliases.get(symbol, [])]
                    listing = subreddit.search(
                        " OR ".join(terms),
                        sort="new",
                        time_filter=time_filter(since, utcnow()),
                        limit=self.options.limit,
                    )
                    async for post in listing:
                        if self._created(post) < since:
                            break  # newest first: the rest is older
                        self._consider(post, sub_name, [symbol], since, items)
            else:
                async for post in subreddit.new(limit=self.options.limit):
                    self._consider(post, sub_name, symbols, since, items)
        log.info("reddit.fetched", items=len(items), symbols=symbols)
        return list(items.values())

    @staticmethod
    def _created(post: Any) -> datetime:
        return datetime.fromtimestamp(float(post.created_utc), UTC)

    def _consider(
        self,
        post: Any,
        subreddit: str,
        symbols: Sequence[str],
        since: datetime,
        out: dict[tuple[str, str], SentimentItem],
    ) -> None:
        created = self._created(post)
        if created < since or post.stickied or post.score < self.options.min_upvotes:
            return
        if post.over_18 and not self.options.include_nsfw:
            return
        text = f"{post.title}\n\n{post.selftext or ''}".strip()
        for symbol in symbols:
            if not mentions(text, symbol, self.options.aliases.get(symbol, [])):
                continue
            out[(post.id, symbol)] = SentimentItem(
                source=self.name,
                external_id=str(post.id),
                symbol=symbol,
                text=text,
                created_at=created,
                author=post.author.name if post.author is not None else None,
                score=int(post.score),
                url=f"https://www.reddit.com{post.permalink}",
                metadata={"subreddit": subreddit, "num_comments": int(post.num_comments)},
            )


def build_reddit_source(options: Mapping[str, Any]) -> RedditSource:
    """Source factory (entry point `synodtrade.sentiment_sources: reddit`)."""
    return RedditSource.from_env(RedditOptions.model_validate(dict(options)))
