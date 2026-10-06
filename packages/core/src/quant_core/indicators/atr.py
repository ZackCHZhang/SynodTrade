"""Average True Range, 14 periods, Wilder smoothing; also as a fraction of the last close.

The true range includes the gap from the previous close, so overnight jumps count.
"""

from __future__ import annotations

from quant_core.indicators._math import true_ranges, wilder_series
from quant_core.indicators.base import BarSeries, Indicator, Values

PERIOD = 14


def atr_series(s: BarSeries, n: int = PERIOD) -> list[float]:
    """ATR for every bar from index n on (bar i uses the true ranges of bars 1..i)."""
    return wilder_series(true_ranges(s.highs, s.lows, s.closes), n)


def compute(s: BarSeries) -> Values:
    series = atr_series(s)
    if not series:
        return {"atr_14": None, "atr_pct": None}
    atr = series[-1]
    return {"atr_14": atr, "atr_pct": atr / s.closes[-1]}


INDICATOR = Indicator(
    name="atr", fields={"atr_14": PERIOD + 1, "atr_pct": PERIOD + 1}, compute=compute
)
