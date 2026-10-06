from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, drawdown

MakeSeries = Callable[..., BarSeries]


def test_drawdown(series: MakeSeries) -> None:
    assert drawdown.max_drawdown([100.0, 120.0, 60.0, 90.0]) == pytest.approx(-0.5)
    closes = [100.0] * 200 + [120.0] * 26 + [60.0] * 26
    assert drawdown.compute(series(closes))["max_drawdown_1y"] == pytest.approx(-0.5)
    assert drawdown.compute(series([1.0] * 100))["max_drawdown_1y"] is None
