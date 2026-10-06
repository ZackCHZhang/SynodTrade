"""Correlation of daily log returns with daily log-volume changes over 20 days (-1..1).

Positive: rises come with rising volume and falls with falling volume (a healthy, volume-
confirmed move); near zero or negative: price moves without volume confirmation.
"""

from __future__ import annotations

import math
from itertools import pairwise

from quant_core.indicators._math import log_returns, pearson
from quant_core.indicators.base import BarSeries, Indicator, Values

PERIOD = 20


def compute(s: BarSeries) -> Values:
    if len(s) < PERIOD + 1:
        return {"return_volume_corr_20d": None}
    closes, volumes = s.closes[-PERIOD - 1 :], s.volumes[-PERIOD - 1 :]
    if any(v <= 0 for v in volumes):
        return {"return_volume_corr_20d": None}
    volume_changes = [math.log(b / a) for a, b in pairwise(volumes)]
    return {"return_volume_corr_20d": pearson(log_returns(closes), volume_changes)}


INDICATOR = Indicator(
    name="return_volume_corr",
    fields={"return_volume_corr_20d": PERIOD + 1},
    compute=compute,
    degenerate_hint="a day without volume, or no variation in price or volume",
)
