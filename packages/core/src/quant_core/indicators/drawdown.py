"""Largest peak-to-trough fall of the close over the last year (a negative ratio)."""

from __future__ import annotations

from collections.abc import Sequence

from quant_core.indicators.base import TRADING_DAYS, BarSeries, Indicator, Values


def max_drawdown(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def compute(s: BarSeries) -> Values:
    if len(s) < TRADING_DAYS:
        return {"max_drawdown_1y": None}
    return {"max_drawdown_1y": max_drawdown(s.closes[-TRADING_DAYS:])}


INDICATOR = Indicator(name="drawdown", fields={"max_drawdown_1y": TRADING_DAYS}, compute=compute)
