"""`TechnicalSnapshot` and `compute_indicators`: runs every indicator module on one symbol's
completed bars. A missing field never raises; it is `None` and explained in `warnings`."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from quant_core.indicators.adx import INDICATOR as ADX
from quant_core.indicators.amihud import INDICATOR as AMIHUD
from quant_core.indicators.atr import INDICATOR as ATR
from quant_core.indicators.base import (
    BarSeries,
    Indicator,
    IndicatorWarning,
    Values,
    WarningReason,
)
from quant_core.indicators.bollinger import INDICATOR as BOLLINGER
from quant_core.indicators.drawdown import INDICATOR as DRAWDOWN
from quant_core.indicators.gap_frequency import INDICATOR as GAP_FREQUENCY
from quant_core.indicators.gap_share import INDICATOR as GAP_SHARE
from quant_core.indicators.macd import INDICATOR as MACD
from quant_core.indicators.max_gap import INDICATOR as MAX_GAP
from quant_core.indicators.moving_average import INDICATOR as MOVING_AVERAGE
from quant_core.indicators.obv import INDICATOR as OBV
from quant_core.indicators.parkinson import INDICATOR as PARKINSON
from quant_core.indicators.range_52w import INDICATOR as RANGE_52W
from quant_core.indicators.return_volume_corr import INDICATOR as RETURN_VOLUME_CORR
from quant_core.indicators.returns import INDICATOR as RETURNS
from quant_core.indicators.rsi import INDICATOR as RSI
from quant_core.indicators.updown_volume import INDICATOR as UPDOWN_VOLUME
from quant_core.indicators.volatility import INDICATOR as VOLATILITY
from quant_core.indicators.volume_ratio import INDICATOR as VOLUME_RATIO
from quant_core.indicators.vwap import INDICATOR as VWAP
from quant_core.indicators.zscore import INDICATOR as ZSCORE
from quant_core.logging import get_logger
from quant_core.models import Bar

log = get_logger(__name__)

# Order matters only for display.
INDICATORS: tuple[Indicator, ...] = (
    RETURNS,
    VOLATILITY,
    PARKINSON,
    ATR,
    MOVING_AVERAGE,
    ZSCORE,
    BOLLINGER,
    RSI,
    MACD,
    ADX,
    RANGE_52W,
    DRAWDOWN,
    GAP_SHARE,
    MAX_GAP,
    GAP_FREQUENCY,
    VOLUME_RATIO,
    UPDOWN_VOLUME,
    OBV,
    VWAP,
    RETURN_VOLUME_CORR,
    AMIHUD,
)


class TechnicalSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bars_used: int
    last_bar_ts: datetime | None = None
    last_close: float | None = None
    # returns
    return_1d: float | None = None
    return_5d: float | None = None
    return_20d: float | None = None
    return_60d: float | None = None
    return_120d: float | None = None
    return_250d: float | None = None
    # volatility
    volatility_20d: float | None = None  # annualised, from daily log returns
    volatility_60d: float | None = None
    parkinson_vol_20d: float | None = None  # annualised, from high/low ranges
    atr_14: float | None = None  # price units
    atr_pct: float | None = None  # ATR / last close
    # trend and mean reversion
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    price_vs_sma_20: float | None = None  # close / SMA - 1
    price_vs_sma_50: float | None = None
    price_vs_sma_200: float | None = None
    zscore_20: float | None = None  # (close - SMA20) / stdev20
    bollinger_pct_b_20: float | None = None  # 0 = lower band, 1 = upper band
    bollinger_width_20: float | None = None  # (upper - lower) / SMA20
    rsi_14: float | None = None  # Wilder, 0..100
    macd: float | None = None  # EMA12 - EMA26
    macd_signal: float | None = None  # EMA9 of MACD
    macd_histogram: float | None = None
    adx_14: float | None = None  # trend strength, 0..100
    plus_di_14: float | None = None
    minus_di_14: float | None = None
    # range and drawdown
    high_52w: float | None = None
    low_52w: float | None = None
    from_52w_high: float | None = None  # close / 52w high - 1 (<= 0)
    from_52w_low: float | None = None  # close / 52w low - 1 (>= 0)
    max_drawdown_1y: float | None = None  # largest peak-to-trough fall, as a negative ratio
    # gaps
    gap_variance_share_60d: float | None = None  # 0..1
    max_gap_60d: float | None = None  # signed fraction
    gap_freq_2atr_60d: float | None = None  # 0..1
    # volume and liquidity
    volume_ratio_20d: float | None = None  # last volume / average of the previous 20
    updown_volume_ratio_10d: float | None = None
    obv_trend_20d: float | None = None  # -1..1
    obv_from_high_250d: float | None = None  # <= 0
    vwap_5d: float | None = None
    vwap_20d: float | None = None
    vwap_60d: float | None = None
    price_vs_vwap_20d: float | None = None
    return_volume_corr_20d: float | None = None  # -1..1
    amihud_illiquidity_20d: float | None = None  # |return| per USD 1M traded
    # why fields above are None
    warnings: tuple[IndicatorWarning, ...] = ()


def _run(indicator: Indicator, series: BarSeries) -> tuple[Values, list[IndicatorWarning]]:
    """One indicator, never raising: unavailable fields come back as None plus a warning."""
    n = len(series)
    fields = dict(indicator.fields)
    try:
        values = indicator.compute(series) if n > 0 else {}
    except (ArithmeticError, ValueError) as exc:
        return dict.fromkeys(fields), [
            IndicatorWarning(
                indicator=indicator.name,
                fields=tuple(fields),
                reason=WarningReason.ERROR,
                available_bars=n,
                detail=f"{type(exc).__name__}: {exc}",
            )
        ]
    out: Values = {f: values.get(f) for f in fields}
    short = [f for f in fields if out[f] is None and n < fields[f]]
    degenerate = [f for f in fields if out[f] is None and n >= fields[f]]
    warnings = []
    for needed in sorted({fields[f] for f in short}):
        warnings.append(
            IndicatorWarning(
                indicator=indicator.name,
                fields=tuple(f for f in short if fields[f] == needed),
                reason=WarningReason.INSUFFICIENT_DATA,
                needed_bars=needed,
                available_bars=n,
            )
        )
    if degenerate:
        warnings.append(
            IndicatorWarning(
                indicator=indicator.name,
                fields=tuple(degenerate),
                reason=WarningReason.DEGENERATE_DATA,
                available_bars=n,
                detail=indicator.degenerate_hint,
            )
        )
    return out, warnings


def compute_indicators(bars: Sequence[Bar], *, warn: bool = True) -> TechnicalSnapshot:
    """Indicators from completed bars ordered oldest first.

    Never raises because of the data: every field that cannot be computed is None and
    explained in `TechnicalSnapshot.warnings`; with `warn=True` they are also logged once
    (event `indicators.unavailable`, level warning).
    """
    series = BarSeries.from_bars(bars)
    data: dict[str, Any] = {
        "bars_used": len(bars),
        "last_bar_ts": bars[-1].ts if bars else None,
        "last_close": series.closes[-1] if bars else None,
    }
    warnings: list[IndicatorWarning] = []
    for indicator in INDICATORS:
        values, problems = _run(indicator, series)
        data.update(values)
        warnings += problems
    if warn and warnings:
        log.warning(
            "indicators.unavailable",
            symbol=bars[0].symbol if bars else None,
            bars=len(bars),
            missing=[f"{w.indicator}: {w.message()}" for w in warnings],
        )
    return TechnicalSnapshot(**data, warnings=tuple(warnings))
