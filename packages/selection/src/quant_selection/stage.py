"""`selection` pipeline stage: candidates -> bars -> screen -> agents pick -> aggregate.

The result replaces the run's universe, so every later stage (data update, sentiment,
decision, risk, trading) works on the selected stocks. Symbols the strategy currently holds
stay in the universe (`keep_holdings`), so a stock that drops out of the selection can
still be sold by the decision stage.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_core.agent_factory import AgentSlot, instantiate_agents
from quant_core.config import AgentRole, ConfigStore, PipelineConfig, StageConfig
from quant_core.indicators import compute_indicators
from quant_core.interfaces import BarsRefresher, CandidateSource
from quant_core.llm import LLMClientPool
from quant_core.logging import get_logger
from quant_core.models import Candidate, PipelineContext, SelectionResult, StockSelection, Timeframe
from quant_core.registry import CANDIDATE_SOURCES
from quant_core.services import Services
from quant_database import AgentInstance, Repositories
from quant_selection.agent import SelectionAgent
from quant_selection.aggregation import SelectionAggregation, aggregate_selection
from quant_selection.screen import CandidateProfile, ScreenOptions, avg_dollar_volume, screen
from quant_selection.sources import CandidateSourceError, StaticCandidateSource, StaticSourceOptions

log = get_logger(__name__)

UNIVERSE_SOURCE = "universe"


class SelectionFallback(StrEnum):
    """What to select when every selection agent failed."""

    PREVIOUS = "previous"  # the pipeline's last selection (none yet: holdings only)
    HOLDINGS = "holdings"  # holdings only: nothing new is bought this run
    FAIL = "fail"  # fail the stage (and so, by default, the run)


class CandidateSourceConfig(BaseModel):
    """One entry of `sources:`: `{type: <registered source>, name: optional, ...options}`."""

    model_config = ConfigDict(extra="allow", frozen=True)

    type: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str | None = None

    @property
    def source_name(self) -> str:
        return self.name or self.type

    def source_options(self) -> dict[str, Any]:
        return {**(self.model_extra or {}), "name": self.source_name}


class SelectionOptions(BaseModel):
    """Options of the `selection` stage in configs/pipelines/*.yaml."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    sources: list[CandidateSourceConfig] = Field(default_factory=list)
    include_universe: bool = True  # the pipeline's `universe` is a candidate source too
    keep_holdings: bool = True
    max_raw_candidates: int = Field(default=60, ge=1, le=200)  # bounds bar requests
    timeframe: Timeframe = Timeframe.D1
    lookback_days: int = Field(default=400, ge=30, le=3650)
    bars_lookback: int = Field(default=260, ge=20, le=2000)
    refresh_bars: bool = True
    screen: ScreenOptions = Field(default_factory=ScreenOptions)
    aggregation: SelectionAggregation = Field(default_factory=SelectionAggregation)
    max_picks_per_agent: int = Field(default=10, ge=1, le=50)
    fallback: SelectionFallback = SelectionFallback.PREVIOUS

    @model_validator(mode="after")
    def _check(self) -> Self:
        names = [s.source_name for s in self.sources]
        if self.include_universe:
            names.append(UNIVERSE_SOURCE)
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"candidate source names must be unique (set `name:`): {dupes}")
        if not names:
            raise ValueError("selection needs candidate sources or include_universe: true")
        return self


class SelectionError(RuntimeError):
    pass


class SelectionStage:
    name = "selection"

    def __init__(
        self,
        options: SelectionOptions,
        sources: list[CandidateSource],
        agents: list[AgentSlot[SelectionAgent]],
        repos: Repositories,
        max_capital: Decimal,
        bars: BarsRefresher | None = None,
    ) -> None:
        self.options = options
        self.sources = sources
        self.agents = agents
        self._repos = repos
        self._max_capital = max_capital
        self._bars = bars

    async def aclose(self) -> None:
        for source in self.sources:
            close = getattr(source, "aclose", None)
            if close is not None:
                await close()

    async def _collect(self, ctx: PipelineContext) -> dict[str, list[Candidate]]:
        """symbol -> candidates, in source order then rank, capped at max_raw_candidates."""
        outcomes = await asyncio.gather(
            *(s.fetch(ctx.as_of) for s in self.sources), return_exceptions=True
        )
        found: dict[str, list[Candidate]] = {}
        failures: dict[str, str] = {}
        for source, outcome in zip(self.sources, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                failures[source.name] = f"{type(outcome).__name__}: {outcome}"
                continue
            for c in sorted(outcome, key=lambda c: c.rank if c.rank is not None else 1 << 30):
                found.setdefault(c.symbol, []).append(c)
        if failures:
            log.warning("selection.source_failures", failures=failures)
            if len(failures) == len(self.sources):
                raise CandidateSourceError(f"every candidate source failed: {failures}")
        dropped = list(found)[self.options.max_raw_candidates :]
        if dropped:
            log.warning("selection.candidates_capped", dropped=dropped)
        return {s: found[s] for s in list(found)[: self.options.max_raw_candidates]}

    async def _profiles(
        self, found: dict[str, list[Candidate]], held: set[str], ctx: PipelineContext
    ) -> tuple[list[CandidateProfile], dict[str, str]]:
        errors: dict[str, str] = {}
        if self._bars is not None and self.options.refresh_bars and found:
            errors = await self._bars.refresh_bars(
                list(found),
                timeframe=self.options.timeframe,
                lookback=timedelta(days=self.options.lookback_days),
                now=ctx.as_of,
            )
        profiles = []
        for symbol, candidates in found.items():
            bars = await self._repos.bars.get_latest_bars(
                symbol, self.options.bars_lookback, self.options.timeframe, as_of=ctx.as_of
            )
            profiles.append(
                CandidateProfile(
                    symbol=symbol,
                    candidates=candidates,
                    indicators=compute_indicators(bars),
                    avg_dollar_volume=avg_dollar_volume(bars),
                    held=symbol in held,
                )
            )
        return profiles, errors

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        ledger = await self._repos.ledger.get_state(
            ctx.pipeline_name, self._max_capital, as_of=ctx.as_of
        )
        holdings = sorted(ledger.positions) if self.options.keep_holdings else []
        found = await self._collect(ctx)
        profiles, bar_errors = await self._profiles(found, set(ledger.positions), ctx)
        kept, rejected = screen(profiles, self.options.screen)
        for symbol, error in bar_errors.items():
            if symbol in rejected:
                rejected[symbol] += f"; data update failed: {error}"

        previous = await self._repos.selection.get_latest(ctx.pipeline_name, as_of=ctx.as_of)
        await self._repos.runs.register_agent_instances(
            [AgentInstance.from_agent(slot.agent, ctx.run_id) for slot in self.agents]
        )
        results: list[SelectionResult] = []
        if kept:
            results = list(
                await asyncio.gather(
                    *(
                        slot.agent.select(
                            kept,
                            run_id=ctx.run_id,
                            pipeline_name=ctx.pipeline_name,
                            as_of=ctx.as_of,
                            max_picks=self.options.max_picks_per_agent,
                            previous=previous,
                            holdings=holdings,
                        )
                        for slot in self.agents
                    )
                )
            )
        await self._repos.selection.add_results(results)
        ctx.selection_results = results

        candidates = [p.symbol for p in kept]
        method = self.options.aggregation.describe()
        if results and all(r.error is not None for r in results):
            if self.options.fallback is SelectionFallback.FAIL:
                raise SelectionError(f"every selection agent failed: {results[0].error}")
            fallback = self.options.fallback
            if fallback is SelectionFallback.PREVIOUS and previous is not None:
                selected, method = list(previous.selected), "fallback_previous"
            else:
                selected, method = [], "fallback_holdings"
            scores: dict[str, float] = {}
            log.warning("selection.agents_failed", fallback=method, selected=selected)
        else:
            weights = {slot.agent.instance_id: slot.weight for slot in self.agents}
            selected, scores = aggregate_selection(
                [(r, weights[r.instance_id]) for r in results],
                candidates,
                self.options.aggregation,
            )

        selection = StockSelection(
            created_at=ctx.as_of,
            run_id=ctx.run_id,
            pipeline_name=ctx.pipeline_name,
            method=method,
            candidates=candidates,
            selected=selected,
            holdings=holdings,
            scores=scores,
            rejected=rejected,
        )
        await self._repos.selection.add_selection(selection)
        ctx.selection = selection
        ctx.universe = selection.universe
        log.info(
            "selection.done",
            candidates=len(found),
            screened=len(kept),
            selected=selected,
            holdings=holdings,
            fallbacks=sum(r.error is not None for r in results),
        )
        return ctx


def build_selection_stage(config: StageConfig, services: Services) -> SelectionStage:
    """Stage factory (entry point `quant.stages: selection`).

    Services: `repos`, `config_store`, `llm` (LLMClientPool), `pipeline` (PipelineConfig:
    universe and budget); optional `bars_refresher` (BarsRefresher) to fetch bars of the
    candidates, and `candidate_sources` (dict name -> CandidateSource) overriding the
    registry, e.g. fakes.
    """
    options = config.options(SelectionOptions)
    repos = services.get("repos", Repositories)
    pipeline = services.get("pipeline", PipelineConfig)
    provided = services.optional("candidate_sources", dict) or {}
    sources: list[CandidateSource] = []
    if options.include_universe and pipeline.universe:
        sources.append(
            StaticCandidateSource(
                StaticSourceOptions(name=UNIVERSE_SOURCE, symbols=pipeline.universe)
            )
        )
    for entry in options.sources:
        name = entry.source_name
        if name in provided:
            sources.append(provided[name])
        else:
            sources.append(CANDIDATE_SOURCES.get(entry.type)(entry.source_options()))
    agents = instantiate_agents(
        config.agents,
        role=AgentRole.SELECTION,
        default_cls=SelectionAgent,
        store=services.get("config_store", ConfigStore),
        llm=services.get("llm", LLMClientPool),
        recorder=repos.llm_calls,
    )
    if not agents:
        raise SelectionError("the selection stage needs at least one selection agent")
    return SelectionStage(
        options,
        sources,
        agents,
        repos,
        pipeline.budget.max_capital,
        services.optional("bars_refresher", BarsRefresher),
    )
