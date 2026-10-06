"""Volume-weighted average price over 5, 20 and 60 days (typical price (H+L+C)/3), and the
last close's distance from the 20-day VWAP. Roughly the average cost of recent buyers."""

from __future__ import annotations

from quant_core.indicators.base import BarSeries, Indicator, Values

PERIODS = (5, 20, 60)


def vwap(s: BarSeries, n: int) -> float | None:
    if len(s) < n:
        return None
    vol = sum(s.volumes[-n:])
    if vol <= 0:
        return None
    typical = [
        (h + lo + c) / 3 for h, lo, c in zip(s.highs[-n:], s.lows[-n:], s.closes[-n:], strict=True)
    ]
    return sum(p * v for p, v in zip(typical, s.volumes[-n:], strict=True)) / vol


def compute(s: BarSeries) -> Values:
    out: Values = {f"vwap_{n}d": vwap(s, n) for n in PERIODS}
    v20 = out["vwap_20d"]
    out["price_vs_vwap_20d"] = s.closes[-1] / v20 - 1 if v20 else None
    return out


INDICATOR = Indicator(
    name="vwap",
    fields={**{f"vwap_{n}d": n for n in PERIODS}, "price_vs_vwap_20d": 20},
    compute=compute,
    degenerate_hint="no volume in the window",
)
