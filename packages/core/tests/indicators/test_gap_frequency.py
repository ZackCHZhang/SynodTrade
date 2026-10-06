from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, gap_frequency

MakeSeries = Callable[..., BarSeries]


def test_big_gaps_are_counted(series: MakeSeries) -> None:
    n = 75
    opens, highs, lows = [100.0] * n, [101.0] * n, [99.0] * n  # ATR 2 before the gaps
    for i in (n - 3, n - 2, n - 1):  # three days open at 106, then fall back to 100
        opens[i], highs[i] = 106.0, 106.0
    s = series([100.0] * n, opens=opens, highs=highs, lows=lows)
    # gap 6 vs 2 ATR of the previous evening: 4, then 4.71, then 5.38 -> all three count
    assert gap_frequency.compute(s)["gap_freq_2atr_60d"] == pytest.approx(3 / 60)


def test_needs_75_bars(series: MakeSeries) -> None:
    assert gap_frequency.compute(series([100.0] * 74))["gap_freq_2atr_60d"] is None
