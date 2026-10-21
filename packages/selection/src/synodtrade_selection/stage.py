"""`selection` pipeline stage: candidates -> bars -> screen -> agents pick -> aggregate.

The result replaces the run's universe, so every later stage (data update, sentiment,
decision, risk, trading) works on the selected stocks. Symbols the strategy currently holds
stay in the universe (`keep_holdings`), so a stock that drops out of the selection can
still be sold by the decision stage.
"""

from __future__ import annotations

import asyncio
import statistics
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from synodtrade_core.agent_factory import AgentSlot, instantiate_agents
from synodtrade_core.config import AgentRole, ConfigStore, PipelineConfig, StageConfig
from synodtrade_core.fundamentals import fundamental_summary
from synodtrade_core.indicators import compute_indicators, relative_to
from synodtrade_core.interfaces import BarsRefresher, CandidateSource, FundamentalsRefresher
from synodtrade_core.llm import LLMClientPool
from synodtrade_core.logging import get_logger
from synodtrade_core.models import (
    Bar,
    Candidate,
    PipelineContext,
    SelectionPick,
    SelectionResult,
    StockSelection,
    Timeframe,
    WatchlistEntry,
)
from synodtrade_core.registry import CANDIDATE_SOURCES
from synodtrade_core.services import Services
from synodtrade_database import AgentInstance, Repositories
from synodtrade_selection.agent import SelectionAgent
from synodtrade_selection.aggregation import SelectionAggregation, aggregate_selection
from synodtrade_selection.screen import CandidateProfile, ScreenOptions, avg_dollar_volume, screen
from synodtrade_selection.sources import (
    CandidateSourceError,
    StaticCandidateSource,
    StaticSourceOptions,
)

log = get_logger(__name__)

UNIVERSE_SOURCE = "universe"
WATCHLIST_SOURCE = "watchlist"  # entries of the pipeline's watchlist (`watchlist.enabled`)


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


class WatchlistOptions(BaseModel):
    """`watchlist:` of the selection stage: follow picks across runs instead of replacing
    the universe every run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    max_age_days: int = Field(default=10, ge=1, le=365)  # removed after N days not picked
    max_size: int = Field(default=15, ge=1, le=100)  # stalest entries beyond this are removed


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
    # Company fundamentals (SEC EDGAR) of the screened candidates, refreshed when older than
    # `fundamentals_max_age_hours` and shown to the agents. Needs the `fundamentals` service.
    fundamentals: bool = False
    fundamentals_max_age_hours: float = Field(default=20, gt=0)
    # Newest stored sentiment analyses (earlier runs, any pipeline) of the last N hours. 0: off.
    stored_sentiment_hours: int = Field(default=48, ge=0, le=24 * 30)
    watchlist: WatchlistOptions = Field(default_factory=WatchlistOptions)

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
        *,
        benchmark: str | None = None,
        fundamentals: FundamentalsRefresher | None = None,
    ) -> None:
        self.options = options
        self.sources = sources
        self.agents = agents
        self._repos = repos
        self._max_capital = max_capital
        self._bars = bars
        self._benchmark = benchmark
        self._fundamentals = fundamentals

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
            extra = [self._benchmark] if self._benchmark and self._benchmark not in found else []
            errors = await self._bars.refresh_bars(
                [*found, *extra],
                timeframe=self.options.timeframe,
                lookback=timedelta(days=self.options.lookback_days),
                now=ctx.as_of,
            )
        if self._benchmark is not None and self._benchmark not in found:
            errors.pop(self._benchmark, None)  # the benchmark is context, not a candidate
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

    async def _refresh_fundamentals(self, symbols: list[str], ctx: PipelineContext) -> None:
        if not self.options.fundamentals:
            return
        if self._fundamentals is None:
            log.warning("selection.fundamentals_unavailable", reason="no fundamentals source")
            return
        try:
            errors = await self._fundamentals.refresh_fundamentals(
                symbols,
                now=ctx.as_of,
                max_age=timedelta(hours=self.options.fundamentals_max_age_hours),
            )
        except Exception as exc:  # context only: selection goes on without it
            log.warning("selection.fundamentals_failed", error=f"{type(exc).__name__}: {exc}")
            return
        if errors:
            log.warning("selection.fundamentals_errors", errors=errors)

    async def _relative(self, symbol: str, benchmark: list[Bar], ctx: PipelineContext) -> str:
        if self._benchmark is None or len(benchmark) < 30:
            return ""
        bars = await self._repos.bars.get_latest_bars(
            symbol, self.options.bars_lookback, self.options.timeframe, as_of=ctx.as_of
        )
        rel = relative_to(bars, benchmark, self._benchmark)
        parts = [
            f"{label} {value * 100:+.1f}%"
            for label, value in (
                (f"vs {self._benchmark} 60d", rel.relative_return_60d),
                ("1y", rel.relative_return_250d),
            )
            if value is not None
        ]
        if rel.beta_1y is not None:
            parts.append(f"beta {rel.beta_1y:.2f}")
        return ", ".join(parts)

    async def _sentiment(self, symbol: str, ctx: PipelineContext) -> str:
        hours = self.options.stored_sentiment_hours
        if hours <= 0:
            return ""
        results = await self._repos.sentiment.get_latest_results(
            symbol, ctx.as_of - timedelta(hours=hours), ctx.as_of
        )
        if not results:
            return ""
        mean = statistics.fmean(r.sentiment for r in results)
        events = [e for r in results for e in r.key_events][:3]
        text = f"{mean:+.2f} from {len(results)} analyses"
        return text + (f"; events: {'; '.join(events)}" if events else "")

    async def _enrich(self, profiles: list[CandidateProfile], ctx: PipelineContext) -> None:
        """Add fundamentals, relative strength and stored sentiment to the screened
        candidates (one-line summaries; every number computed in code)."""
        symbols = [p.symbol for p in profiles]
        if not symbols:
            return
        await self._refresh_fundamentals(symbols, ctx)
        stored = await self._repos.fundamentals.get_latest_many(symbols, ctx.as_of)
        benchmark: list[Bar] = []
        if self._benchmark is not None:
            benchmark = await self._repos.bars.get_latest_bars(
                self._benchmark, self.options.bars_lookback, self.options.timeframe, as_of=ctx.as_of
            )
        for profile in profiles:
            summary = fundamental_summary(stored.get(profile.symbol), profile.indicators.last_close)
            for key, value in (
                ("fundamentals", summary),
                ("relative", await self._relative(profile.symbol, benchmark, ctx)),
                ("sentiment", await self._sentiment(profile.symbol, ctx)),
            ):
                if value:
                    profile.extra[key] = value

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        ledger = await self._repos.ledger.get_state(
            ctx.pipeline_name, self._max_capital, as_of=ctx.as_of
        )
        holdings = sorted(ledger.positions) if self.options.keep_holdings else []
        found = await self._collect(ctx)
        watched = await self._watched(ctx, found)
        profiles, bar_errors = await self._profiles(found, set(ledger.positions), ctx)
        kept, rejected = screen(profiles, self.options.screen)
        for symbol, error in bar_errors.items():
            if symbol in rejected:
                rejected[symbol] += f"; data update failed: {error}"
        await self._enrich(kept, ctx)

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
                            watchlist_days=self.options.watchlist.max_age_days
                            if self.options.watchlist.enabled
                            else None,
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

        agents_failed = method.startswith("fallback_")
        watchlist = await self._update_watchlist(
            ctx, selected, scores, results, holdings, watched, update=not agents_failed
        )
        selection = StockSelection(
            created_at=ctx.as_of,
            run_id=ctx.run_id,
            pipeline_name=ctx.pipeline_name,
            method=method,
            candidates=candidates,
            selected=selected,
            holdings=holdings,
            watchlist=[s for s in watchlist if s not in selected],
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
            watchlist=selection.watchlist,
            holdings=holdings,
            fallbacks=sum(r.error is not None for r in results),
        )
        return ctx

    async def _watched(
        self, ctx: PipelineContext, found: dict[str, list[Candidate]]
    ) -> list[WatchlistEntry]:
        """Active watchlist entries; each becomes a candidate again (re-screened, re-scored)."""
        if not self.options.watchlist.enabled:
            return []
        entries = await self._repos.watchlist.get_active(ctx.pipeline_name, ctx.as_of)
        for e in entries:
            since = e.added_at.date().isoformat()
            note = f"on the watchlist since {since}, picked {e.times_selected}x"
            if e.pinned:
                note += ", pinned"
            found.setdefault(e.symbol, []).append(
                Candidate(symbol=e.symbol, source=WATCHLIST_SOURCE, note=note)
            )
        return entries

    async def _update_watchlist(
        self,
        ctx: PipelineContext,
        selected: list[str],
        scores: dict[str, float],
        results: list[SelectionResult],
        holdings: list[str],
        watched: list[WatchlistEntry],
        *,
        update: bool,
    ) -> list[str]:
        """Add this run's picks, drop stale entries; returns the watchlist's symbols."""
        opts = self.options.watchlist
        if not opts.enabled:
            return []
        if not update:  # every agent failed: leave the list as it is
            return [e.symbol for e in watched]
        best: dict[str, SelectionPick] = {}
        for r in results:
            for pick in r.picks:
                if pick.symbol not in best or pick.score > best[pick.symbol].score:
                    best[pick.symbol] = pick
        added = await self._repos.watchlist.record_selection(
            ctx.pipeline_name,
            [(s, scores.get(s), best[s].reason if s in best else None) for s in selected],
            ctx.as_of,
        )
        removed = await self._repos.watchlist.expire(
            ctx.pipeline_name,
            ctx.as_of,
            max_age=timedelta(days=opts.max_age_days),
            max_size=opts.max_size,
            keep=[*holdings, *selected],
        )
        active = await self._repos.watchlist.get_active(ctx.pipeline_name, ctx.as_of)
        log.info("selection.watchlist", added=added, removed=removed, size=len(active))
        return [e.symbol for e in active]


def build_selection_stage(config: StageConfig, services: Services) -> SelectionStage:
    """Stage factory (entry point `synodtrade.stages: selection`).

    Services: `repos`, `config_store`, `llm` (LLMClientPool), `pipeline` (PipelineConfig:
    universe, budget and benchmark); optional `bars_refresher` (BarsRefresher) to fetch bars
    of the candidates, `fundamentals` (FundamentalsRefresher) for their fundamentals, and
    `candidate_sources` (dict name -> CandidateSource) overriding the registry, e.g. fakes.
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
        benchmark=pipeline.benchmark,
        fundamentals=services.optional("fundamentals", FundamentalsRefresher),
    )
