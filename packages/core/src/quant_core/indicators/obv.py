"""On-Balance Volume (OBV): volume added on up closes, subtracted on down closes.

Raw OBV depends on the starting point, so two normalised views are reported:
- `obv_trend_20d`: OBV change over 20 days / total volume of those days (-1..1);
  near +1 = almost all volume on up days.
- `obv_from_high_250d`: (OBV now - its highest value of the last 250 days) / total volume of
  those days (<= 0; 0 = OBV at a new high). A price at a 52-week high with OBV well below its
  own high is a classic volume divergence.
"""

from __future__ import annotations

from quant_core.indicators.base import BarSeries, Indicator, Values

TREND_PERIOD = 20
HIGH_PERIOD = 250


def obv_series(s: BarSeries) -> list[float]:
    out = [0.0]
    for i in range(1, len(s)):
        change = s.closes[i] - s.closes[i - 1]
        out.append(out[-1] + (s.volumes[i] if change > 0 else -s.volumes[i] if change < 0 else 0))
    return out


def compute(s: BarSeries) -> Values:
    out: Values = {"obv_trend_20d": None, "obv_from_high_250d": None}
    if len(s) < TREND_PERIOD + 1:
        return out
    obv = obv_series(s)
    vol = sum(s.volumes[-TREND_PERIOD:])
    if vol > 0:
        out["obv_trend_20d"] = (obv[-1] - obv[-1 - TREND_PERIOD]) / vol
    if len(s) >= HIGH_PERIOD + 1:
        vol = sum(s.volumes[-HIGH_PERIOD:])
        if vol > 0:
            out["obv_from_high_250d"] = (obv[-1] - max(obv[-HIGH_PERIOD - 1 :])) / vol
    return out


INDICATOR = Indicator(
    name="obv",
    fields={"obv_trend_20d": TREND_PERIOD + 1, "obv_from_high_250d": HIGH_PERIOD + 1},
    compute=compute,
    degenerate_hint="no volume in the window",
)
