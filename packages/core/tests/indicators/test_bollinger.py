import math
from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, bollinger

MakeSeries = Callable[..., BarSeries]


def test_bollinger(series: MakeSeries) -> None:
    out = bollinger.compute(series(range(1, 21)))
    sd = math.sqrt(35)
    assert out["bollinger_pct_b_20"] == pytest.approx((20 - (10.5 - 2 * sd)) / (4 * sd))
    assert out["bollinger_width_20"] == pytest.approx(4 * sd / 10.5)
    assert bollinger.compute(series([5.0] * 20))["bollinger_pct_b_20"] is None
