from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, returns

MakeSeries = Callable[..., BarSeries]


def test_returns(series: MakeSeries) -> None:
    out = returns.compute(series([1, 2, 3, 4, 5, 6]))
    assert out["return_1d"] == pytest.approx(6 / 5 - 1)
    assert out["return_5d"] == pytest.approx(6 / 1 - 1)
    assert out["return_20d"] is None
    assert returns.INDICATOR.fields["return_250d"] == 251


def test_pct_change_guards() -> None:
    assert returns.pct_change([0.0, 1.0], 1) is None
    assert returns.pct_change([1.0], 1) is None
