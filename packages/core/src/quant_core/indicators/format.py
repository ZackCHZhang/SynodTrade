"""How snapshot fields are labelled and formatted in prompts (shared by every agent type)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from quant_core.indicators.snapshot import TechnicalSnapshot

Kind = Literal["pct", "price", "level", "signed", "num", "ratio", "macd", "frac"]

# field -> (label, kind). The order is the order shown to the agents.
FIELDS: dict[str, tuple[str, Kind]] = {
    "last_close": ("Last close", "price"),
    "return_1d": ("Return 1 day", "pct"),
    "return_5d": ("Return 5 days", "pct"),
    "return_20d": ("Return 20 days", "pct"),
    "return_60d": ("Return 60 days", "pct"),
    "return_120d": ("Return 120 days", "pct"),
    "return_250d": ("Return 250 days", "pct"),
    "volatility_20d": ("Volatility 20d close-to-close (annualised)", "pct"),
    "volatility_60d": ("Volatility 60d close-to-close (annualised)", "pct"),
    "parkinson_vol_20d": ("Volatility 20d from high/low ranges, Parkinson (annualised)", "pct"),
    "atr_14": ("ATR 14 (average true range, price units)", "price"),
    "atr_pct": ("ATR 14 as % of last close", "pct"),
    "sma_20": ("SMA 20", "price"),
    "sma_50": ("SMA 50", "price"),
    "sma_200": ("SMA 200", "price"),
    "price_vs_sma_20": ("Close vs SMA 20", "pct"),
    "price_vs_sma_50": ("Close vs SMA 50", "pct"),
    "price_vs_sma_200": ("Close vs SMA 200", "pct"),
    "zscore_20": ("Z-score of close vs last 20 closes (standard deviations)", "signed"),
    "bollinger_pct_b_20": ("Bollinger %b (20, 2σ; 0 = lower band, 1 = upper band)", "num"),
    "bollinger_width_20": ("Bollinger band width / SMA 20", "pct"),
    "rsi_14": ("RSI 14", "level"),
    "macd": ("MACD (12,26)", "macd"),
    "macd_signal": ("MACD signal (9)", "macd"),
    "macd_histogram": ("MACD histogram", "macd"),
    "adx_14": ("ADX 14 (trend strength; <20 weak, >25 trending)", "level"),
    "plus_di_14": ("+DI 14", "level"),
    "minus_di_14": ("-DI 14", "level"),
    "high_52w": ("52-week high", "price"),
    "low_52w": ("52-week low", "price"),
    "from_52w_high": ("Distance from 52-week high", "pct"),
    "from_52w_low": ("Distance from 52-week low", "pct"),
    "max_drawdown_1y": ("Max drawdown 1 year", "pct"),
    "gap_variance_share_60d": ("Share of 60-day price variation from overnight gaps", "pct"),
    "max_gap_60d": ("Largest overnight gap in 60 days", "pct"),
    "gap_freq_2atr_60d": ("Days in last 60 that gapped more than 2 ATR", "pct"),
    "volume_ratio_20d": ("Volume vs 20-day average", "ratio"),
    "updown_volume_ratio_10d": ("Avg volume on up days / down days (10 days)", "ratio"),
    "obv_trend_20d": ("OBV change over 20 days / their volume (-1..1)", "signed"),
    "obv_from_high_250d": ("OBV below its 250-day high, / 250-day volume (0 = at high)", "signed"),
    "vwap_5d": ("VWAP 5 days", "price"),
    "vwap_20d": ("VWAP 20 days", "price"),
    "vwap_60d": ("VWAP 60 days", "price"),
    "price_vs_vwap_20d": ("Close vs VWAP 20 days", "pct"),
    "return_volume_corr_20d": ("Correlation of returns with volume changes, 20 days", "signed"),
    "amihud_illiquidity_20d": ("Amihud illiquidity (|return| per USD 1M traded, 20 days)", "frac"),
}


def fmt_pct(value: float | Decimal) -> str:
    return f"{float(value) * 100:+.2f}%"


def fmt_value(field: str, value: float) -> str:
    kind = FIELDS[field][1] if field in FIELDS else "price"
    if kind == "pct":
        return fmt_pct(value)
    if kind == "ratio":
        return f"{value:.2f}x"
    if kind == "macd":
        return f"{value:.4f}"
    if kind == "frac":
        return f"{value:.6f}"
    if kind == "signed":
        return f"{value:+.2f}"
    if kind == "level":
        return f"{value:.1f}"
    return f"{value:.2f}"


def indicator_rows(snapshot: TechnicalSnapshot) -> list[dict[str, Any]]:
    """Every available field as {id, field, label, value}, in display order."""
    rows = []
    for field, (label, _) in FIELDS.items():
        value = getattr(snapshot, field)
        if value is not None:
            rows.append(
                {
                    "id": f"ind:{field}",
                    "field": field,
                    "label": label,
                    "value": fmt_value(field, value),
                }
            )
    return rows


def unavailable_notes(snapshot: TechnicalSnapshot) -> list[str]:
    """One line per warning, for the prompt: which indicators are missing and why."""
    return [f"{w.indicator}: {w.message()}" for w in snapshot.warnings]
