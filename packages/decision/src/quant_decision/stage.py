"""`decision` pipeline stage: build per-symbol context -> agents decide -> aggregate -> store."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from quant_core.agent_factory import AgentSlot, instantiate_agents
from quant_core.config import AgentRole, ConfigStore, PipelineConfig, StageConfig
from quant_core.indicators import TechnicalSnapshot, compute_indicators, relative_to
from quant_core.llm import LLMClientPool
from quant_core.logging import get_logger
from quant_core.models import (
    Action,
    AggregatedDecision,
    Bar,
    Decision,
    PipelineContext,
    Timeframe,
)
from quant_core.research import selection_inputs
from quant_core.services import Services
from quant_database import AgentInstance, LedgerState, Repositories
from quant_database.repositories import TIMEFRAME_DURATION
from quant_decision.agent import DecisionAgent
from quant_decision.aggregation import AggregationOptions, aggregate
from quant_decision.context import SymbolContext, history_entries

log = get_logger(__name__)


class DecisionOptions(BaseModel):
    """Options of the `decision` stage in configs/pipelines/*.yaml."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    aggregation: AggregationOptions = Field(default_factory=AggregationOptions)
    timeframe: Timeframe = Timeframe.D1
    bars_lookback: int = Field(default=260, ge=30, le=2000)  # enough for SMA 200 / 52 weeks
    min_bars: int = Field(default=30, ge=1)  # fewer completed bars -> HOLD without asking
    recent_bars_in_prompt: int = Field(default=20, ge=0, le=250)
    history_limit: int = Field(default=5, ge=0, le=50)
    # Without sentiment from this run (stage skipped/failed/absent): show each sentiment
    # agent's newest stored analysis of the last N hours (any run or pipeline). 0: never.
    stored_sentiment_hours: int = Field(default=48, ge=0, le=24 * 30)
    max_quote_age_minutes: int = Field(default=30, ge=1)  # older quotes are not shown
    fundamentals: bool = True  # show stored fundamentals (refreshed by data_update/selection)


class DecisionStage:
    name = "decision"

    def __init__(
        self,
        options: DecisionOptions,
        agents: list[AgentSlot[DecisionAgent]],
        repos: Repositories,
        max_capital: Decimal,
        benchmark: str | None = None,
    ) -> None:
        self.options = options
        self.agents = agents
        self._repos = repos
        self._max_capital = max_capital
        self._benchmark = benchmark

    async def _context(
        self,
        symbol: str,
        ctx: PipelineContext,
        ledger: LedgerState,
        nav: Decimal,
        market: tuple[list[Bar], TechnicalSnapshot] | None,
        selection: dict[str, dict[str, Any]],
    ) -> SymbolContext | None:
        opts = self.options
        bars = await self._repos.bars.get_latest_bars(
            symbol, opts.bars_lookback, opts.timeframe, as_of=ctx.as_of
        )
        if len(bars) < opts.min_bars:
            return None
        past = await self._repos.decisions.get_recent_aggregated(
            symbol,
            opts.history_limit,
            as_of=ctx.as_of,
            pipeline_name=ctx.pipeline_name,
            exclude_methods=("insufficient_data",),
        )
        outcomes = await self._repos.decisions.get_outcomes(past)
        sentiment = ctx.sentiment_results.get(symbol, [])
        this_run = any(s.error is None for s in sentiment)
        if not this_run and opts.stored_sentiment_hours > 0:
            sentiment = await self._repos.sentiment.get_latest_results(
                symbol, ctx.as_of - timedelta(hours=opts.stored_sentiment_hours), ctx.as_of
            )
        cutoff = ctx.snapshot_cutoff()
        quote = await self._repos.quotes.get_latest_quote(symbol, as_of=cutoff)
        if quote is not None and cutoff - quote.ts > timedelta(minutes=opts.max_quote_age_minutes):
            quote = None
        fundamentals = (
            await self._repos.fundamentals.get_latest(symbol, ctx.as_of)
            if opts.fundamentals
            else None
        )
        relative = None
        if market is not None and self._benchmark is not None:
            relative = relative_to(bars, market[0], self._benchmark)
        return SymbolContext(
            symbol=symbol,
            as_of=ctx.as_of,
            bars=bars,
            indicators=compute_indicators(bars),
            ledger=ledger,
            nav=nav,
            sentiment=sentiment,
            sentiment_from_this_run=this_run,
            history=history_entries(past, bars, TIMEFRAME_DURATION[opts.timeframe], outcomes),
            recent_bars_in_prompt=opts.recent_bars_in_prompt,
            quote=quote,
            fundamentals=fundamentals,
            benchmark=self._benchmark if market is not None else None,
            benchmark_indicators=market[1] if market is not None else None,
            relative=relative,
            selection=selection.get(symbol),
        )

    async def _market(self, ctx: PipelineContext) -> tuple[list[Bar], TechnicalSnapshot] | None:
        """The benchmark's bars and indicators (market regime), if configured and stored."""
        if self._benchmark is None:
            return None
        bars = await self._repos.bars.get_latest_bars(
            self._benchmark, self.options.bars_lookback, self.options.timeframe, as_of=ctx.as_of
        )
        if len(bars) < self.options.min_bars:
            return None
        return bars, compute_indicators(bars)

    async def _selection(self, ctx: PipelineContext) -> dict[str, dict[str, Any]]:
        """symbol -> what stock selection said about it (this run's, else the latest)."""
        selection, results = ctx.selection, ctx.selection_results
        if selection is None:
            selection = await self._repos.selection.get_latest(ctx.pipeline_name, ctx.as_of)
            results = (
                await self._repos.selection.get_results_by_run(selection.run_id)
                if selection is not None
                else []
            )
        watchlist = await self._repos.watchlist.get_active(ctx.pipeline_name, ctx.as_of)
        return selection_inputs(
            selection, results, this_run=ctx.selection is not None, watchlist=watchlist
        )

    async def _nav(self, ledger: LedgerState, ctx: PipelineContext) -> Decimal:
        prices: dict[str, Decimal] = {}
        for symbol in ledger.positions:
            last = await self._repos.bars.get_latest_bars(
                symbol, 1, self.options.timeframe, as_of=ctx.as_of
            )
            if last:
                prices[symbol] = last[-1].close
        return ledger.nav(prices)

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        ledger = await self._repos.ledger.get_state(
            ctx.pipeline_name, self._max_capital, as_of=ctx.as_of
        )
        nav = await self._nav(ledger, ctx)
        market = await self._market(ctx)
        selection = await self._selection(ctx)
        contexts: dict[str, SymbolContext] = {}
        aggregated: dict[str, AggregatedDecision] = {}
        for symbol in ctx.universe:
            context = await self._context(symbol, ctx, ledger, nav, market, selection)
            if context is None:
                aggregated[symbol] = AggregatedDecision(
                    created_at=ctx.as_of,
                    run_id=ctx.run_id,
                    symbol=symbol,
                    final_action=Action.HOLD,
                    method="insufficient_data",
                    score=0.0,
                    votes=[],
                )
            else:
                contexts[symbol] = context

        await self._repos.runs.register_agent_instances(
            [AgentInstance.from_agent(slot.agent, ctx.run_id) for slot in self.agents]
        )
        pairs = [(slot, symbol) for slot in self.agents for symbol in sorted(contexts)]
        decisions: list[Decision] = list(
            await asyncio.gather(
                *(slot.agent.decide(contexts[symbol], run_id=ctx.run_id) for slot, symbol in pairs)
            )
        )
        weights = {slot.agent.instance_id: slot.weight for slot in self.agents}
        for symbol in sorted(contexts):
            votes = [(d, weights[d.instance_id]) for d in decisions if d.symbol == symbol]
            aggregated[symbol] = aggregate(
                ctx.run_id, symbol, votes, self.options.aggregation, created_at=ctx.as_of
            )

        await self._repos.decisions.add_decisions(decisions)
        await self._repos.decisions.add_aggregated([aggregated[s] for s in ctx.universe])
        for d in decisions:
            ctx.decisions.setdefault(d.symbol, []).append(d)
        ctx.aggregated_decisions.update(aggregated)
        log.info(
            "decision.done",
            final={s: a.final_action.value for s, a in aggregated.items()},
            fallbacks=sum(d.error is not None for d in decisions),
            insufficient_data=sorted(set(ctx.universe) - set(contexts)),
            stored_sentiment=sorted(
                s for s, c in contexts.items() if c.sentiment and not c.sentiment_from_this_run
            ),
            with_fundamentals=sorted(s for s, c in contexts.items() if c.fundamentals),
        )
        return ctx


def build_decision_stage(config: StageConfig, services: Services) -> DecisionStage:
    """Stage factory (entry point `quant.stages: decision`).

    Services: `repos`, `config_store`, `llm` (LLMClientPool), `pipeline` (PipelineConfig:
    the budget that bounds the sub-ledger, and the market benchmark).
    """
    repos = services.get("repos", Repositories)
    agents = instantiate_agents(
        config.agents,
        role=AgentRole.DECISION,
        default_cls=DecisionAgent,
        store=services.get("config_store", ConfigStore),
        llm=services.get("llm", LLMClientPool),
        recorder=repos.llm_calls,
    )
    pipeline = services.get("pipeline", PipelineConfig)
    return DecisionStage(
        config.options(DecisionOptions),
        agents,
        repos,
        pipeline.budget.max_capital,
        pipeline.benchmark,
    )
