"""Bollinger Bands (20, 2σ): %b (0 = lower band, 1 = upper band) and band width / SMA."""

from __future__ import annotations

import statistics

from quant_core.indicators.base import BarSeries, Indicator, Values

PERIOD = 20
WIDTH = 2.0


def compute(s: BarSeries) -> Values:
    if len(s) < PERIOD:
        return {"bollinger_pct_b_20": None, "bollinger_width_20": None}
    window = s.closes[-PERIOD:]
    mid, sd = statistics.fmean(window), statistics.stdev(window)
    if sd == 0:
        return {"bollinger_pct_b_20": None, "bollinger_width_20": None}
    lower, upper = mid - WIDTH * sd, mid + WIDTH * sd
    return {
        "bollinger_pct_b_20": (window[-1] - lower) / (upper - lower),
        "bollinger_width_20": (upper - lower) / mid,
    }


INDICATOR = Indicator(
    name="bollinger",
    fields={"bollinger_pct_b_20": PERIOD, "bollinger_width_20": PERIOD},
    compute=compute,
    degenerate_hint="the last 20 closes are all equal",
)
