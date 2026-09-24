"""Technical indicators computed in code (the LLM is never asked to do arithmetic).

Indicators are informational statistics for the prompt, not money amounts, so they are
computed in float. Every indicator is None when there is not enough history for it.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from datetime import datetime
from itertools import pairwise

from pydantic import BaseModel, ConfigDict

from quant_core.models import Bar

TRADING_DAYS = 252


class TechnicalSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bars_used: int
    last_bar_ts: datetime | None = None
    last_close: float | None = None
    return_1d: float | None = None
    return_5d: float | None = None
    return_20d: float | None = None
    return_60d: float | None = None
    return_120d: float | None = None
    return_250d: float | None = None
    volatility_20d: float | None = None  # annualised, from daily log returns
    volatility_60d: float | None = None
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    price_vs_sma_20: float | None = None  # close / SMA - 1
    price_vs_sma_50: float | None = None
    price_vs_sma_200: float | None = None
    rsi_14: float | None = None  # Wilder, 0..100
    macd: float | None = None  # EMA12 - EMA26
    macd_signal: float | None = None  # EMA9 of MACD
    macd_histogram: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    from_52w_high: float | None = None  # close / 52w high - 1 (<= 0)
    from_52w_low: float | None = None  # close / 52w low - 1 (>= 0)
    max_drawdown_1y: float | None = None  # largest peak-to-trough fall, as a negative ratio
    volume_ratio_20d: float | None = None  # last volume / average of the previous 20


def pct_change(values: Sequence[float], n: int) -> float | None:
    if len(values) <= n or values[-1 - n] == 0:
        return None
    return values[-1] / values[-1 - n] - 1


def sma(values: Sequence[float], n: int) -> float | None:
    return statistics.fmean(values[-n:]) if len(values) >= n else None


def ema_series(values: Sequence[float], n: int) -> list[float]:
    """EMA seeded with the SMA of the first n values; one output per value from index n-1."""
    if len(values) < n:
        return []
    alpha = 2 / (n + 1)
    out = [statistics.fmean(values[:n])]
    for v in values[n:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def annualised_volatility(values: Sequence[float], n: int) -> float | None:
    if len(values) < n + 1:
        return None
    window = values[-(n + 1) :]
    log_returns = [math.log(b / a) for a, b in pairwise(window)]
    return statistics.stdev(log_returns) * math.sqrt(TRADING_DAYS)


def rsi(values: Sequence[float], n: int = 14) -> float | None:
    if len(values) < n + 1:
        return None
    changes = [b - a for a, b in pairwise(values)]
    avg_gain = statistics.fmean(max(c, 0.0) for c in changes[:n])
    avg_loss = statistics.fmean(max(-c, 0.0) for c in changes[:n])
    for c in changes[n:]:
        avg_gain = (avg_gain * (n - 1) + max(c, 0.0)) / n
        avg_loss = (avg_loss * (n - 1) + max(-c, 0.0)) / n
    if avg_loss == 0:
        return 50.0 if avg_gain == 0 else 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def max_drawdown(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def compute_indicators(bars: Sequence[Bar]) -> TechnicalSnapshot:
    """Indicators from daily bars ordered oldest first."""
    if not bars:
        return TechnicalSnapshot(bars_used=0)
    closes = [float(b.close) for b in bars]
    volumes = [float(b.volume) for b in bars]
    last = closes[-1]

    def vs(avg: float | None) -> float | None:
        return last / avg - 1 if avg else None

    sma20, sma50, sma200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    macd_line: list[float] = []
    ema12, ema26 = ema_series(closes, 12), ema_series(closes, 26)
    if ema26:
        offset = len(ema12) - len(ema26)
        macd_line = [a - b for a, b in zip(ema12[offset:], ema26, strict=True)]
    signal = ema_series(macd_line, 9)
    year = bars[-TRADING_DAYS:]
    high = max(float(b.high) for b in year) if len(bars) >= TRADING_DAYS else None
    low = min(float(b.low) for b in year) if len(bars) >= TRADING_DAYS else None
    prior_volume = sma(volumes[:-1], 20)

    return TechnicalSnapshot(
        bars_used=len(bars),
        last_bar_ts=bars[-1].ts,
        last_close=last,
        return_1d=pct_change(closes, 1),
        return_5d=pct_change(closes, 5),
        return_20d=pct_change(closes, 20),
        return_60d=pct_change(closes, 60),
        return_120d=pct_change(closes, 120),
        return_250d=pct_change(closes, 250),
        volatility_20d=annualised_volatility(closes, 20),
        volatility_60d=annualised_volatility(closes, 60),
        sma_20=sma20,
        sma_50=sma50,
        sma_200=sma200,
        price_vs_sma_20=vs(sma20),
        price_vs_sma_50=vs(sma50),
        price_vs_sma_200=vs(sma200),
        rsi_14=rsi(closes, 14),
        macd=macd_line[-1] if macd_line else None,
        macd_signal=signal[-1] if signal else None,
        macd_histogram=macd_line[-1] - signal[-1] if signal else None,
        high_52w=high,
        low_52w=low,
        from_52w_high=last / high - 1 if high else None,
        from_52w_low=last / low - 1 if low else None,
        max_drawdown_1y=max_drawdown(closes[-TRADING_DAYS:]) if len(bars) >= TRADING_DAYS else None,
        volume_ratio_20d=volumes[-1] / prior_volume if prior_volume else None,
    )
