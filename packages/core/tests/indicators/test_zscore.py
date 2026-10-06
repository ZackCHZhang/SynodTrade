import math
from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, zscore

MakeSeries = Callable[..., BarSeries]


def test_zscore(series: MakeSeries) -> None:
    out = zscore.compute(series(range(1, 21)))  # mean 10.5, sample variance 35
    assert out["zscore_20"] == pytest.approx((20 - 10.5) / math.sqrt(35))


def test_flat_prices_are_degenerate(series: MakeSeries) -> None:
    assert zscore.compute(series([5.0] * 20))["zscore_20"] is None
    assert zscore.compute(series([5.0] * 19))["zscore_20"] is None
