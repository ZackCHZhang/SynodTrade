"""Fraction of the last 60 days that opened more than 2 ATR away from the previous close.

Each gap is compared with the ATR(14) known the evening before, so the gap itself does not
inflate its own yardstick.
"""

from __future__ import annotations

from quant_core.indicators.atr import PERIOD as ATR_PERIOD
from quant_core.indicators.atr import atr_series
from quant_core.indicators.base import BarSeries, Indicator, Values

PERIOD = 60
MULTIPLE = 2.0


def compute(s: BarSeries) -> Values:
    if len(s) < PERIOD + ATR_PERIOD + 1:
        return {"gap_freq_2atr_60d": None}
    atr = atr_series(s, ATR_PERIOD)  # atr[j] belongs to bar j + ATR_PERIOD
    big = 0
    for i in range(len(s) - PERIOD, len(s)):
        prior_atr = atr[i - 1 - ATR_PERIOD]
        if abs(s.opens[i] - s.closes[i - 1]) > MULTIPLE * prior_atr:
            big += 1
    return {"gap_freq_2atr_60d": big / PERIOD}


INDICATOR = Indicator(
    name="gap_frequency",
    fields={"gap_freq_2atr_60d": PERIOD + ATR_PERIOD + 1},
    compute=compute,
)
