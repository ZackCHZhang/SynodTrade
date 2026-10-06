from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, volume_ratio

MakeSeries = Callable[..., BarSeries]


def test_volume_ratio(series: MakeSeries) -> None:
    out = volume_ratio.compute(series([10.0] * 21, volumes=[10.0] * 20 + [20.0]))
    assert out["volume_ratio_20d"] == pytest.approx(2.0)
    zero = volume_ratio.compute(series([10.0] * 21, volumes=[0.0] * 21))
    assert zero["volume_ratio_20d"] is None
