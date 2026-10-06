from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, obv

MakeSeries = Callable[..., BarSeries]


def test_obv_rising(series: MakeSeries) -> None:
    out = obv.compute(series([float(i) for i in range(1, 260)]))
    assert out["obv_trend_20d"] == pytest.approx(1.0)  # all volume on up days
    assert out["obv_from_high_250d"] == pytest.approx(0.0)  # OBV at its high


def test_obv_below_its_high(series: MakeSeries) -> None:
    closes = [float(i) for i in range(1, 231)] + [float(i) for i in range(229, 208, -1)]
    out = obv.compute(series(closes))  # 251 bars, the last 21 falling
    assert out["obv_trend_20d"] == pytest.approx(-1.0)
    assert out["obv_from_high_250d"] == pytest.approx(-21 * 1000 / (250 * 1000))


def test_obv_short_and_no_volume(series: MakeSeries) -> None:
    out = obv.compute(series([1.0, 2.0, 3.0] * 10))
    assert out["obv_from_high_250d"] is None
    assert obv.compute(series(range(1, 30), volumes=[0.0] * 29))["obv_trend_20d"] is None
