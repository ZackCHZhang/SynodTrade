import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from quant_sentiment.sources import (
    FakeSentimentSource,
    RedditOptions,
    RedditSource,
    SourceConfigError,
    SourceError,
    StocktwitsOptions,
    StocktwitsSource,
    build_stocktwits_source,
)
from quant_sentiment.sources.reddit import time_filter

NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)
SINCE = NOW - timedelta(hours=24)


# ------------------------------------------------------------------ reddit stubs


@dataclass
class Author:
    name: str


@dataclass
class Post:
    id: str
    title: str
    hours_ago: float = 1
    selftext: str = ""
    score: int = 10
    stickied: bool = False
    over_18: bool = False
    author: Author | None = None
    num_comments: int = 3

    @property
    def created_utc(self) -> float:
        return (NOW - timedelta(hours=self.hours_ago)).timestamp()

    @property
    def permalink(self) -> str:
        return f"/r/stocks/comments/{self.id}/"


class StubSubreddit:
    def __init__(self, posts: list[Post], calls: list[tuple[str, Any]]) -> None:
        self.posts = posts
        self.calls = calls

    async def _iter(self, posts: list[Post]) -> AsyncIterator[Post]:
        for p in posts:
            yield p

    def search(self, query: str, **kw: Any) -> AsyncIterator[Post]:
        self.calls.append(("search", (query, kw)))
        return self._iter(sorted(self.posts, key=lambda p: p.hours_ago))

    def new(self, **kw: Any) -> AsyncIterator[Post]:
        self.calls.append(("new", kw))
        return self._iter(sorted(self.posts, key=lambda p: p.hours_ago))


class StubReddit:
    def __init__(self, posts: dict[str, list[Post]]) -> None:
        self.posts = posts
        self.calls: list[tuple[str, Any]] = []
        self.closed = False

    async def subreddit(self, name: str) -> StubSubreddit:
        return StubSubreddit(self.posts.get(name, []), self.calls)

    async def close(self) -> None:
        self.closed = True


def test_time_filter() -> None:
    assert time_filter(NOW - timedelta(minutes=30), NOW) == "hour"
    assert time_filter(NOW - timedelta(hours=24), NOW) == "day"
    assert time_filter(NOW - timedelta(days=3), NOW) == "week"
    assert time_filter(NOW - timedelta(days=20), NOW) == "month"
    assert time_filter(NOW - timedelta(days=200), NOW) == "year"
    assert time_filter(NOW - timedelta(days=900), NOW) == "all"


async def test_reddit_search_mode_filters_posts() -> None:
    posts = [
        Post("p1", "$AAPL to the moon", author=Author("alice"), score=50),
        Post("p2", "AAPL earnings", selftext="beat on revenue", hours_ago=2),
        Post("pin", "Daily thread $AAPL", stickied=True),
        Post("nsfw", "$AAPL", over_18=True),
        Post("low", "$AAPL meh", score=0),
        Post("other", "Just MSFT here"),
        Post("old", "$AAPL old news", hours_ago=30),  # older than `since`: stops iteration
        Post("older", "$AAPL even older", hours_ago=40),
    ]
    reddit = StubReddit({"stocks": posts})
    source = RedditSource(RedditOptions(subreddits=["stocks"], min_upvotes=1), reddit)
    items = await source.fetch(["aapl"], SINCE)
    assert {i.external_id for i in items} == {"p1", "p2"}
    p1 = next(i for i in items if i.external_id == "p1")
    assert p1.author == "alice"
    assert p1.score == 50
    assert p1.url == "https://www.reddit.com/r/stocks/comments/p1/"
    assert p1.metadata == {"subreddit": "stocks", "num_comments": 3}
    p2 = next(i for i in items if i.external_id == "p2")
    assert p2.text == "AAPL earnings\n\nbeat on revenue"
    assert p2.author is None
    query, kw = reddit.calls[0][1]
    assert query == "AAPL"
    assert kw["sort"] == "new"
    await source.aclose()
    assert reddit.closed


async def test_reddit_search_uses_aliases() -> None:
    reddit = StubReddit({"stocks": [Post("p", "Apple unveils new chip")]})
    source = RedditSource(RedditOptions(subreddits=["stocks"], aliases={"AAPL": ["Apple"]}), reddit)
    items = await source.fetch(["AAPL"], SINCE)
    assert [i.external_id for i in items] == ["p"]
    assert reddit.calls[0][1][0] == "AAPL OR Apple"


async def test_reddit_new_mode_matches_multiple_symbols() -> None:
    reddit = StubReddit(
        {"wallstreetbets": [Post("x", "$AAPL vs $MSFT, which one?"), Post("y", "$NVDA calls")]}
    )
    source = RedditSource(RedditOptions(subreddits=["wallstreetbets"], mode="new"), reddit)
    items = await source.fetch(["AAPL", "MSFT"], SINCE)
    assert sorted((i.external_id, i.symbol) for i in items) == [("x", "AAPL"), ("x", "MSFT")]
    assert reddit.calls == [("new", {"limit": 50})]


def test_reddit_from_env() -> None:
    with pytest.raises(SourceConfigError, match="REDDIT_CLIENT_ID"):
        RedditSource.from_env(RedditOptions(), env={})
    source = RedditSource.from_env(
        RedditOptions(),
        env={"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "s", "REDDIT_USER_AGENT": "ua"},
    )
    assert source.name == "reddit"


def test_reddit_options_validation() -> None:
    with pytest.raises(ValueError, match="mode"):
        RedditOptions.model_validate({"mode": "hot"})


# ------------------------------------------------------------------ stocktwits


def message(
    mid: int, *, hours_ago: float = 1, likes: int = 3, body: str = "bullish $AAPL"
) -> dict[str, Any]:
    return {
        "id": mid,
        "body": body,
        "created_at": (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "user": {"username": "bob", "followers": 12},
        "likes": {"total": likes},
        "entities": {"sentiment": {"basic": "Bullish"}},
    }


def stocktwits(handler: Any, **kw: Any) -> StocktwitsSource:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.stocktwits.com/api/2"
    )
    return StocktwitsSource(StocktwitsOptions(**kw), client=client, access_token="tok")


async def test_stocktwits_parses_and_filters() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "messages": [
                    message(1, likes=5),
                    message(2, hours_ago=30),  # too old
                    message(3, likes=0),  # below min_likes
                    {"id": 4, "body": "no timestamp"},  # malformed: skipped
                    {**message(5), "created_at": "not a date"},  # invalid: skipped
                ]
            },
        )

    source = stocktwits(handler, min_likes=1)
    items = await source.fetch(["AAPL"], SINCE)
    assert [i.external_id for i in items] == ["1"]
    item = items[0]
    assert item.source == "stocktwits"
    assert item.score == 5
    assert item.metadata == {"declared_sentiment": "Bullish", "followers": 12}
    assert item.url == "https://stocktwits.com/bob/message/1"
    assert seen[0].url.path == "/api/2/streams/symbol/AAPL.json"
    assert seen[0].url.params["access_token"] == "tok"
    await source.aclose()


async def test_stocktwits_partial_and_total_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "MSFT" in request.url.path:
            return httpx.Response(429, json={"errors": "rate limited"})
        return httpx.Response(200, json={"messages": [message(1)]})

    items = await stocktwits(handler).fetch(["AAPL", "MSFT"], SINCE)
    assert [i.symbol for i in items] == ["AAPL"]

    def always_fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    with pytest.raises(SourceError, match="every symbol"):
        await stocktwits(always_fail).fetch(["AAPL", "MSFT"], SINCE)

    def not_a_dict(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps([1, 2]))

    with pytest.raises(SourceError):
        await stocktwits(not_a_dict).fetch(["AAPL"], SINCE)


def test_stocktwits_factory_reads_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCKTWITS_ACCESS_TOKEN", "secret")
    source = build_stocktwits_source({"min_likes": 2})
    assert source.options.min_likes == 2
    assert source._token == "secret"


# ------------------------------------------------------------------ fake


async def test_fake_source(make_post: Any) -> None:
    source = FakeSentimentSource(
        "fake", [make_post("a"), make_post("m", "MSFT"), make_post("old", hours_ago=48)]
    )
    items = await source.fetch(["aapl"], SINCE)
    assert [i.external_id for i in items] == ["a"]
    await source.aclose()
    assert source.closed
    with pytest.raises(SourceError):
        await FakeSentimentSource("x", fail=True).fetch(["AAPL"], SINCE)
