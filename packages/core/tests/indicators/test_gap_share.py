from collections.abc import Callable

import pytest

from quant_core.indicators import BarSeries, gap_share

MakeSeries = Callable[..., BarSeries]


def test_no_gaps(series: MakeSeries) -> None:
    closes = [100.0 + (i % 2) for i in range(61)]
    opens = [closes[0], *closes[:-1]]  # every day opens at the previous close
    s = series(closes, opens=opens, highs=[102.0] * 61, lows=[99.0] * 61)
    assert gap_share.compute(s)["gap_variance_share_60d"] == pytest.approx(0.0)


def test_only_gaps(series: MakeSeries) -> None:
    closes = [100.0 + (i % 2) for i in range(61)]  # opens equal closes: all movement is gaps
    assert gap_share.compute(series(closes))["gap_variance_share_60d"] == pytest.approx(1.0)


def test_degenerate_and_short(series: MakeSeries) -> None:
    assert gap_share.compute(series([100.0] * 61))["gap_variance_share_60d"] is None
    assert gap_share.compute(series([100.0] * 60))["gap_variance_share_60d"] is None
