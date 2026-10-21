"""IBKR news headlines (and optionally article bodies) via `ib_async`.

Uses its own read-only connection to TWS / IB Gateway. IBKR client ids must be unique per
connection; by default this source uses IBKR_CLIENT_ID + 2 (market data uses the configured
id, trading + 1). Which providers are available depends on the account's news
subscriptions; the API includes free ones such as Briefing.com (BRFG, BRFUPDN) and
Dow Jones (DJNL).

IBKR returns news timestamps without a timezone; they are treated as UTC.
"""

from __future__ import annotations

import html
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from ib_async import IB, Contract, Stock
from pydantic import BaseModel, ConfigDict, Field

from synodtrade_core.logging import get_logger
from synodtrade_core.models import SentimentItem
from synodtrade_core.timeutil import utcnow
from synodtrade_sentiment.sources.base import SourceError

log = get_logger(__name__)

CLIENT_ID_OFFSET = 2
_META = re.compile(r"^\s*\{([^}]*)\}\s*")
_TAG = re.compile(r"<[^>]+>")


class IBKRNewsOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    host: str | None = None  # default: $IBKR_HOST or 127.0.0.1
    port: int | None = None  # default: $IBKR_PORT or 4002
    client_id: int | None = None  # default: $IBKR_CLIENT_ID + 2
    providers: list[str] | None = None  # default: every provider the account can access
    max_headlines: int = Field(default=20, ge=1, le=300)  # per symbol and request
    fetch_bodies: bool = False  # one extra request per article
    max_body_chars: int = Field(default=4000, ge=100)
    currency: str = "USD"
    connect_timeout_s: float = Field(default=10.0, gt=0)


def parse_headline(raw: str) -> tuple[str, dict[str, float | None]]:
    """Split IBKR's optional `{A:800015:L:en:K:-0.97:C:0.66}` prefix from the headline.

    K and C are IBKR's own sentiment score and its confidence, when provided.
    """
    match = _META.match(raw)
    if match is None:
        return raw.strip(), {}
    parts = match.group(1).split(":")
    fields = dict(zip(parts[0::2], parts[1::2], strict=False))
    meta: dict[str, float | None] = {}
    for key, name in (("K", "ibkr_sentiment"), ("C", "ibkr_confidence")):
        if key in fields:
            try:
                meta[name] = float(fields[key])
            except ValueError:
                meta[name] = None
    return raw[match.end() :].strip(), meta


def html_to_text(text: str) -> str:
    return html.unescape(_TAG.sub(" ", text))


class IBKRNewsSource:
    name = "ibkr_news"

    def __init__(
        self,
        options: IBKRNewsOptions,
        *,
        env: Mapping[str, str] | None = None,
        ib: IB | None = None,
    ) -> None:
        env = os.environ if env is None else env
        self.options = options
        self.host = options.host or env.get("IBKR_HOST") or "127.0.0.1"
        self.port = options.port or int(env.get("IBKR_PORT") or 4002)
        self.client_id = (
            options.client_id
            if options.client_id is not None
            else int(env.get("IBKR_CLIENT_ID") or 17) + CLIENT_ID_OFFSET
        )
        self._ib = ib or IB()
        self._con_ids: dict[str, int] = {}
        self._provider_codes: str | None = None

    async def _connect(self) -> None:
        if not self._ib.isConnected():
            await self._ib.connectAsync(
                self.host,
                self.port,
                clientId=self.client_id,
                timeout=self.options.connect_timeout_s,
                readonly=True,
            )

    async def aclose(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()

    async def _providers(self) -> str:
        if self._provider_codes is None:
            codes = self.options.providers
            if codes is None:
                codes = [p.code for p in await self._ib.reqNewsProvidersAsync()]
            if not codes:
                raise SourceError("ibkr_news: the account has no news providers")
            self._provider_codes = "+".join(codes)
        return self._provider_codes

    async def _con_id(self, symbol: str) -> int:
        if symbol not in self._con_ids:
            [contract] = await self._ib.qualifyContractsAsync(
                Stock(symbol, "SMART", self.options.currency)
            )
            if not isinstance(contract, Contract) or not contract.conId:
                raise SourceError(f"ibkr_news: unknown stock {symbol}")
            self._con_ids[symbol] = contract.conId
        return self._con_ids[symbol]

    async def fetch(self, symbols: Sequence[str], since: datetime) -> list[SentimentItem]:
        await self._connect()
        providers = await self._providers()
        items: list[SentimentItem] = []
        errors: dict[str, str] = {}
        for symbol in (s.upper() for s in symbols):
            try:
                items += await self._fetch_symbol(symbol, providers, since)
            except Exception as exc:
                errors[symbol] = f"{type(exc).__name__}: {exc}"
        if errors:
            log.warning("ibkr_news.symbol_errors", errors=errors)
            if len(errors) == len(symbols):
                raise SourceError(f"ibkr_news failed for every symbol: {errors}")
        return items

    async def _fetch_symbol(
        self, symbol: str, providers: str, since: datetime
    ) -> list[SentimentItem]:
        con_id = await self._con_id(symbol)
        headlines: Any = await self._ib.reqHistoricalNewsAsync(
            con_id, providers, since, utcnow(), self.options.max_headlines
        )
        if headlines is None:
            raise SourceError("historical news request timed out")
        items = []
        for news in headlines:
            created = news.time if news.time.tzinfo else news.time.replace(tzinfo=UTC)
            if created < since:
                continue
            headline, meta = parse_headline(news.headline)
            text = headline
            if self.options.fetch_bodies:
                body = await self._body(news.providerCode, news.articleId)
                if body:
                    text = f"{headline}\n\n{body}"
            items.append(
                SentimentItem(
                    source=self.name,
                    external_id=f"{news.providerCode}:{news.articleId}",
                    symbol=symbol,
                    text=text,
                    created_at=created,
                    author=news.providerCode,
                    score=0,
                    metadata={"provider": news.providerCode, **meta},
                )
            )
        return items

    async def _body(self, provider: str, article_id: str) -> str | None:
        article = await self._ib.reqNewsArticleAsync(provider, article_id)
        if article is None or article.articleType != 0:  # 1 = binary (PDF)
            return None
        return html_to_text(article.articleText)[: self.options.max_body_chars]


def build_ibkr_news_source(options: Mapping[str, Any]) -> IBKRNewsSource:
    """Source factory (entry point `synodtrade.sentiment_sources: ibkr_news`)."""
    return IBKRNewsSource(IBKRNewsOptions.model_validate(dict(options)))
