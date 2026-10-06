"""Relative Strength Index, 14 periods, Wilder smoothing (0..100)."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from itertools import pairwise

from quant_core.indicators.base import BarSeries, Indicator, Values


def rsi(values: Sequence[float], n: int = 14) -> float | None:
    if len(values) < n + 1:
        return None
    changes = [b - a for a, b in pairwise(values)]
    avg_gain = statistics.fmean(max(c, 0.0) for c in changes[:n])
    avg_loss = statistics.fmean(max(-c, 0.0) for c in changes[:n])
    for c in changes[n:]:
        avg_gain = (avg_gain * (n - 1) + max(c, 0.0)) / n
        avg_loss = (avg_loss * (n - 1) + max(-c, 0.0)) / n
    if avg_loss == 0:
        return 50.0 if avg_gain == 0 else 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def compute(s: BarSeries) -> Values:
    return {"rsi_14": rsi(s.closes, 14)}


INDICATOR = Indicator(name="rsi", fields={"rsi_14": 15}, compute=compute)
