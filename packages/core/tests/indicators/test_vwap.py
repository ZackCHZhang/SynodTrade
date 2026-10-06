from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, vwap

MakeSeries = Callable[..., BarSeries]


def test_vwap(series: MakeSeries) -> None:
    prices = [10.0] * 15 + [10.0, 11.0, 12.0, 13.0, 14.0]
    volumes = [1.0] * 15 + [1.0, 2.0, 3.0, 4.0, 5.0]
    out = vwap.compute(series(prices, spread=0.0, volumes=volumes))
    assert out["vwap_5d"] == pytest.approx((10 + 22 + 36 + 52 + 70) / 15)
    expected_20 = (150 + 10 + 22 + 36 + 52 + 70) / (15 + 15)
    assert out["vwap_20d"] == pytest.approx(expected_20)
    assert out["price_vs_vwap_20d"] == pytest.approx(14 / expected_20 - 1)
    assert out["vwap_60d"] is None


def test_no_volume(series: MakeSeries) -> None:
    assert vwap.compute(series([10.0] * 5, volumes=[0.0] * 5))["vwap_5d"] is None
