"""52-week (252-bar) high and low, and the last close's distance from each."""

from __future__ import annotations

from quant_core.indicators.base import TRADING_DAYS, BarSeries, Indicator, Values


def compute(s: BarSeries) -> Values:
    if len(s) < TRADING_DAYS:
        return dict.fromkeys(INDICATOR.fields)
    high, low = max(s.highs[-TRADING_DAYS:]), min(s.lows[-TRADING_DAYS:])
    last = s.closes[-1]
    return {
        "high_52w": high,
        "low_52w": low,
        "from_52w_high": last / high - 1,
        "from_52w_low": last / low - 1,
    }


INDICATOR = Indicator(
    name="range_52w",
    fields=dict.fromkeys(("high_52w", "low_52w", "from_52w_high", "from_52w_low"), TRADING_DAYS),
    compute=compute,
)
