"""MACD (EMA 12 - EMA 26), its 9-period signal line and the histogram."""

from __future__ import annotations

from quant_core.indicators._math import ema_series
from quant_core.indicators.base import BarSeries, Indicator, Values


def compute(s: BarSeries) -> Values:
    ema12, ema26 = ema_series(s.closes, 12), ema_series(s.closes, 26)
    line: list[float] = []
    if ema26:
        offset = len(ema12) - len(ema26)
        line = [a - b for a, b in zip(ema12[offset:], ema26, strict=True)]
    signal = ema_series(line, 9)
    return {
        "macd": line[-1] if line else None,
        "macd_signal": signal[-1] if signal else None,
        "macd_histogram": line[-1] - signal[-1] if signal else None,
    }


INDICATOR = Indicator(
    name="macd",
    fields={"macd": 26, "macd_signal": 34, "macd_histogram": 34},
    compute=compute,
)
