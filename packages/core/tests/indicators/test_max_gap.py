from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, max_gap

MakeSeries = Callable[..., BarSeries]


def test_largest_gap_keeps_its_sign(series: MakeSeries) -> None:
    closes = [100.0] * 61
    opens = [100.0] * 61
    opens[30], opens[50] = 105.0, 92.0  # +5% and -8%
    s = series(closes, opens=opens, highs=[106.0] * 61, lows=[91.0] * 61)
    assert max_gap.compute(s)["max_gap_60d"] == pytest.approx(-0.08)
    assert max_gap.compute(series([100.0] * 60))["max_gap_60d"] is None
