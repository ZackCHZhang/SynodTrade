"""Decide whether a post is about a given ticker."""

from __future__ import annotations

import re
from collections.abc import Iterable

# Tickers that are also everyday words/abbreviations: only `$TICKER` counts for these.
AMBIGUOUS_TICKERS = frozenset(
    [
        "A",
        "AI",
        "ALL",
        "AM",
        "AN",
        "ANY",
        "ARE",
        "AT",
        "BE",
        "BIG",
        "BIT",
        "BY",
        "CAN",
        "CAR",
        "CAT",
        "CEO",
        "DD",
        "DO",
        "EAT",
        "EOD",
        "EV",
        "FOR",
        "FUN",
        "GO",
        "GOOD",
        "HAS",
        "HE",
        "HOLD",
        "HOT",
        "I",
        "IT",
        "KEY",
        "LOVE",
        "LOW",
        "MAN",
        "ME",
        "NEW",
        "NEXT",
        "NICE",
        "NOW",
        "OK",
        "ON",
        "ONE",
        "OPEN",
        "OR",
        "OUT",
        "PLAY",
        "REAL",
        "RUN",
        "SEE",
        "SO",
        "TV",
        "TWO",
        "UP",
        "US",
        "WELL",
        "YOLO",
    ]
)


def mentions(text: str, symbol: str, aliases: Iterable[str] = ()) -> bool:
    """True if `text` refers to `symbol`.

    - `$AAPL` (any case) always counts.
    - Bare `AAPL` counts only in upper case and only for unambiguous tickers.
    - Aliases (e.g. company names like "Apple") match as whole words, any case.
    """
    symbol = symbol.upper()
    escaped = re.escape(symbol)
    if re.search(rf"\${escaped}(?![\w])", text, re.IGNORECASE):
        return True
    if symbol not in AMBIGUOUS_TICKERS and re.search(rf"(?<![\w$]){escaped}(?![\w])", text):
        return True
    return any(
        re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text, re.IGNORECASE) for alias in aliases
    )
