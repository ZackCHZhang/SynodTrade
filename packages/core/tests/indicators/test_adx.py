from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, adx

MakeSeries = Callable[..., BarSeries]


def test_steady_uptrend_is_a_full_trend(series: MakeSeries) -> None:
    # every day: high and low up by 1 -> +DM 1, -DM 0, true range 2
    out = adx.compute(series([float(i) for i in range(100, 130)]))
    assert out["plus_di_14"] == pytest.approx(50.0)
    assert out["minus_di_14"] == pytest.approx(0.0)
    assert out["adx_14"] == pytest.approx(100.0)


def test_adx_needs_28_bars(series: MakeSeries) -> None:
    out = adx.compute(series([float(i) for i in range(100, 127)]))  # 27 bars
    assert out["plus_di_14"] is not None
    assert out["adx_14"] is None


def test_no_range_is_degenerate(series: MakeSeries) -> None:
    out = adx.compute(series([100.0] * 40, spread=0.0))
    assert out == {"adx_14": None, "plus_di_14": None, "minus_di_14": None}
