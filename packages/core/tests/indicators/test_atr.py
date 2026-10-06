from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, atr

MakeSeries = Callable[..., BarSeries]


def test_atr_constant_range(series: MakeSeries) -> None:
    out = atr.compute(series([100.0] * 20))  # every true range is 2
    assert out["atr_14"] == pytest.approx(2.0)
    assert out["atr_pct"] == pytest.approx(0.02)


def test_atr_counts_the_gap(series: MakeSeries) -> None:
    closes = [10.0] * 15 + [15.0]
    s = series(closes, highs=[11.0] * 15 + [16.0], lows=[9.0] * 15 + [14.0])
    # last true range = max(16 - 14, |16 - 10|, |14 - 10|) = 6
    assert atr.compute(s)["atr_14"] == pytest.approx((2 * 13 + 6) / 14)


def test_atr_needs_15_bars(series: MakeSeries) -> None:
    assert atr.compute(series([100.0] * 14)) == {"atr_14": None, "atr_pct": None}
