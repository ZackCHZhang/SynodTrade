"""Share of the last 60 days' price variation that came from overnight gaps.

Each day's log return splits into the gap ln(open / previous close) and the session move
ln(close / open); the share is Σgap² / (Σgap² + Σsession²). Near 0: risk is intraday
(stops can work); high: risk arrives at the open, where stops do not protect.
"""

from __future__ import annotations

import math

from quant_core.indicators.base import BarSeries, Indicator, Values

PERIOD = 60


def compute(s: BarSeries) -> Values:
    if len(s) < PERIOD + 1:
        return {"gap_variance_share_60d": None}
    gap_sq = session_sq = 0.0
    for i in range(len(s) - PERIOD, len(s)):
        gap_sq += math.log(s.opens[i] / s.closes[i - 1]) ** 2
        session_sq += math.log(s.closes[i] / s.opens[i]) ** 2
    total = gap_sq + session_sq
    return {"gap_variance_share_60d": gap_sq / total if total > 0 else None}


INDICATOR = Indicator(
    name="gap_share",
    fields={"gap_variance_share_60d": PERIOD + 1},
    compute=compute,
    degenerate_hint="no price change at all in the last 60 days",
)
