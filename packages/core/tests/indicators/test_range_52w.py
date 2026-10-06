from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, range_52w

MakeSeries = Callable[..., BarSeries]


def test_52_week_range(series: MakeSeries) -> None:
    out = range_52w.compute(series([100 + i for i in range(300)]))
    assert out["high_52w"] == 400  # highs are close + 1
    assert out["low_52w"] == 147  # lowest low in the last 252 bars
    assert out["from_52w_high"] == pytest.approx(399 / 400 - 1)
    assert range_52w.compute(series([1.0] * 251))["high_52w"] is None
