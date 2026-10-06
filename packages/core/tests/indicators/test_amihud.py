from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, amihud

MakeSeries = Callable[..., BarSeries]


def test_amihud(series: MakeSeries) -> None:
    closes = [100 * 1.01**i for i in range(21)]  # +1% every day
    volumes = [1e6 / c for c in closes]  # USD 1M traded every day
    out = amihud.compute(series(closes, volumes=volumes))
    assert out["amihud_illiquidity_20d"] == pytest.approx(0.01)


def test_no_volume(series: MakeSeries) -> None:
    assert (
        amihud.compute(series(range(1, 22), volumes=[0.0] * 21))["amihud_illiquidity_20d"] is None
    )
