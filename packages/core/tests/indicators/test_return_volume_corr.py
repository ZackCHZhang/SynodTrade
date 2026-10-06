from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, return_volume_corr

MakeSeries = Callable[..., BarSeries]


def test_volume_confirms_moves(series: MakeSeries) -> None:
    closes = [100.0 + (i % 2) for i in range(21)]  # up, down, up, ...
    volumes = [200.0 if i % 2 else 100.0 for i in range(21)]  # volume up on up days
    out = return_volume_corr.compute(series(closes, volumes=volumes))
    assert out["return_volume_corr_20d"] == pytest.approx(1.0)


def test_zero_volume_is_degenerate(series: MakeSeries) -> None:
    closes = [100.0 + (i % 2) for i in range(21)]
    volumes = [0.0] + [100.0] * 20
    assert (
        return_volume_corr.compute(series(closes, volumes=volumes))["return_volume_corr_20d"]
        is None
    )
