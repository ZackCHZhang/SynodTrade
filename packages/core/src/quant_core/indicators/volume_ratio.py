"""Last bar's volume relative to the average of the previous 20 bars."""

from __future__ import annotations

from quant_core.indicators._math import sma
from quant_core.indicators.base import BarSeries, Indicator, Values


def compute(s: BarSeries) -> Values:
    prior = sma(s.volumes[:-1], 20)
    return {"volume_ratio_20d": s.volumes[-1] / prior if prior else None}


INDICATOR = Indicator(
    name="volume_ratio",
    fields={"volume_ratio_20d": 21},
    compute=compute,
    degenerate_hint="no volume in the previous 20 bars",
)
