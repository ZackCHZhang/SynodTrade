"""Everything a decision agent sees about one symbol, pre-computed and pre-formatted.

Each piece of data carries a stable id (e.g. `ind:rsi_14`, `bar:2026-09-23`, `sent:<uuid>`,
`hist:<uuid>`, `pos:AAPL`, `quote:AAPL`, `fund:pe`, `mkt:SPY`, `sel:AAPL`). Agents cite
these ids in `referenced_data_ids`, and only ids that were actually shown are kept.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from quant_core.fundamentals import fundamentals_inputs
from quant_core.indicators import RelativeSnapshot, TechnicalSnapshot
from quant_core.models import Bar, Fundamentals, Quote, SentimentResult
from quant_core.research import (
    HistoryEntry,
    earnings_reaction,
    fmt_pct,
    history_entries,
    history_inputs,
    market_inputs,
    quote_inputs,
    sentiment_inputs,
)
from quant_database import LedgerState

__all__ = ["HistoryEntry", "SymbolContext", "fmt_indicator", "fmt_pct", "history_entries"]

_PERCENT = {
    "return_1d", "return_5d", "return_20d", "return_60d", "return_120d", "return_250d",
    "volatility_20d", "volatility_60d", "price_vs_sma_20", "price_vs_sma_50",
    "price_vs_sma_200", "from_52w_high", "from_52w_low", "max_drawdown_1y", "atr_14_pct",
    "max_gap_60d",
}  # fmt: skip
_LABELS = {
    "last_close": "Last close",
    "return_1d": "Return 1 day",
    "return_5d": "Return 5 days",
    "return_20d": "Return 20 days",
    "return_60d": "Return 60 days",
    "return_120d": "Return 120 days",
    "return_250d": "Return 250 days",
    "volatility_20d": "Volatility 20d (annualised)",
    "volatility_60d": "Volatility 60d (annualised)",
    "sma_20": "SMA 20",
    "sma_50": "SMA 50",
    "sma_200": "SMA 200",
    "price_vs_sma_20": "Close vs SMA 20",
    "price_vs_sma_50": "Close vs SMA 50",
    "price_vs_sma_200": "Close vs SMA 200",
    "rsi_14": "RSI 14",
    "macd": "MACD (12,26)",
    "macd_signal": "MACD signal (9)",
    "macd_histogram": "MACD histogram",
    "high_52w": "52-week high",
    "low_52w": "52-week low",
    "from_52w_high": "Distance from 52-week high",
    "from_52w_low": "Distance from 52-week low",
    "max_drawdown_1y": "Max drawdown 1 year",
    "volume_ratio_20d": "Volume vs 20-day average",
    "atr_14": "Average true range 14 (price units)",
    "atr_14_pct": "Average true range 14 / close",
    "max_gap_60d": "Largest overnight gap, 60 days",
    "high_20d": "20-day high",
    "low_20d": "20-day low",
    "high_55d": "55-day high",
    "low_55d": "55-day low",
}


def fmt_indicator(name: str, value: float) -> str:
    if name in _PERCENT:
        return fmt_pct(value)
    if name == "rsi_14":
        return f"{value:.1f}"
    if name == "volume_ratio_20d":
        return f"{value:.2f}x"
    return f"{value:.4f}" if name.startswith("macd") else f"{value:.2f}"


@dataclass(slots=True)
class SymbolContext:
    symbol: str
    as_of: datetime
    bars: Sequence[Bar]  # completed bars, oldest first
    indicators: TechnicalSnapshot
    ledger: LedgerState
    nav: Decimal
    sentiment: Sequence[SentimentResult] = ()
    sentiment_from_this_run: bool = True  # False: newest stored results of earlier runs
    history: Sequence[HistoryEntry] = ()
    recent_bars_in_prompt: int = 20
    quote: Quote | None = None  # a fresh quote from this run's data update
    fundamentals: Fundamentals | None = None
    benchmark: str | None = None
    benchmark_indicators: TechnicalSnapshot | None = None
    relative: RelativeSnapshot | None = None
    selection: dict[str, Any] | None = None  # see `selection_inputs` in the stage
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def price(self) -> float | None:
        """Current price: the fresh quote, else the last close."""
        if self.quote is not None and self.quote.reference_price is not None:
            return float(self.quote.reference_price)
        return self.indicators.last_close

    def to_inputs(self) -> tuple[dict[str, Any], set[str]]:
        """Template inputs and the set of data ids shown in them."""
        ids: set[str] = set()

        indicators = []
        for name, label in _LABELS.items():
            value = getattr(self.indicators, name)
            if value is not None:
                ids.add(f"ind:{name}")
                indicators.append(
                    {"id": f"ind:{name}", "label": label, "value": fmt_indicator(name, value)}
                )

        bars = []
        for bar in self.bars[-self.recent_bars_in_prompt :]:
            day = bar.ts.date().isoformat()
            ids.add(f"bar:{day}")
            bars.append(
                {
                    "id": f"bar:{day}",
                    "date": day,
                    "open": f"{bar.open:.2f}",
                    "high": f"{bar.high:.2f}",
                    "low": f"{bar.low:.2f}",
                    "close": f"{bar.close:.2f}",
                    "volume": f"{bar.volume:,.0f}",
                }
            )

        position = self._position()
        if position is not None:
            ids.add(position["id"])

        sentiment = sentiment_inputs(
            self.sentiment, self.as_of, this_run=self.sentiment_from_this_run
        )
        ids.update(item["id"] for item in sentiment)

        history = history_inputs(self.history)
        ids.update(item["id"] for item in history)

        quote = quote_inputs(self.symbol, self.quote, self.indicators.last_close, self.as_of)
        if quote is not None:
            ids.add(quote["id"])

        fundamentals = fundamentals_inputs(self.fundamentals, self.price, self.as_of.date())
        if fundamentals is not None:
            reaction = earnings_reaction(self.fundamentals, self.bars, self.price)
            if reaction is not None:
                fundamentals["lines"].append(reaction)
            ids.update(line["id"] for line in fundamentals["lines"])

        market = None
        if self.benchmark is not None and self.benchmark_indicators is not None:
            market = market_inputs(self.benchmark, self.benchmark_indicators, self.relative)
            if market is not None:
                ids.add(market["id"])

        if self.selection is not None:
            ids.add(self.selection["id"])

        inputs = {
            "symbol": self.symbol,
            "as_of": self.as_of.isoformat(timespec="minutes"),
            "indicators": indicators,
            "bars": bars,
            "position": position,
            "cash": {
                "available": f"{self.ledger.available_cash:,.2f}",
                "nav": f"{self.nav:,.2f}",
                "max_capital": f"{self.ledger.max_capital:,.2f}",
            },
            "sentiment": sentiment,
            "sentiment_from_this_run": self.sentiment_from_this_run,
            "history": history,
            "quote": quote,
            "fundamentals": fundamentals,
            "market": market,
            "selection": self.selection,
            **self.extra,
        }
        return inputs, ids

    def _position(self) -> dict[str, Any] | None:
        pos = self.ledger.positions.get(self.symbol)
        if pos is None or pos.qty == 0:
            return None
        last = self.price
        value = pos.qty * Decimal(str(last)) if last is not None else pos.cost_basis
        return {
            "id": f"pos:{self.symbol}",
            "qty": format(pos.qty.normalize(), "f"),
            "avg_cost": f"{pos.avg_cost:.2f}",
            "market_value": f"{value:,.2f}",
            "unrealized": fmt_pct(value / pos.cost_basis - 1) if pos.cost_basis else "n/a",
            "weight": fmt_pct(value / self.nav) if self.nav else "n/a",
        }
