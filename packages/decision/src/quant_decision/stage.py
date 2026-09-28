"""`decision` pipeline stage: build per-symbol context -> agents decide -> aggregate -> store."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from quant_core.agent_factory import AgentSlot, instantiate_agents
from quant_core.config import AgentRole, ConfigStore, PipelineConfig, StageConfig
from quant_core.indicators import compute_indicators
from quant_core.llm import LLMClientPool
from quant_core.logging import get_logger
from quant_core.models import Action, AggregatedDecision, Decision, PipelineContext, Timeframe
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


class DecisionStage:
    name = "decision"

    def __init__(
        self,
        options: DecisionOptions,
        agents: list[AgentSlot[DecisionAgent]],
        repos: Repositories,
        max_capital: Decimal,
    ) -> None:
        self.options = options
        self.agents = agents
        self._repos = repos
        self._max_capital = max_capital

    async def _context(
        self, symbol: str, ctx: PipelineContext, ledger: LedgerState, nav: Decimal
    ) -> SymbolContext | None:
        bars = await self._repos.bars.get_latest_bars(
            symbol, self.options.bars_lookback, self.options.timeframe, as_of=ctx.as_of
        )
        if len(bars) < self.options.min_bars:
            return None
        past = await self._repos.decisions.get_recent_aggregated(
            symbol, self.options.history_limit, as_of=ctx.as_of
        )
        return SymbolContext(
            symbol=symbol,
            as_of=ctx.as_of,
            bars=bars,
            indicators=compute_indicators(bars),
            ledger=ledger,
            nav=nav,
            sentiment=ctx.sentiment_results.get(symbol, []),
            history=history_entries(past, bars, TIMEFRAME_DURATION[self.options.timeframe]),
            recent_bars_in_prompt=self.options.recent_bars_in_prompt,
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
        contexts: dict[str, SymbolContext] = {}
        aggregated: dict[str, AggregatedDecision] = {}
        for symbol in ctx.universe:
            context = await self._context(symbol, ctx, ledger, nav)
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
        )
        return ctx


def build_decision_stage(config: StageConfig, services: Services) -> DecisionStage:
    """Stage factory (entry point `quant.stages: decision`).

    Services: `repos`, `config_store`, `llm` (LLMClientPool), `pipeline` (PipelineConfig,
    for the budget that bounds the sub-ledger).
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
        config.options(DecisionOptions), agents, repos, pipeline.budget.max_capital
    )
