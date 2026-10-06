"""Amihud illiquidity over 20 days: average |daily return| per USD 1 million traded.

Higher = each dollar traded moves the price more (less liquid). Days without volume are
skipped.
"""

from __future__ import annotations

import statistics

from quant_core.indicators.base import BarSeries, Indicator, Values

PERIOD = 20


def compute(s: BarSeries) -> Values:
    if len(s) < PERIOD + 1:
        return {"amihud_illiquidity_20d": None}
    ratios = []
    for i in range(len(s) - PERIOD, len(s)):
        dollar_volume = s.closes[i] * s.volumes[i]
        if dollar_volume > 0:
            ratios.append(abs(s.closes[i] / s.closes[i - 1] - 1) / dollar_volume * 1e6)
    return {"amihud_illiquidity_20d": statistics.fmean(ratios) if ratios else None}


INDICATOR = Indicator(
    name="amihud",
    fields={"amihud_illiquidity_20d": PERIOD + 1},
    compute=compute,
    degenerate_hint="no volume in the last 20 days",
)
