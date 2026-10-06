from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, updown_volume

MakeSeries = Callable[..., BarSeries]


def test_ratio(series: MakeSeries) -> None:
    closes = [100.0 + (i % 2) for i in range(11)]  # alternating up / down
    volumes = [200.0 if i % 2 else 100.0 for i in range(11)]  # up days 200, down days 100
    out = updown_volume.compute(series(closes, volumes=volumes))
    assert out["updown_volume_ratio_10d"] == pytest.approx(2.0)


def test_only_up_days_is_degenerate(series: MakeSeries) -> None:
    assert updown_volume.compute(series(range(1, 12)))["updown_volume_ratio_10d"] is None
