"""Stocktwits symbol streams (public API; an access token is optional).

The public API is rate limited (roughly 200 requests/hour unauthenticated) and has become
unreliable for new users; treat this source as best-effort (`on_error: skip` on the stage).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from synodtrade_core.logging import get_logger
from synodtrade_core.models import SentimentItem
from synodtrade_sentiment.sources.base import SourceError

log = get_logger(__name__)

ENV_ACCESS_TOKEN = "STOCKTWITS_ACCESS_TOKEN"


class StocktwitsOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str = "https://api.stocktwits.com/api/2"
    min_likes: int = 0
    timeout_s: float = Field(default=15.0, gt=0)


class StocktwitsSource:
    name = "stocktwits"

    def __init__(
        self,
        options: StocktwitsOptions,
        *,
        access_token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.options = options
        self._token = access_token
        self._client = client or httpx.AsyncClient(
            base_url=options.base_url,
            timeout=options.timeout_s,
            headers={"User-Agent": "SynodTrade/0.1"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, symbols: Sequence[str], since: datetime) -> list[SentimentItem]:
        items: list[SentimentItem] = []
        errors: dict[str, str] = {}
        for symbol in (s.upper() for s in symbols):
            try:
                items += self._parse(symbol, await self._get_stream(symbol), since)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                errors[symbol] = f"{type(exc).__name__}: {exc}"
        if errors:
            log.warning("stocktwits.symbol_errors", errors=errors)
            if len(errors) == len(symbols):
                raise SourceError(f"stocktwits failed for every symbol: {errors}")
        return items

    async def _get_stream(self, symbol: str) -> dict[str, Any]:
        params = {"access_token": self._token} if self._token else None
        response = await self._client.get(f"/streams/symbol/{symbol}.json", params=params)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("unexpected response shape")
        return data

    def _parse(self, symbol: str, data: dict[str, Any], since: datetime) -> list[SentimentItem]:
        items = []
        for msg in data.get("messages", []):
            likes = int((msg.get("likes") or {}).get("total", 0))
            if likes < self.options.min_likes:
                continue
            user = msg.get("user") or {}
            declared = ((msg.get("entities") or {}).get("sentiment") or {}).get("basic")
            try:
                item = SentimentItem(
                    source=self.name,
                    external_id=str(msg["id"]),
                    symbol=symbol,
                    text=str(msg.get("body", "")),
                    created_at=msg["created_at"],
                    author=user.get("username"),
                    score=likes,
                    url=f"https://stocktwits.com/{user.get('username', '_')}/message/{msg['id']}",
                    metadata={"declared_sentiment": declared, "followers": user.get("followers")},
                )
            except ValidationError as exc:
                log.warning("stocktwits.bad_message", id=msg.get("id"), error=str(exc))
                continue
            if item.created_at >= since:
                items.append(item)
        return items


def build_stocktwits_source(options: Mapping[str, Any]) -> StocktwitsSource:
    """Source factory (entry point `synodtrade.sentiment_sources: stocktwits`)."""
    return StocktwitsSource(
        StocktwitsOptions.model_validate(dict(options)),
        access_token=os.environ.get(ENV_ACCESS_TOKEN) or None,
    )
