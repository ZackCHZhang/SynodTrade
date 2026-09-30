"""Offline mode: run the whole pipeline with no gateway, no API keys and no network.

- market data: generated daily bars up to `as_of` (deterministic per symbol), for the
  universe and every stock selection candidate;
- candidate sources: static lists as configured; market scanners are replaced by a fixed
  list of large caps (`OFFLINE_SCANNER_SYMBOLS`);
- sentiment sources: a few synthetic posts/headlines per symbol (clearly marked synthetic),
  so the sentiment agents run too;
- LLM: `schema_reply` answers from the requested output schema. Selection agents pick the
  first three candidates shown. Style "neutral" (default): sentiment 0, decision hold —
  nothing can trade. Style "bullish": decisions say buy, so
  risk agents and order planning are exercised as well;
- broker: DryRunBroker (offline always runs in dry_run mode: orders are recorded, never sent).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any, Literal

from quant_core.config import PipelineConfig, StageConfig
from quant_core.llm import FakeLLMClient, LLMRequest
from quant_core.models import SentimentItem
from quant_market_data import FakeMarketDataProvider, generate_daily_bars
from quant_selection import CandidateSourceConfig, FakeCandidateSource
from quant_sentiment.sources import FakeSentimentSource

OfflineLLMStyle = Literal["neutral", "bullish"]

_PROPOSED = re.compile(r'the proposed action is "([a-z_]+)"')
_CANDIDATE = re.compile(r"\[cand:([A-Z0-9.\- ]+)\]")

# What an offline "market scanner" returns.
OFFLINE_SCANNER_SYMBOLS = ("NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM")


def schema_reply(
    request: LLMRequest,
    *,
    decision_action: str = "hold",
    decision_confidence: float = 0.5,
    sentiment: float = 0.0,
) -> str:
    """A valid reply for whichever agent output schema the request carries."""
    props = (request.json_schema or {}).get("properties", {})
    prompt = request.messages[0].content if request.messages else ""
    if "picks" in props:
        symbols = _CANDIDATE.findall(prompt)[:3]
        return json.dumps(
            {
                "picks": [
                    {"symbol": s, "score": round(0.7 - 0.1 * i, 2), "reason": "offline pick"}
                    for i, s in enumerate(symbols)
                ],
                "summary": "offline mode: the first candidates shown",
            }
        )
    if "sentiment" in props:
        ids = re.findall(r'<item id="([^"]+)"', prompt)[:3]
        return json.dumps(
            {
                "sentiment": sentiment,
                "confidence": 0.3,
                "summary": "offline mode: synthetic analysis",
                "key_events": [],
                "item_ids": ids,
            }
        )
    if "action" in props:
        return json.dumps(
            {
                "action": decision_action,
                "confidence": decision_confidence,
                "reasoning": "offline mode: fixed decision",
                "referenced_data_ids": ["ind:rsi_14"],
            }
        )
    if "verdict" in props:
        match = _PROPOSED.search(prompt)
        proposed = match.group(1) if match else "hold"
        return json.dumps(
            {"verdict": "approve", "adjusted_action": proposed, "reason": "offline mode: approved"}
        )
    raise ValueError(f"offline LLM does not know this schema: {sorted(props)}")


def offline_llm(style: OfflineLLMStyle = "neutral") -> FakeLLMClient:
    if style == "bullish":
        return FakeLLMClient(
            default=partial(
                schema_reply, decision_action="buy", decision_confidence=0.8, sentiment=0.4
            )
        )
    return FakeLLMClient(default=schema_reply)


def _weekdays_between(start: date, end: date) -> int:
    return sum(1 for i in range((end - start).days) if (start + timedelta(days=i)).weekday() < 5)


def offline_market_data(
    symbols: Iterable[str], as_of: datetime, days: int = 420
) -> FakeMarketDataProvider:
    """About 300 generated daily bars per symbol, the last one being `as_of`'s trading day."""
    start = as_of.date() - timedelta(days=days)
    count = _weekdays_between(start, as_of.date() + timedelta(days=1))
    bars = [b for s in symbols for b in generate_daily_bars(s, start, count)]
    return FakeMarketDataProvider(bars)


def _synthetic_items(source: str, symbol: str, as_of: datetime) -> list[SentimentItem]:
    if source == "ibkr_news":
        texts = [f"{symbol}: synthetic offline headline, no real news"]
    else:
        texts = [
            f"${symbol} synthetic offline post {i}: looking steady, holding my position"
            for i in range(3)
        ]
    return [
        SentimentItem(
            source=source,
            external_id=f"offline-{source}-{symbol}-{i}",
            symbol=symbol,
            text=text,
            created_at=as_of - timedelta(hours=i + 1),
            author=f"offline_{source}",
            score=5 * (i + 1),
            metadata={"synthetic": True},
        )
        for i, text in enumerate(texts)
    ]


def offline_sentiment_sources(
    names: Iterable[str], symbols: Iterable[str] = (), as_of: datetime | None = None
) -> dict[str, Any]:
    """Fake sources with a few synthetic items per symbol (none without `as_of`)."""
    symbols = list(symbols)
    return {
        name: FakeSentimentSource(
            name,
            [i for s in symbols for i in _synthetic_items(name, s, as_of)] if as_of else [],
        )
        for name in names
    }


def _selection_sources(stage: StageConfig) -> list[CandidateSourceConfig]:
    return [CandidateSourceConfig.model_validate(s) for s in getattr(stage, "sources", [])]


def offline_candidate_sources(stage: StageConfig) -> dict[str, Any]:
    """Fakes for every non-static candidate source of a selection stage."""
    return {
        s.source_name: FakeCandidateSource(s.source_name, OFFLINE_SCANNER_SYMBOLS)
        for s in _selection_sources(stage)
        if s.type != "static"
    }


def offline_symbols(pipeline: PipelineConfig, stages: Sequence[StageConfig]) -> list[str]:
    """Every symbol an offline run may need bars/posts for: the universe plus, with a
    selection stage, all of its candidates."""
    symbols = list(pipeline.universe)
    for stage in stages:
        if stage.type != "selection":
            continue
        for source in _selection_sources(stage):
            extra = source.source_options().get("symbols", []) if source.type == "static" else []
            fake = OFFLINE_SCANNER_SYMBOLS if source.type != "static" else ()
            symbols += [str(s).strip().upper() for s in [*extra, *fake]]
    return list(dict.fromkeys(symbols))
