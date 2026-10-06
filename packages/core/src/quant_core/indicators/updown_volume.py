"""Average volume on up days divided by average volume on down days (last 10 days).

Above 1: buyers are more active than sellers; below 1: selling happens on heavier volume.
"""

from __future__ import annotations

import statistics

from quant_core.indicators.base import BarSeries, Indicator, Values

PERIOD = 10


def compute(s: BarSeries) -> Values:
    if len(s) < PERIOD + 1:
        return {"updown_volume_ratio_10d": None}
    up, down = [], []
    for i in range(len(s) - PERIOD, len(s)):
        if s.closes[i] > s.closes[i - 1]:
            up.append(s.volumes[i])
        elif s.closes[i] < s.closes[i - 1]:
            down.append(s.volumes[i])
    if not up or not down or statistics.fmean(down) == 0:
        return {"updown_volume_ratio_10d": None}
    return {"updown_volume_ratio_10d": statistics.fmean(up) / statistics.fmean(down)}


INDICATOR = Indicator(
    name="updown_volume",
    fields={"updown_volume_ratio_10d": PERIOD + 1},
    compute=compute,
    degenerate_hint="the last 10 days had no up day, no down day, or no down-day volume",
)
