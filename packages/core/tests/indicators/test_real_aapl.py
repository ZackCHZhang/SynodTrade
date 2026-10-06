"""Regression test on real IBKR data: 299 completed AAPL daily bars (2025-07-29 .. 2026-10-05).

Expected values were cross-checked against an independent pandas implementation.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from quant_core.indicators import compute_indicators, indicator_rows
from quant_core.models import Bar, Timeframe

DATA = Path(__file__).parent / "data" / "aapl_daily_ibkr.json"


def aapl_bars() -> list[Bar]:
    raw: dict[str, Any] = json.loads(DATA.read_text())
    start = datetime(2025, 7, 29, 4, tzinfo=UTC)
    return [
        Bar(
            symbol="AAPL",
            timeframe=Timeframe.D1,
            ts=start + timedelta(days=i),
            open=Decimal(str(o)),
            high=Decimal(str(h)),
            low=Decimal(str(lo)),
            close=Decimal(str(c)),
            volume=Decimal(v),
        )
        for i, (o, h, lo, c, v) in enumerate(
            zip(raw["open"], raw["high"], raw["low"], raw["close"], raw["volume"], strict=True)
        )
    ]


EXPECTED = {
    "last_close": 332.89,
    "return_250d": 0.296856,
    "volatility_20d": 0.209127,
    "volatility_60d": 0.275091,
    "parkinson_vol_20d": 0.197547,
    "atr_14": 6.854657,
    "zscore_20": 0.051254,
    "bollinger_pct_b_20": 0.512814,
    "rsi_14": 53.789320,
    "macd": 3.483823,
    "macd_signal": 4.552864,
    "adx_14": 16.701481,
    "plus_di_14": 26.592789,
    "minus_di_14": 22.184369,
    "high_52w": 345.34,
    "low_52w": 243.42,
    "max_drawdown_1y": -0.138230,
    "gap_variance_share_60d": 0.517149,
    "max_gap_60d": -0.086165,
    "gap_freq_2atr_60d": 1 / 60,
    "updown_volume_ratio_10d": 1.130596,
    "obv_trend_20d": 0.056627,
    "obv_from_high_250d": -0.009197,
    "vwap_20d": 330.751100,
    "vwap_60d": 322.161705,
    "return_volume_corr_20d": -0.076158,
}


def test_real_aapl_values() -> None:
    snap = compute_indicators(aapl_bars())
    assert snap.bars_used == 299
    assert snap.warnings == ()
    for field, value in EXPECTED.items():
        assert getattr(snap, field) == pytest.approx(value, abs=5e-6), field


def test_real_aapl_prompt_rows() -> None:
    rows = {r["field"]: r["value"] for r in indicator_rows(compute_indicators(aapl_bars()))}
    assert rows["atr_pct"] == "+2.06%"
    assert rows["adx_14"] == "16.7"
    assert rows["amihud_illiquidity_20d"] == "1.27e-06"
