"""Building blocks shared by every indicator module.

Each indicator lives in its own module and exports one `Indicator`: the snapshot fields it
fills, how many completed bars each field needs, and a pure `compute` function. The
orchestrator (`snapshot.compute_indicators`) never lets one indicator break the others: a
field that cannot be computed (too little history, degenerate data, an arithmetic error)
becomes `None` and is reported as an `IndicatorWarning` instead of raising.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from quant_core.models import Bar

TRADING_DAYS = 252

Values = dict[str, float | None]


@dataclass(frozen=True, slots=True)
class BarSeries:
    """Completed bars as plain float lists, oldest first (indicators are statistics for the
    prompt, not money amounts, so float is fine)."""

    opens: list[float]
    highs: list[float]
    lows: list[float]
    closes: list[float]
    volumes: list[float]

    @classmethod
    def from_bars(cls, bars: Sequence[Bar]) -> BarSeries:
        return cls(
            opens=[float(b.open) for b in bars],
            highs=[float(b.high) for b in bars],
            lows=[float(b.low) for b in bars],
            closes=[float(b.close) for b in bars],
            volumes=[float(b.volume) for b in bars],
        )

    def __len__(self) -> int:
        return len(self.closes)


@dataclass(frozen=True, slots=True)
class Indicator:
    """One indicator: `fields` maps each snapshot field it fills to the number of completed
    bars that field needs. `compute` returns a value (or None) for every field."""

    name: str
    fields: Mapping[str, int]
    compute: Callable[[BarSeries], Values]
    # Shown when a field is None although there were enough bars (e.g. "no volume").
    degenerate_hint: str | None = None


class WarningReason(StrEnum):
    INSUFFICIENT_DATA = "insufficient_data"  # fewer bars than the field needs
    DEGENERATE_DATA = "degenerate_data"  # enough bars, but e.g. zero volume or no variance
    ERROR = "error"  # an unexpected arithmetic error inside the indicator


class IndicatorWarning(BaseModel):
    """Why some fields of one indicator are missing from the snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    indicator: str
    fields: tuple[str, ...]
    reason: WarningReason
    needed_bars: int | None = None
    available_bars: int
    detail: str | None = None

    def message(self) -> str:
        names = ", ".join(self.fields)
        if self.reason is WarningReason.INSUFFICIENT_DATA:
            return (
                f"{names}: needs {self.needed_bars} completed bars, "
                f"only {self.available_bars} available"
            )
        if self.reason is WarningReason.DEGENERATE_DATA:
            return f"{names}: not computable from this data ({self.detail or 'degenerate'})"
        return f"{names}: calculation failed ({self.detail})"
