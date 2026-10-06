from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, moving_average

MakeSeries = Callable[..., BarSeries]


def test_sma_and_distance(series: MakeSeries) -> None:
    out = moving_average.compute(series(range(1, 21)))
    assert out["sma_20"] == pytest.approx(10.5)
    assert out["price_vs_sma_20"] == pytest.approx(20 / 10.5 - 1)
    assert out["sma_50"] is None
    assert out["price_vs_sma_50"] is None
