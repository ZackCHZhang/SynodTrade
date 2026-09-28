"""Offline mode: run the whole pipeline with no gateway, no API keys and no network.

- market data: generated daily bars up to `as_of` (deterministic per symbol);
- sentiment sources: present but empty;
- LLM: `schema_reply` answers from the requested output schema with neutral/conservative
  content (sentiment 0, decision hold, risk keeps the proposal) — every agent, prompt and
  validation path runs, but nothing the fake says can make the system trade;
- broker: DryRunBroker (offline always runs in dry_run mode).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from quant_core.llm import FakeLLMClient, LLMRequest
from quant_market_data import FakeMarketDataProvider, generate_daily_bars
from quant_sentiment.sources import FakeSentimentSource

_PROPOSED = re.compile(r'the proposed action is "([a-z_]+)"')


def schema_reply(
    request: LLMRequest, *, decision_action: str = "hold", decision_confidence: float = 0.5
) -> str:
    """A valid reply for whichever agent output schema the request carries."""
    props = (request.json_schema or {}).get("properties", {})
    prompt = request.messages[0].content if request.messages else ""
    if "sentiment" in props:
        return json.dumps(
            {
                "sentiment": 0.0,
                "confidence": 0.3,
                "summary": "offline mode: no analysis",
                "key_events": [],
                "item_ids": [],
            }
        )
    if "action" in props:
        return json.dumps(
            {
                "action": decision_action,
                "confidence": decision_confidence,
                "reasoning": "offline mode: fixed decision",
                "referenced_data_ids": [],
            }
        )
    if "verdict" in props:
        match = _PROPOSED.search(prompt)
        proposed = match.group(1) if match else "hold"
        return json.dumps(
            {"verdict": "approve", "adjusted_action": proposed, "reason": "offline mode: approved"}
        )
    raise ValueError(f"offline LLM does not know this schema: {sorted(props)}")


def offline_llm() -> FakeLLMClient:
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


def offline_sentiment_sources(names: Iterable[str]) -> dict[str, Any]:
    return {name: FakeSentimentSource(name) for name in names}
