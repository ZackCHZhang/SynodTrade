"""Technical indicators computed in code (the LLM is never asked to do arithmetic).

One module per indicator (see `base.Indicator`); `compute_indicators` runs them all and
returns a `TechnicalSnapshot`. A field that cannot be computed is None and explained in
`TechnicalSnapshot.warnings` — missing data never raises.
"""

from quant_core.indicators._math import ema_series, sma
from quant_core.indicators.base import (
    TRADING_DAYS,
    BarSeries,
    Indicator,
    IndicatorWarning,
    WarningReason,
)
from quant_core.indicators.drawdown import max_drawdown
from quant_core.indicators.format import (
    FIELDS,
    fmt_pct,
    fmt_value,
    indicator_rows,
    unavailable_notes,
)
from quant_core.indicators.returns import pct_change
from quant_core.indicators.rsi import rsi
from quant_core.indicators.snapshot import INDICATORS, TechnicalSnapshot, compute_indicators
from quant_core.indicators.volatility import annualised_volatility

__all__ = [
    "FIELDS",
    "INDICATORS",
    "TRADING_DAYS",
    "BarSeries",
    "Indicator",
    "IndicatorWarning",
    "TechnicalSnapshot",
    "WarningReason",
    "annualised_volatility",
    "compute_indicators",
    "ema_series",
    "fmt_pct",
    "fmt_value",
    "indicator_rows",
    "max_drawdown",
    "pct_change",
    "rsi",
    "sma",
    "unavailable_notes",
]
