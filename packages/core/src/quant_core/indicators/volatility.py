"""Annualised close-to-close volatility from daily log returns (20 and 60 days)."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

from quant_core.indicators._math import log_returns
from quant_core.indicators.base import TRADING_DAYS, BarSeries, Indicator, Values


def annualised_volatility(values: Sequence[float], n: int) -> float | None:
    if len(values) < n + 1:
        return None
    return statistics.stdev(log_returns(values[-(n + 1) :])) * math.sqrt(TRADING_DAYS)


def compute(s: BarSeries) -> Values:
    return {
        "volatility_20d": annualised_volatility(s.closes, 20),
        "volatility_60d": annualised_volatility(s.closes, 60),
    }


INDICATOR = Indicator(
    name="volatility",
    fields={"volatility_20d": 21, "volatility_60d": 61},
    compute=compute,
)
