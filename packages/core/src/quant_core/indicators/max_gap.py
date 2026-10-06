"""Largest overnight gap of the last 60 days (open / previous close - 1, keeps its sign)."""

from __future__ import annotations

from quant_core.indicators.base import BarSeries, Indicator, Values

PERIOD = 60


def compute(s: BarSeries) -> Values:
    if len(s) < PERIOD + 1:
        return {"max_gap_60d": None}
    gaps = [s.opens[i] / s.closes[i - 1] - 1 for i in range(len(s) - PERIOD, len(s))]
    return {"max_gap_60d": max(gaps, key=abs)}


INDICATOR = Indicator(name="max_gap", fields={"max_gap_60d": PERIOD + 1}, compute=compute)
