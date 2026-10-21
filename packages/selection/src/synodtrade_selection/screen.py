"""Deterministic pre-screen: per-candidate statistics computed in code, hard filters, and a
cap on how many candidates the agents see (prompt size and cost stay bounded).

Candidates that pass are ordered by average daily dollar volume (most liquid first) before
the cap is applied, so the cap drops the least tradable names.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from synodtrade_core.indicators import TechnicalSnapshot
from synodtrade_core.models import Bar, Candidate


class ScreenOptions(BaseModel):
    """`screen:` options of the selection stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_bars: int = Field(default=60, ge=1)  # completed daily bars needed to judge a stock
    min_price: float | None = Field(default=5.0, ge=0)
    max_price: float | None = Field(default=None, gt=0)
    # Average of close x volume over the last 20 completed bars.
    min_avg_dollar_volume: float | None = Field(default=5_000_000, ge=0)
    max_volatility: float | None = Field(default=None, gt=0)  # annualised 60-day, e.g. 0.8
    max_candidates: int = Field(default=30, ge=1, le=100)  # shown to the agents


def avg_dollar_volume(bars: Sequence[Bar], n: int = 20) -> float | None:
    recent = bars[-n:]
    if not recent:
        return None
    return sum(float(b.close * b.volume) for b in recent) / len(recent)


@dataclass(slots=True)
class CandidateProfile:
    """One candidate with everything the agents are shown about it."""

    symbol: str
    candidates: list[Candidate]  # one per source that proposed it
    indicators: TechnicalSnapshot
    avg_dollar_volume: float | None = None
    held: bool = False
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def sources(self) -> list[str]:
        return [c.source for c in self.candidates]

    @property
    def notes(self) -> list[str]:
        return [c.note for c in self.candidates if c.note]


def rejection(profile: CandidateProfile, options: ScreenOptions) -> str | None:
    """Why the candidate fails the screen, or None if it passes."""
    ind = profile.indicators
    if ind.bars_used < options.min_bars or ind.last_close is None:
        return f"only {ind.bars_used} completed bars (< {options.min_bars})"
    price = ind.last_close
    if options.min_price is not None and price < options.min_price:
        return f"price {price:.2f} < {options.min_price:g}"
    if options.max_price is not None and price > options.max_price:
        return f"price {price:.2f} > {options.max_price:g}"
    adv = profile.avg_dollar_volume
    if options.min_avg_dollar_volume is not None and (
        adv is None or adv < options.min_avg_dollar_volume
    ):
        shown = f"{adv:,.0f}" if adv is not None else "n/a"
        return f"avg dollar volume {shown} < {options.min_avg_dollar_volume:,.0f}"
    vol = ind.volatility_60d
    if options.max_volatility is not None and vol is not None and vol > options.max_volatility:
        return f"volatility {vol:.2f} > {options.max_volatility:g}"
    return None


def screen(
    profiles: Sequence[CandidateProfile], options: ScreenOptions
) -> tuple[list[CandidateProfile], dict[str, str]]:
    """(candidates for the agents, most liquid first; {symbol: rejection reason})."""
    rejected: dict[str, str] = {}
    passed: list[CandidateProfile] = []
    for profile in profiles:
        reason = rejection(profile, options)
        if reason is None:
            passed.append(profile)
        else:
            rejected[profile.symbol] = reason
    passed.sort(key=lambda p: (-(p.avg_dollar_volume or 0.0), p.symbol))
    for profile in passed[options.max_candidates :]:
        rejected[profile.symbol] = f"beyond max_candidates ({options.max_candidates})"
    return passed[: options.max_candidates], rejected
