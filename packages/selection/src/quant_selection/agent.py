"""Selection agent: one call per agent instance over the whole screened candidate list."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from quant_core.agent import Agent
from quant_core.logging import get_logger
from quant_core.models import SelectionPick, SelectionResult, StockSelection
from quant_selection.screen import CandidateProfile

log = get_logger(__name__)


class PickOutput(BaseModel):
    symbol: str = Field(description="A candidate symbol exactly as listed")
    score: float = Field(ge=0.0, le=1.0, description="How strongly you want it, 0..1")
    reason: str = Field(max_length=600, description="One or two sentences")


class SelectionOutput(BaseModel):
    """What the LLM must return (validated; symbols checked against the candidates)."""

    picks: list[PickOutput] = Field(default_factory=list, max_length=50)
    summary: str = Field(default="", max_length=2000, description="Overall rationale")


def _pct(value: float | None) -> str:
    return f"{value * 100:+.1f}%" if value is not None else "n/a"


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    for unit, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(value) >= size:
            return f"${value / size:.1f}{unit}"
    return f"${value:.0f}"


def candidate_inputs(profile: CandidateProfile) -> dict[str, Any]:
    """Pre-formatted numbers for the prompt (computed in code, never by the LLM)."""
    ind = profile.indicators
    return {
        "id": f"cand:{profile.symbol}",
        "symbol": profile.symbol,
        "held": profile.held,
        "sources": ", ".join(dict.fromkeys(profile.sources)),
        "notes": "; ".join(profile.notes),
        "last_close": f"{ind.last_close:.2f}" if ind.last_close is not None else "n/a",
        "return_20d": _pct(ind.return_20d),
        "return_60d": _pct(ind.return_60d),
        "return_120d": _pct(ind.return_120d),
        "return_250d": _pct(ind.return_250d),
        "volume_ratio_20d": f"{ind.volume_ratio_20d:.2f}x"
        if ind.volume_ratio_20d is not None
        else "n/a",
        "volatility_60d": _pct(ind.volatility_60d),
        "price_vs_sma_50": _pct(ind.price_vs_sma_50),
        "price_vs_sma_200": _pct(ind.price_vs_sma_200),
        "rsi_14": f"{ind.rsi_14:.0f}" if ind.rsi_14 is not None else "n/a",
        "from_52w_high": _pct(ind.from_52w_high),
        "max_drawdown_1y": _pct(ind.max_drawdown_1y),
        "avg_dollar_volume": _money(profile.avg_dollar_volume),
        "fundamentals": "",  # one-line summaries, filled by the stage when available
        "relative": "",
        "sentiment": "",
        **profile.extra,
    }


class SelectionAgent(Agent[SelectionOutput]):
    """Selection agent. Like every agent, the LLM is chosen when instantiating it:

        agent = SelectionAgent(
            store.agent("momentum_screener"),                # persona + prompt only
            pool.get("deepseek"),                            # provider client
            model=LLMModelConfig(provider="deepseek", name="deepseek-chat"),
            prompt_root=store.agents_dir,
        )

    In a pipeline, each agent reference sets it instead:
    `{ agent: momentum_screener, count: 2, model: { provider: deepseek, name: deepseek-chat } }`.
    """

    output_model = SelectionOutput

    def fallback_output(self, inputs: Mapping[str, Any], error: str) -> SelectionOutput:
        return SelectionOutput(picks=[], summary=f"selection unavailable: {error[:300]}")

    async def select(
        self,
        profiles: Sequence[CandidateProfile],
        *,
        run_id: UUID,
        pipeline_name: str,
        as_of: datetime,
        max_picks: int,
        previous: StockSelection | None = None,
        holdings: Sequence[str] = (),
        watchlist_days: int | None = None,
    ) -> SelectionResult:
        symbols = [p.symbol for p in profiles]
        inputs: dict[str, Any] = {
            "as_of": as_of.isoformat(timespec="minutes"),
            "candidates": [candidate_inputs(p) for p in profiles],
            "max_picks": max_picks,
            "holdings": list(holdings),
            "watchlist_days": watchlist_days,
            "previous": (
                {
                    "date": previous.created_at.date().isoformat(),
                    "selected": previous.selected,
                }
                if previous is not None
                else None
            ),
            "instructions": self.config.params.get("instructions", ""),
        }
        result = await self.invoke(inputs, run_id=run_id)
        picks, unknown = self._valid_picks(result.output.picks, set(symbols), max_picks)
        if unknown:
            log.warning("selection.unknown_symbols", agent=self.agent_id, unknown=unknown)
        return SelectionResult(
            created_at=as_of,
            run_id=run_id,
            pipeline_name=pipeline_name,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            prompt_version=self.prompt_version,
            picks=picks,
            summary=result.output.summary,
            candidates=symbols,
            llm_call_ids=result.call_ids,
            error=result.error,
        )

    @staticmethod
    def _valid_picks(
        raw: Sequence[PickOutput], allowed: set[str], max_picks: int
    ) -> tuple[list[SelectionPick], list[str]]:
        """Known symbols only, first mention wins, best score first, at most `max_picks`."""
        picks: dict[str, SelectionPick] = {}
        unknown: list[str] = []
        for p in raw:
            symbol = p.symbol.strip().upper().removeprefix("CAND:")
            if symbol not in allowed:
                unknown.append(p.symbol)
            elif symbol not in picks:
                picks[symbol] = SelectionPick(symbol=symbol, score=p.score, reason=p.reason)
        ranked = sorted(picks.values(), key=lambda p: -p.score)  # stable: ties keep LLM order
        return ranked[:max_picks], unknown
