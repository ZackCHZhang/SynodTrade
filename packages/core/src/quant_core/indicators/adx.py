"""Average Directional Index (14) with +DI / -DI, Wilder's method.

+DI / -DI need 14 true ranges (15 bars); ADX smooths 14 DX values on top (28 bars).
ADX below ~20 usually means no trend, above ~25 a trend; the DIs give its direction.
"""

from __future__ import annotations

from quant_core.indicators._math import true_ranges, wilder_series
from quant_core.indicators.base import BarSeries, Indicator, Values

PERIOD = 14


def compute(s: BarSeries) -> Values:
    out: Values = {"adx_14": None, "plus_di_14": None, "minus_di_14": None}
    n = PERIOD
    trs = true_ranges(s.highs, s.lows, s.closes)
    plus_dm, minus_dm = [], []
    for i in range(1, len(s)):
        up, down = s.highs[i] - s.highs[i - 1], s.lows[i - 1] - s.lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    tr_s, pdm_s, mdm_s = (
        wilder_series(trs, n),
        wilder_series(plus_dm, n),
        wilder_series(minus_dm, n),
    )
    if not tr_s:
        return out
    dx: list[float] = []
    plus_di = minus_di = None
    for tr, pdm, mdm in zip(tr_s, pdm_s, mdm_s, strict=True):
        if tr == 0:
            plus_di = minus_di = None
            continue
        plus_di, minus_di = 100 * pdm / tr, 100 * mdm / tr
        total = plus_di + minus_di
        dx.append(0.0 if total == 0 else 100 * abs(plus_di - minus_di) / total)
    out["plus_di_14"], out["minus_di_14"] = plus_di, minus_di
    adx = wilder_series(dx, n)
    out["adx_14"] = adx[-1] if adx else None
    return out


INDICATOR = Indicator(
    name="adx",
    fields={"adx_14": 2 * PERIOD, "plus_di_14": PERIOD + 1, "minus_di_14": PERIOD + 1},
    compute=compute,
    degenerate_hint="no price range (high equals low) in the window",
)
