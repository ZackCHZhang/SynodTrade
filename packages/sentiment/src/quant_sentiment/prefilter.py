"""Deterministic pre-filtering before anything reaches an LLM (token and noise control)."""

from __future__ import annotations

import hashlib
import math
import re
from collections import deque
from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from quant_core.models import SentimentItem

_WS = re.compile(r"\s+")
_URL = re.compile(r"https?://\S+")


class PrefilterOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_items_per_symbol: int = Field(default=20, ge=1, le=200)
    max_chars_per_item: int = Field(default=800, ge=50)
    min_chars: int = Field(default=15, ge=0)
    min_score: int = 0
    bot_authors: list[str] = Field(
        default_factory=lambda: ["AutoModerator", "VisualMod", "QualityVote"]
    )
    bot_name_pattern: str = r"(?i)(^bot_|_bot$|bot$)"
    # How fast a post's rank decays with age, relative to log-engagement.
    half_life_hours: float = Field(default=12.0, gt=0)


def clean_text(text: str, max_chars: int) -> str:
    """Collapse whitespace, drop URLs, neutralise angle brackets (so a post cannot close the
    <post> delimiters in the prompt), and truncate."""
    text = _WS.sub(" ", _URL.sub("[link]", text)).strip()
    text = text.replace("<", "‹").replace(">", "›")
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def _fingerprint(text: str) -> str:
    normalised = re.sub(r"[^a-z0-9$]+", " ", text.lower()).strip()
    return hashlib.sha1(normalised.encode()).hexdigest()


def _rank(item: SentimentItem, now: datetime, half_life_h: float) -> float:
    age_h = max(0.0, (now - item.created_at).total_seconds() / 3600)
    return math.log1p(max(item.score, 0)) - age_h / half_life_h * math.log(2)


def prefilter(
    items: Iterable[SentimentItem], options: PrefilterOptions, now: datetime
) -> dict[str, list[SentimentItem]]:
    """Per symbol: drop bots/short/low-score/duplicate posts, keep the top N (ranked by
    engagement with recency decay within each source, shared fairly across sources),
    clean the text, and return them oldest first."""
    bot_authors = {a.lower() for a in options.bot_authors}
    bot_pattern = re.compile(options.bot_name_pattern)
    seen_ids: set[tuple[str, str, str]] = set()
    seen_text: set[tuple[str, str]] = set()
    grouped: dict[str, list[SentimentItem]] = {}

    for item in items:
        author = item.author or ""
        if author.lower() in bot_authors or (author and bot_pattern.search(author)):
            continue
        if len(item.text.strip()) < options.min_chars or item.score < options.min_score:
            continue
        key = (item.source, item.external_id, item.symbol)
        text_key = (item.symbol, _fingerprint(item.text))
        if key in seen_ids or text_key in seen_text:
            continue  # exact repost / copy-paste spam
        seen_ids.add(key)
        seen_text.add(text_key)
        grouped.setdefault(item.symbol, []).append(item)

    result: dict[str, list[SentimentItem]] = {}
    for symbol, candidates in grouped.items():
        # Rank within each source, then take from the sources in turn: engagement scores
        # are not comparable across sources (news has none), so no source can crowd out
        # the others.
        by_source: dict[str, list[SentimentItem]] = {}
        for item in candidates:
            by_source.setdefault(item.source, []).append(item)
        queues = [
            deque(
                sorted(
                    group,
                    key=lambda i: (_rank(i, now, options.half_life_hours), i.created_at),
                    reverse=True,
                )
            )
            for _, group in sorted(by_source.items())
        ]
        picked: list[SentimentItem] = []
        while len(picked) < options.max_items_per_symbol and any(queues):
            for queue in queues:
                if queue and len(picked) < options.max_items_per_symbol:
                    picked.append(queue.popleft())
        result[symbol] = [
            i.model_copy(update={"text": clean_text(i.text, options.max_chars_per_item)})
            for i in sorted(picked, key=lambda i: i.created_at)
        ]
    return result
