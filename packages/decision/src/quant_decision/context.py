"""Everything a decision agent sees about one symbol, pre-computed and pre-formatted.

Each piece of data carries a stable id (e.g. `ind:rsi_14`, `bar:2026-09-23`, `sent:<uuid>`,
`hist:<uuid>`, `pos:AAPL`). Agents cite these ids in `referenced_data_ids`, and only ids
that were actually shown are kept.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from quant_core.indicators import TechnicalSnapshot, fmt_pct, indicator_rows, unavailable_notes
from quant_core.models import AggregatedDecision, Bar, SentimentResult
from quant_database import LedgerState


@dataclass(slots=True)
class HistoryEntry:
    decision: AggregatedDecision
    price_then: Decimal | None  # close of the last bar completed before the decision
    change_since: float | None  # last close / price_then - 1


@dataclass(slots=True)
class SymbolContext:
    symbol: str
    as_of: datetime
    bars: Sequence[Bar]  # completed bars, oldest first
    indicators: TechnicalSnapshot
    ledger: LedgerState
    nav: Decimal
    sentiment: Sequence[SentimentResult] = ()
    history: Sequence[HistoryEntry] = ()
    recent_bars_in_prompt: int = 20
    extra: dict[str, Any] = field(default_factory=dict)

    def to_inputs(self) -> tuple[dict[str, Any], set[str]]:
        """Template inputs and the set of data ids shown in them."""
        ids: set[str] = set()

        indicators = [
            {"id": r["id"], "label": r["label"], "value": r["value"]}
            for r in indicator_rows(self.indicators)
        ]
        ids.update(r["id"] for r in indicators)

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

        sentiment = []
        for s in self.sentiment:
            if s.error is not None:
                continue  # failed analyses carry no information
            ids.add(f"sent:{s.id}")
            sentiment.append(
                {
                    "id": f"sent:{s.id}",
                    "agent": s.agent_id,
                    "sentiment": f"{s.sentiment:+.2f}",
                    "confidence": f"{s.confidence:.2f}",
                    "summary": s.summary,
                    "key_events": s.key_events,
                }
            )

        history = []
        for h in self.history:
            ids.add(f"hist:{h.decision.id}")
            history.append(
                {
                    "id": f"hist:{h.decision.id}",
                    "date": h.decision.created_at.date().isoformat(),
                    "action": h.decision.final_action.value,
                    "price_then": f"{h.price_then:.2f}" if h.price_then is not None else "n/a",
                    "change_since": fmt_pct(h.change_since)
                    if h.change_since is not None
                    else "n/a",
                }
            )

        inputs = {
            "symbol": self.symbol,
            "as_of": self.as_of.isoformat(timespec="minutes"),
            "indicators": indicators,
            "indicators_unavailable": unavailable_notes(self.indicators),
            "bars": bars,
            "position": position,
            "cash": {
                "available": f"{self.ledger.available_cash:,.2f}",
                "nav": f"{self.nav:,.2f}",
                "max_capital": f"{self.ledger.max_capital:,.2f}",
            },
            "sentiment": sentiment,
            "history": history,
            **self.extra,
        }
        return inputs, ids

    def _position(self) -> dict[str, Any] | None:
        pos = self.ledger.positions.get(self.symbol)
        if pos is None or pos.qty == 0:
            return None
        last = self.indicators.last_close
        value = pos.qty * Decimal(str(last)) if last is not None else pos.cost_basis
        return {
            "id": f"pos:{self.symbol}",
            "qty": format(pos.qty.normalize(), "f"),
            "avg_cost": f"{pos.avg_cost:.2f}",
            "market_value": f"{value:,.2f}",
            "unrealized": fmt_pct(value / pos.cost_basis - 1) if pos.cost_basis else "n/a",
            "weight": fmt_pct(value / self.nav) if self.nav else "n/a",
        }


def history_entries(
    decisions: Sequence[AggregatedDecision], bars: Sequence[Bar], bar_length: timedelta
) -> list[HistoryEntry]:
    """Past decisions with the price move since (computed in code, never by the LLM)."""
    last = bars[-1].close if bars else None
    entries = []
    for d in decisions:
        completed = [b for b in bars if b.ts + bar_length <= d.created_at]
        then = completed[-1].close if completed else None
        change = float(last / then - 1) if last is not None and then else None
        entries.append(HistoryEntry(d, then, change))
    return entries
