from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries
from quant_core.indicators.rsi import INDICATOR, compute

MakeSeries = Callable[..., BarSeries]


def test_rsi(series: MakeSeries) -> None:
    closes = [10, 11, 12, 11, 12, 13, 12, 13, 14, 13, 14, 15, 14, 15, 16]
    assert compute(series(closes))["rsi_14"] == pytest.approx(100 - 100 / (1 + 10 / 4))
    assert compute(series([5.0] * 20))["rsi_14"] == 50.0
    assert compute(series([1.0] * 14))["rsi_14"] is None
    assert INDICATOR.fields == {"rsi_14": 15}
