"""Prompt inputs shared by the decision and risk stages, computed and formatted in code.

Every block carries a stable data id (`hist:<uuid>`, `quote:AAPL`, `mkt:SPY`, `sent:<uuid>`)
that agents can cite.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from synodtrade_core.indicators import RelativeSnapshot, TechnicalSnapshot
from synodtrade_core.models import (
    Action,
    AggregatedDecision,
    Bar,
    DecisionOutcome,
    Fundamentals,
    Quote,
    SelectionResult,
    SentimentResult,
    StockSelection,
    WatchlistEntry,
)


def fmt_pct(value: float | Decimal) -> str:
    return f"{float(value) * 100:+.2f}%"


def fmt_age(then: datetime, now: datetime) -> str:
    hours = (now - then).total_seconds() / 3600
    if hours < 1:
        return f"{max(0, round(hours * 60))} min ago"
    if hours < 48:
        return f"{hours:.0f} h ago"
    return f"{hours / 24:.0f} days ago"


# ------------------------------------------------------------------ decision history


@dataclass(slots=True)
class HistoryEntry:
    decision: AggregatedDecision
    price_then: Decimal | None  # close of the last bar completed before the decision
    change_since: float | None  # last close / price_then - 1
    outcome: DecisionOutcome | None = None


def history_entries(
    decisions: Sequence[AggregatedDecision],
    bars: Sequence[Bar],
    bar_length: timedelta,
    outcomes: Mapping[UUID, DecisionOutcome] | None = None,
) -> list[HistoryEntry]:
    """Past decisions with the price move since (computed in code, never by the LLM)."""
    last = bars[-1].close if bars else None
    entries = []
    for d in decisions:
        completed = [b for b in bars if b.ts + bar_length <= d.created_at]
        then = completed[-1].close if completed else None
        change = float(last / then - 1) if last is not None and then else None
        entries.append(HistoryEntry(d, then, change, (outcomes or {}).get(d.id)))
    return entries


def describe_outcome(action: Action, outcome: DecisionOutcome | None) -> str:
    """What happened after the decision, in words."""
    if action is Action.HOLD:
        return "nothing to execute"
    if outcome is None or outcome.risk_action is None:
        return "not executed, no risk review recorded"
    parts = []
    if outcome.risk_action is Action.HOLD:
        parts.append(f"rejected by risk ({(outcome.risk_reason or '')[:160]})")
    elif outcome.risk_action is not action:
        parts.append(f"reduced by risk to {outcome.risk_action.value}")
    else:
        parts.append("approved by risk")
    if outcome.risk_action is not Action.HOLD:
        if outcome.order_status is None:
            parts.append("no order placed (too small or skipped)")
        elif outcome.filled_qty > 0:
            price = f" at {outcome.avg_fill_price:.2f}" if outcome.avg_fill_price else ""
            parts.append(
                f"order {outcome.order_status}, {format(outcome.filled_qty.normalize(), 'f')} "
                f"shares filled{price}"
            )
        else:
            parts.append(f"order {outcome.order_status}, nothing filled")
    return "; ".join(parts)


def history_inputs(entries: Sequence[HistoryEntry]) -> list[dict[str, str]]:
    return [
        {
            "id": f"hist:{h.decision.id}",
            "date": h.decision.created_at.date().isoformat(),
            "action": h.decision.final_action.value,
            "price_then": f"{h.price_then:.2f}" if h.price_then is not None else "n/a",
            "change_since": fmt_pct(h.change_since) if h.change_since is not None else "n/a",
            "outcome": describe_outcome(h.decision.final_action, h.outcome),
        }
        for h in entries
    ]


def earnings_reaction(
    f: Fundamentals | None, bars: Sequence[Bar], price: float | None
) -> dict[str, str] | None:
    """Prompt line `fund:earnings_reaction`: the move over the first two sessions from the
    last earnings release (covers releases before the open and after the close) and the
    move since (computed from completed daily bars)."""
    if f is None or f.last_earnings_date is None or not bars:
        return None
    released = f.last_earnings_date
    before = [b for b in bars if b.ts.date() < released]
    after = [b for b in bars if b.ts.date() >= released]
    if not before or not after:
        return None
    base = float(before[-1].close)
    reaction = float(after[:2][-1].close) / base - 1
    since = (price if price is not None else float(bars[-1].close)) / base - 1
    held = "held" if since * reaction > 0 and abs(since) >= abs(reaction) / 2 else "faded"
    return {
        "id": "fund:earnings_reaction",
        "label": "Price reaction to the last earnings release",
        "value": f"{fmt_pct(reaction)} over the first two sessions, {fmt_pct(since)} since "
        f"the close before the release ({held})",
    }


# ------------------------------------------------------------------ live price


def quote_inputs(
    symbol: str, quote: Quote | None, last_close: float | None, now: datetime
) -> dict[str, str] | None:
    """The latest quote (taken during this run's data update) against the last close."""
    if quote is None:
        return None
    price = quote.reference_price
    if price is None:
        return None
    return {
        "id": f"quote:{symbol}",
        "price": f"{price:.2f}",
        "bid": f"{quote.bid:.2f}" if quote.bid is not None else "n/a",
        "ask": f"{quote.ask:.2f}" if quote.ask is not None else "n/a",
        "time": quote.ts.isoformat(timespec="minutes"),
        "age": fmt_age(quote.ts, now),
        "vs_last_close": fmt_pct(float(price) / last_close - 1) if last_close else "n/a",
    }


# ------------------------------------------------------------------ market benchmark


def market_inputs(
    benchmark: str, snap: TechnicalSnapshot, relative: RelativeSnapshot | None
) -> dict[str, Any] | None:
    """Market regime (the benchmark's own trend and volatility) and the symbol against it."""
    if snap.last_close is None:
        return None

    def pct(value: float | None) -> str:
        return fmt_pct(value) if value is not None else "n/a"

    regime = "n/a"
    if snap.price_vs_sma_200 is not None:
        regime = (
            "above its 200-day average"
            if snap.price_vs_sma_200 > 0
            else ("below its 200-day average")
        )
    out: dict[str, Any] = {
        "id": f"mkt:{benchmark}",
        "benchmark": benchmark,
        "return_20d": pct(snap.return_20d),
        "return_60d": pct(snap.return_60d),
        "return_250d": pct(snap.return_250d),
        "vs_sma_200": pct(snap.price_vs_sma_200),
        "regime": regime,
        "volatility_20d": pct(snap.volatility_20d),
        "from_52w_high": pct(snap.from_52w_high),
        "relative": None,
    }
    if relative is not None:
        out["relative"] = {
            "beta_1y": f"{relative.beta_1y:.2f}" if relative.beta_1y is not None else "n/a",
            "correlation_1y": f"{relative.correlation_1y:.2f}"
            if relative.correlation_1y is not None
            else "n/a",
            "relative_return_60d": pct(relative.relative_return_60d),
            "relative_return_250d": pct(relative.relative_return_250d),
        }
    return out


# ------------------------------------------------------------------ sentiment


def sentiment_inputs(
    results: Sequence[SentimentResult], now: datetime, *, this_run: bool
) -> list[dict[str, Any]]:
    out = []
    for s in results:
        if s.error is not None:
            continue  # failed analyses carry no information
        out.append(
            {
                "id": f"sent:{s.id}",
                "agent": s.agent_id,
                "sentiment": f"{s.sentiment:+.2f}",
                "confidence": f"{s.confidence:.2f}",
                "summary": s.summary,
                "key_events": s.key_events,
                "age": "this run" if this_run else fmt_age(s.created_at, now),
            }
        )
    return out


# ------------------------------------------------------------------ stock selection


def watchlist_status(e: WatchlistEntry) -> str:
    parts = [f"on the watchlist since {e.added_at.date().isoformat()}"]
    if e.last_selected_at is not None:
        parts.append(
            f"picked {e.times_selected}x, last on {e.last_selected_at.date().isoformat()}"
            + (f" (score {e.last_score:.2f})" if e.last_score is not None else "")
        )
    else:
        parts.append("added by hand")
    if e.pinned:
        parts.append("pinned")
    if e.note:
        parts.append(f"note: {e.note}")
    return ", ".join(parts)


def selection_inputs(
    selection: StockSelection | None,
    results: Sequence[SelectionResult],
    *,
    this_run: bool,
    watchlist: Sequence[WatchlistEntry] = (),
) -> dict[str, dict[str, Any]]:
    """Per symbol: its place in the selection, every agent's reason for picking it, and
    its watchlist entry (the latest reason it was picked for, even on an earlier day)."""
    entries = {e.symbol: e for e in watchlist}
    out: dict[str, dict[str, Any]] = {}
    if selection is not None:
        out = _selection_status(selection, results, this_run=this_run)
    for symbol, e in entries.items():
        item = out.setdefault(
            symbol,
            {"id": f"sel:{symbol}", "when": "watchlist", "status": "", "reasons": []},
        )
        status = watchlist_status(e)
        item["status"] = f"{item['status']}; {status}" if item["status"] else status
        if not item["reasons"] and e.last_reason:
            item["reasons"] = [
                {
                    "agent": "watchlist (last pick)",
                    "score": f"{e.last_score:.2f}" if e.last_score is not None else "n/a",
                    "reason": e.last_reason,
                }
            ]
    return out


def _selection_status(
    selection: StockSelection, results: Sequence[SelectionResult], *, this_run: bool
) -> dict[str, dict[str, Any]]:
    """Per symbol: its place in the selection and every agent's reason for picking it."""
    reasons: dict[str, list[dict[str, str]]] = {}
    for r in results:
        if r.error is not None:
            continue
        for pick in r.picks:
            reasons.setdefault(pick.symbol, []).append(
                {"agent": r.agent_id, "score": f"{pick.score:.2f}", "reason": pick.reason}
            )
    when = "this run" if this_run else selection.created_at.date().isoformat()
    out: dict[str, dict[str, Any]] = {}
    for symbol in dict.fromkeys([*selection.candidates, *selection.holdings]):
        if symbol in selection.selected:
            rank = selection.selected.index(symbol) + 1
            score = selection.scores.get(symbol)
            status = f"selected, rank {rank} of {len(selection.selected)}" + (
                f", aggregated score {score:.2f}" if score is not None else ""
            )
        elif symbol in selection.watchlist:
            status = "not picked this time; still followed on the watchlist"
        elif symbol in selection.holdings:
            status = "not selected; kept in the universe only because the strategy holds it"
        else:
            status = "screened in but not selected"
        out[symbol] = {
            "id": f"sel:{symbol}",
            "when": when,
            "status": status,
            "reasons": reasons.get(symbol, []),
        }
    return out
