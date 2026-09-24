"""IBKRNewsSource against a stub `IB` object — no gateway, no network."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ib_async import HistoricalNews, NewsArticle, NewsProvider, Stock

from quant_sentiment.sources import (
    IBKRNewsOptions,
    IBKRNewsSource,
    SourceError,
    build_ibkr_news_source,
)
from quant_sentiment.sources.ibkr_news import html_to_text, parse_headline

NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)
SINCE = NOW - timedelta(hours=24)


class StubIB:
    def __init__(self) -> None:
        self.connected = False
        self.calls: list[tuple[str, Any]] = []
        self.providers = [
            NewsProvider("BRFG", "Briefing.com General"),
            NewsProvider("DJNL", "Dow Jones Newsletters"),
        ]
        self.news: dict[int, Any] = {}
        self.articles: dict[str, NewsArticle] = {}
        self.con_ids = {"AAPL": 265598, "MSFT": 272093}

    def isConnected(self) -> bool:  # noqa: N802 - mirrors ib_async
        return self.connected

    async def connectAsync(self, host: str, port: int, **kw: Any) -> None:  # noqa: N802
        self.calls.append(("connect", (host, port, kw)))
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    async def reqNewsProvidersAsync(self) -> list[NewsProvider]:  # noqa: N802
        self.calls.append(("providers", None))
        return self.providers

    async def qualifyContractsAsync(self, contract: Stock) -> list[Any]:  # noqa: N802
        self.calls.append(("qualify", contract.symbol))
        con_id = self.con_ids.get(contract.symbol)
        if con_id is None:
            return [None]
        contract.conId = con_id
        return [contract]

    async def reqHistoricalNewsAsync(  # noqa: N802
        self, con_id: int, providers: str, start: datetime, end: datetime, total: int
    ) -> Any:
        self.calls.append(("news", (con_id, providers, start, total)))
        return self.news.get(con_id, [])

    async def reqNewsArticleAsync(self, provider: str, article_id: str) -> NewsArticle:  # noqa: N802
        self.calls.append(("article", article_id))
        return self.articles[article_id]


def headline(
    article_id: str, text: str, hours_ago: float = 1, naive: bool = True
) -> HistoricalNews:
    ts = NOW - timedelta(hours=hours_ago)
    return HistoricalNews(ts.replace(tzinfo=None) if naive else ts, "BRFG", article_id, text)


def source(ib: StubIB, **options: Any) -> IBKRNewsSource:
    return IBKRNewsSource(IBKRNewsOptions(**options), env={}, ib=ib)  # type: ignore[arg-type]


def test_parse_headline() -> None:
    text, meta = parse_headline("{A:800015:L:en:K:-0.97:C:0.66}Apple cut to Neutral")
    assert text == "Apple cut to Neutral"
    assert meta == {"ibkr_sentiment": -0.97, "ibkr_confidence": 0.66}
    assert parse_headline("{A:1:L:en:K:n/a}Hi") == ("Hi", {"ibkr_sentiment": None})
    assert parse_headline("  Plain headline ") == ("Plain headline", {})


def test_html_to_text() -> None:
    assert html_to_text("<p>Revenue &amp; margins <b>up</b></p>").split() == [
        "Revenue",
        "&",
        "margins",
        "up",
    ]


async def test_fetches_headlines_per_symbol() -> None:
    ib = StubIB()
    ib.news = {
        265598: [
            headline("a1", "{K:0.8:C:0.9}Apple beats estimates"),
            headline("old", "Too old", hours_ago=30),
        ],
        272093: [headline("m1", "Microsoft outage", naive=False)],
    }
    src = source(ib)
    items = await src.fetch(["aapl", "MSFT"], SINCE)
    assert [(i.symbol, i.external_id) for i in items] == [
        ("AAPL", "BRFG:a1"),
        ("MSFT", "BRFG:m1"),
    ]
    apple = items[0]
    assert apple.text == "Apple beats estimates"
    assert apple.source == "ibkr_news"
    assert apple.author == "BRFG"
    assert apple.score == 0
    assert apple.created_at == NOW - timedelta(hours=1)  # naive IBKR time treated as UTC
    assert apple.metadata == {"provider": "BRFG", "ibkr_sentiment": 0.8, "ibkr_confidence": 0.9}
    news_calls = [c[1] for c in ib.calls if c[0] == "news"]
    assert news_calls[0][1] == "BRFG+DJNL"  # every available provider by default
    assert news_calls[0][3] == 20

    await src.fetch(["AAPL"], SINCE)  # providers and con_ids are cached
    assert sum(c[0] == "providers" for c in ib.calls) == 1
    assert sum(c[0] == "qualify" for c in ib.calls) == 2
    connect = next(c[1] for c in ib.calls if c[0] == "connect")
    assert connect[2]["readonly"] is True
    await src.aclose()
    assert not ib.connected


async def test_bodies_and_explicit_providers() -> None:
    ib = StubIB()
    ib.news = {265598: [headline("a1", "Apple guidance"), headline("pdf", "Report")]}
    ib.articles = {
        "a1": NewsArticle(0, "<p>Guidance raised to <b>$100B</b></p>" + "x" * 500),
        "pdf": NewsArticle(1, "%PDF-binary"),
    }
    src = source(ib, providers=["DJNL"], fetch_bodies=True, max_body_chars=100)
    items = await src.fetch(["AAPL"], SINCE)
    by_id = {i.external_id: i for i in items}
    assert by_id["BRFG:a1"].text.startswith("Apple guidance\n\n")
    assert "Guidance raised to" in by_id["BRFG:a1"].text
    assert len(by_id["BRFG:a1"].text) <= len("Apple guidance\n\n") + 100
    assert by_id["BRFG:pdf"].text == "Report"  # binary articles keep just the headline
    assert ("providers", None) not in ib.calls
    assert next(c[1] for c in ib.calls if c[0] == "news")[1] == "DJNL"


async def test_partial_and_total_failures() -> None:
    ib = StubIB()
    ib.news = {265598: [headline("a1", "Apple news")], 272093: None}  # None = timed out
    items = await source(ib).fetch(["AAPL", "MSFT", "NOPE"], SINCE)
    assert [i.symbol for i in items] == ["AAPL"]

    with pytest.raises(SourceError, match="every symbol"):
        await source(ib).fetch(["NOPE"], SINCE)

    ib.providers = []
    with pytest.raises(SourceError, match="no news providers"):
        await source(ib).fetch(["AAPL"], SINCE)


def test_connection_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {"IBKR_HOST": "gw", "IBKR_PORT": "4001", "IBKR_CLIENT_ID": "30"}
    src = IBKRNewsSource(IBKRNewsOptions(), env=env)
    assert (src.host, src.port, src.client_id) == ("gw", 4001, 32)  # market data id + 2
    explicit = IBKRNewsSource(IBKRNewsOptions(host="h", port=7497, client_id=5), env={})
    assert (explicit.host, explicit.port, explicit.client_id) == ("h", 7497, 5)
    defaults = IBKRNewsSource(IBKRNewsOptions(), env={})
    assert (defaults.host, defaults.port, defaults.client_id) == ("127.0.0.1", 4002, 19)
    monkeypatch.delenv("IBKR_CLIENT_ID", raising=False)
    assert build_ibkr_news_source({"max_headlines": 5}).options.max_headlines == 5
