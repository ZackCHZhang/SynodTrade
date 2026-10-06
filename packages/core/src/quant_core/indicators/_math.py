"""Small numeric helpers used by several indicator modules (not indicators themselves)."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from itertools import pairwise


def sma(values: Sequence[float], n: int) -> float | None:
    return statistics.fmean(values[-n:]) if len(values) >= n else None


def ema_series(values: Sequence[float], n: int) -> list[float]:
    """EMA seeded with the SMA of the first n values; one output per value from index n-1."""
    if len(values) < n:
        return []
    alpha = 2 / (n + 1)
    out = [statistics.fmean(values[:n])]
    for v in values[n:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def wilder_series(values: Sequence[float], n: int) -> list[float]:
    """Wilder smoothing (alpha = 1/n) seeded with the mean of the first n values; one output
    per value from index n-1."""
    if len(values) < n:
        return []
    out = [statistics.fmean(values[:n])]
    for v in values[n:]:
        out.append((out[-1] * (n - 1) + v) / n)
    return out


def log_returns(values: Sequence[float]) -> list[float]:
    return [math.log(b / a) for a, b in pairwise(values)]


def true_ranges(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> list[float]:
    """True range of every bar after the first (it needs the previous close)."""
    return [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, len(closes))
    ]


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson correlation; None when either side has no variance."""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)
