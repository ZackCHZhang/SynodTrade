"""Z-score of the last close against the last 20 closes: (close - SMA20) / stdev20."""

from __future__ import annotations

import statistics

from quant_core.indicators.base import BarSeries, Indicator, Values

PERIOD = 20


def compute(s: BarSeries) -> Values:
    if len(s) < PERIOD:
        return {"zscore_20": None}
    window = s.closes[-PERIOD:]
    sd = statistics.stdev(window)
    if sd == 0:
        return {"zscore_20": None}
    return {"zscore_20": (window[-1] - statistics.fmean(window)) / sd}


INDICATOR = Indicator(
    name="zscore",
    fields={"zscore_20": PERIOD},
    compute=compute,
    degenerate_hint="the last 20 closes are all equal",
)
