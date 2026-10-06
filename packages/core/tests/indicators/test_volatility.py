import math
from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, volatility

MakeSeries = Callable[..., BarSeries]


def test_volatility(series: MakeSeries) -> None:
    out = volatility.compute(series([100.0, 110.0] * 31))
    expected = math.log(1.1) * math.sqrt(20 / 19) * math.sqrt(252)  # stdev of ±log(1.1)
    assert out["volatility_20d"] == pytest.approx(expected)
    assert out["volatility_60d"] is not None
    assert volatility.compute(series([100.0] * 10))["volatility_20d"] is None
    assert volatility.annualised_volatility([100.0] * 30, 20) == 0.0
