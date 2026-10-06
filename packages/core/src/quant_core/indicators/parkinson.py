"""Parkinson volatility (20 days, annualised) from each bar's high/low range.

It only sees intraday ranges, not overnight gaps; compare it with the close-to-close
`volatility_20d` to see how much of the risk comes from gaps.
"""

from __future__ import annotations

import math
import statistics

from quant_core.indicators.base import TRADING_DAYS, BarSeries, Indicator, Values

PERIOD = 20


def compute(s: BarSeries) -> Values:
    if len(s) < PERIOD:
        return {"parkinson_vol_20d": None}
    sq = [math.log(h / lo) ** 2 for h, lo in zip(s.highs[-PERIOD:], s.lows[-PERIOD:], strict=True)]
    return {
        "parkinson_vol_20d": math.sqrt(statistics.fmean(sq) / (4 * math.log(2)))
        * math.sqrt(TRADING_DAYS)
    }


INDICATOR = Indicator(name="parkinson", fields={"parkinson_vol_20d": PERIOD}, compute=compute)
