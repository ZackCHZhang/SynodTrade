import math
from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, parkinson

MakeSeries = Callable[..., BarSeries]


def test_parkinson(series: MakeSeries) -> None:
    s = series([100.0] * 20, highs=[102.0] * 20, lows=[98.0] * 20)
    expected = math.log(102 / 98) / math.sqrt(4 * math.log(2)) * math.sqrt(252)
    assert parkinson.compute(s)["parkinson_vol_20d"] == pytest.approx(expected)
    assert parkinson.compute(series([100.0] * 19))["parkinson_vol_20d"] is None
