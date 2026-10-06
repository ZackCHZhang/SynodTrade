"""Simple moving averages (20/50/200) and the last close's distance from each."""

from __future__ import annotations

from quant_core.indicators._math import sma
from quant_core.indicators.base import BarSeries, Indicator, Values

PERIODS = (20, 50, 200)


def compute(s: BarSeries) -> Values:
    out: Values = {}
    last = s.closes[-1] if s.closes else None
    for n in PERIODS:
        avg = sma(s.closes, n)
        out[f"sma_{n}"] = avg
        out[f"price_vs_sma_{n}"] = last / avg - 1 if avg and last is not None else None
    return out


INDICATOR = Indicator(
    name="moving_average",
    fields={f: n for n in PERIODS for f in (f"sma_{n}", f"price_vs_sma_{n}")},
    compute=compute,
)
