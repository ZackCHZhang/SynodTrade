"""Simple returns over 1, 5, 20, 60, 120 and 250 bars."""

from __future__ import annotations

from collections.abc import Sequence

from quant_core.indicators.base import BarSeries, Indicator, Values

PERIODS = (1, 5, 20, 60, 120, 250)


def pct_change(values: Sequence[float], n: int) -> float | None:
    if len(values) <= n or values[-1 - n] == 0:
        return None
    return values[-1] / values[-1 - n] - 1


def compute(s: BarSeries) -> Values:
    return {f"return_{n}d": pct_change(s.closes, n) for n in PERIODS}


INDICATOR = Indicator(
    name="returns",
    fields={f"return_{n}d": n + 1 for n in PERIODS},
    compute=compute,
)
