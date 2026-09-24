import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quant_core.indicators import (
    annualised_volatility,
    compute_indicators,
    ema_series,
    max_drawdown,
    pct_change,
    rsi,
    sma,
)
from quant_core.models import Bar, Timeframe


def make_bars(symbol: str, closes: Sequence[float]) -> list[Bar]:
    start = datetime(2025, 1, 1, 5, 0, tzinfo=UTC)
    out = []
    for i, c in enumerate(closes):
        close = Decimal(str(c))
        out.append(
            Bar(
                symbol=symbol,
                timeframe=Timeframe.D1,
                ts=start + timedelta(days=i),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=Decimal(1000 + i),
            )
        )
    return out


def test_basic_helpers() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert pct_change(values, 1) == pytest.approx(0.25)
    assert pct_change(values, 4) == pytest.approx(4.0)
    assert pct_change(values, 5) is None
    assert pct_change([0.0, 1.0], 1) is None
    assert sma(values, 2) == 4.5
    assert sma(values, 6) is None
    assert ema_series(values, 3) == pytest.approx([2.0, 3.0, 4.0])  # seed 2, alpha 0.5
    assert ema_series(values, 6) == []


def test_rsi() -> None:
    rising = [float(i) for i in range(1, 30)]
    assert rsi(rising) == 100.0
    assert rsi([5.0] * 20) == 50.0
    zigzag = [10.0 + (i % 2) for i in range(15)]  # 14 changes: 7 gains, 7 losses
    assert rsi(zigzag) == pytest.approx(50.0)
    falling = [float(i) for i in range(40, 10, -1)]
    assert rsi(falling) == pytest.approx(0.0)
    assert rsi([1.0] * 14) is None


def test_rsi_matches_hand_computation() -> None:
    # 15 closes -> 14 changes: gains sum 10, losses sum 4 -> RS 2.5 -> RSI 71.43
    closes = [10, 11, 12, 11, 12, 13, 12, 13, 14, 13, 14, 15, 14, 15, 16]
    assert rsi([float(c) for c in closes]) == pytest.approx(100 - 100 / (1 + 10 / 4))


def test_volatility_and_drawdown() -> None:
    assert annualised_volatility([100.0] * 30, 20) == 0.0
    assert annualised_volatility([100.0] * 10, 20) is None
    alternating = [100.0, 110.0] * 15
    expected = math.log(1.1) * math.sqrt(20 / 19) * math.sqrt(252)  # stdev of ±log(1.1)
    assert annualised_volatility(alternating, 20) == pytest.approx(expected)
    assert max_drawdown([100.0, 120.0, 60.0, 90.0]) == pytest.approx(-0.5)
    assert max_drawdown([1.0, 2.0, 3.0]) == 0.0
    assert max_drawdown([1.0]) is None


def test_compute_indicators_full_history() -> None:
    closes = [100 + i for i in range(300)]  # steady uptrend 100..399
    bars = make_bars("AAPL", closes)
    snap = compute_indicators(bars)
    assert snap.bars_used == 300
    assert snap.last_close == 399
    assert snap.return_1d == pytest.approx(399 / 398 - 1)
    assert snap.return_250d == pytest.approx(399 / 149 - 1)
    assert snap.sma_20 == pytest.approx(389.5)
    assert snap.price_vs_sma_20 == pytest.approx(399 / 389.5 - 1)
    assert snap.sma_200 == pytest.approx(299.5)
    assert snap.rsi_14 == 100.0
    assert snap.macd is not None
    assert snap.macd > 0
    assert snap.macd_signal is not None
    assert snap.macd_histogram == pytest.approx(snap.macd - snap.macd_signal)
    assert snap.high_52w == 400  # highs are close + 1
    assert snap.low_52w == 147  # lowest low in the last 252 bars (close 148 - 1)
    assert snap.from_52w_high == pytest.approx(399 / 400 - 1)
    assert snap.max_drawdown_1y == 0.0
    assert snap.volume_ratio_20d == pytest.approx(1299 / (sum(range(1279, 1299)) / 20))
    assert snap.last_bar_ts == bars[-1].ts


def test_compute_indicators_short_history() -> None:
    snap = compute_indicators(make_bars("X", [10, 11, 12]))
    assert snap.bars_used == 3
    assert snap.return_1d == pytest.approx(12 / 11 - 1)
    assert snap.return_5d is None
    assert snap.sma_20 is None
    assert snap.price_vs_sma_20 is None
    assert snap.rsi_14 is None
    assert snap.macd is None
    assert snap.high_52w is None
    assert snap.volume_ratio_20d is None
    empty = compute_indicators([])
    assert empty.bars_used == 0
    assert empty.last_close is None
