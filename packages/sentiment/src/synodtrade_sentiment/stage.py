"""`sentiment` pipeline stage: collect -> store -> prefilter -> analyse -> store."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from synodtrade_core.agent_factory import AgentSlot, instantiate_agents
from synodtrade_core.config import AgentRole, ConfigStore, StageConfig
from synodtrade_core.interfaces import SentimentSource
from synodtrade_core.llm import LLMClientPool
from synodtrade_core.logging import get_logger
from synodtrade_core.models import PipelineContext, SentimentItem, SentimentResult
from synodtrade_core.registry import SENTIMENT_SOURCES
from synodtrade_core.services import Services
from synodtrade_database import AgentInstance, Repositories
from synodtrade_sentiment.agent import SentimentAgent
from synodtrade_sentiment.prefilter import PrefilterOptions, prefilter

log = get_logger(__name__)


class SentimentOptions(BaseModel):
    """Options of the `sentiment` stage in configs/pipelines/*.yaml."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    sources: list[str] = Field(default_factory=lambda: ["reddit", "stocktwits"], min_length=1)
    source_options: dict[str, dict[str, Any]] = Field(default_factory=dict)
    lookback_hours: int = Field(default=24, ge=1, le=24 * 30)
    prefilter: PrefilterOptions = Field(default_factory=PrefilterOptions)
    min_sources_ok: int = Field(default=1, ge=0)


class SentimentError(RuntimeError):
    pass


class UnavailableSource:
    """Stands in for a source that could not be created; fails like any broken source."""

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason

    async def fetch(self, symbols: Sequence[str], since: datetime) -> list[SentimentItem]:
        raise SentimentError(f"{self.name} unavailable: {self.reason}")


class SentimentStage:
    name = "sentiment"

    def __init__(
        self,
        options: SentimentOptions,
        sources: list[SentimentSource],
        agents: list[AgentSlot[SentimentAgent]],
        repos: Repositories,
    ) -> None:
        self.options = options
        self.sources = sources
        self.agents = agents
        self._repos = repos

    async def aclose(self) -> None:
        for source in self.sources:
            close = getattr(source, "aclose", None)
            if close is not None:
                await close()

    async def _collect(self, ctx: PipelineContext) -> int:
        since = ctx.as_of - timedelta(hours=self.options.lookback_hours)
        outcomes = await asyncio.gather(
            *(s.fetch(ctx.universe, since) for s in self.sources), return_exceptions=True
        )
        fetched: list[SentimentItem] = []
        failures: dict[str, str] = {}
        for source, outcome in zip(self.sources, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                failures[source.name] = f"{type(outcome).__name__}: {outcome}"
            else:
                fetched += outcome
        if failures:
            log.warning("sentiment.source_failures", failures=failures)
        if len(self.sources) - len(failures) < self.options.min_sources_ok:
            raise SentimentError(f"not enough sentiment sources succeeded: {failures}")
        inserted = await self._repos.sentiment.add_items(fetched)
        log.info("sentiment.collected", fetched=len(fetched), new=inserted)
        return inserted

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        await self._collect(ctx)

        # Analyse everything stored for the window (also posts collected by earlier runs or
        # other pipelines), never anything created after as_of.
        since = ctx.as_of - timedelta(hours=self.options.lookback_hours)
        stored: list[SentimentItem] = []
        for symbol in ctx.universe:
            stored += await self._repos.sentiment.get_items(symbol, since, as_of=ctx.as_of)
        batches = prefilter(stored, self.options.prefilter, ctx.as_of)

        await self._repos.runs.register_agent_instances(
            [AgentInstance.from_agent(slot.agent, ctx.run_id) for slot in self.agents]
        )
        results: list[SentimentResult] = list(
            await asyncio.gather(
                *(
                    slot.agent.analyze(
                        symbol,
                        items,
                        run_id=ctx.run_id,
                        as_of=ctx.as_of,
                        lookback_hours=self.options.lookback_hours,
                    )
                    for slot in self.agents
                    for symbol, items in sorted(batches.items())
                    if items
                )
            )
        )
        await self._repos.sentiment.add_results(results)
        for result in results:
            ctx.sentiment_results.setdefault(result.symbol, []).append(result)
        log.info(
            "sentiment.analysed",
            results=len(results),
            fallbacks=sum(r.error is not None for r in results),
            symbols_without_posts=sorted(set(ctx.universe) - set(batches)),
        )
        return ctx


def build_sentiment_stage(config: StageConfig, services: Services) -> SentimentStage:
    """Stage factory (entry point `synodtrade.stages: sentiment`).

    Services: `repos`, `config_store` (ConfigStore), `llm` (LLMClientPool); optional
    `sentiment_sources` (dict name -> SentimentSource) overriding the registry, e.g. fakes.
    """
    options = config.options(SentimentOptions)
    repos = services.get("repos", Repositories)
    provided = services.optional("sentiment_sources", dict) or {}
    sources: list[SentimentSource] = []
    for name in options.sources:
        if name in provided:
            sources.append(provided[name])
            continue
        try:
            sources.append(SENTIMENT_SOURCES.get(name)(options.source_options.get(name, {})))
        except Exception as exc:  # e.g. missing credentials: only this source is lost
            log.warning("sentiment.source_unavailable", source=name, error=str(exc))
            sources.append(UnavailableSource(name, f"{type(exc).__name__}: {exc}"))
    agents = instantiate_agents(
        config.agents,
        role=AgentRole.SENTIMENT,
        default_cls=SentimentAgent,
        store=services.get("config_store", ConfigStore),
        llm=services.get("llm", LLMClientPool),
        recorder=repos.llm_calls,
    )
    return SentimentStage(options, sources, agents, repos)
