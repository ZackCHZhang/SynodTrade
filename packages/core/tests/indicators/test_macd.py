from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, macd

MakeSeries = Callable[..., BarSeries]


def test_macd_needs_history(series: MakeSeries) -> None:
    rising = series(range(1, 60))
    out = macd.compute(rising)
    line, signal = out["macd"], out["macd_signal"]
    assert line is not None
    assert signal is not None
    assert line > 0
    assert out["macd_histogram"] == pytest.approx(line - signal)
    short = macd.compute(series(range(1, 30)))  # 29 bars: MACD yes, signal (34) no
    assert short["macd"] is not None
    assert short["macd_signal"] is None
