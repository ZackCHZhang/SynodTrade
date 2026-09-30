"""Build a pipeline from configs/ and run it: one run_id, one record, fail-safe stage policy."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from quant_core.config import (
    AccountConfig,
    ConfigError,
    ConfigStore,
    OnError,
    PipelineConfig,
    StageConfig,
    config_hash,
    resolve_model,
)
from quant_core.interfaces import Stage
from quant_core.llm import LLMClientPool
from quant_core.logging import bind_run, get_logger
from quant_core.models import PipelineContext, RunMode, StageError
from quant_core.registry import STAGES
from quant_core.safety import ensure_mode_allowed
from quant_core.services import Services
from quant_core.timeutil import utcnow
from quant_database import Database, PipelineRun, Repositories, RunStatus
from quant_market_data import DataUpdater, IBKRMarketDataProvider, MarketDataProvider
from quant_pipeline.offline import (
    OfflineLLMStyle,
    offline_candidate_sources,
    offline_llm,
    offline_market_data,
    offline_sentiment_sources,
    offline_symbols,
)
from quant_trading import Broker, create_broker

log = get_logger(__name__)

# Short names accepted by `--stages`.
STAGE_ALIASES = {
    "select": "selection",
    "selection": "selection",
    "data": "data_update",
    "sentiment": "sentiment",
    "decision": "decision",
    "risk": "risk",
    "trading": "trading",
    "trade": "trading",
}


class PipelineBusyError(RuntimeError):
    """Another run of the same pipeline is still in progress."""


@dataclass(frozen=True, slots=True)
class RunOptions:
    dry_run: bool = False  # force dry_run mode whatever the config says
    paper: bool = False  # run in paper mode whatever the config says (never live)
    stages: Sequence[str] | None = None  # subset of stage types (aliases allowed)
    as_of: datetime | None = None  # default: now
    offline: bool = False  # fake market data, sentiment and LLM; implies dry_run
    offline_llm: OfflineLLMStyle = "neutral"  # bullish: fake decisions say buy
    max_run_minutes: int = 180  # an older unfinished run is considered crashed


@dataclass(slots=True)
class RunReport:
    run_id: UUID
    pipeline: str
    mode: RunMode
    status: RunStatus
    summary: dict[str, Any]
    context: PipelineContext | None = None
    errors: list[StageError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status is RunStatus.SUCCEEDED


def select_stages(pipeline: PipelineConfig, wanted: Sequence[str] | None) -> list[StageConfig]:
    enabled = [s for s in pipeline.stages if s.enabled]
    if not wanted:
        return enabled
    types = {STAGE_ALIASES.get(w.strip(), w.strip()) for w in wanted if w.strip()}
    unknown = types - {s.type for s in enabled}
    if unknown:
        raise ConfigError(f"pipeline {pipeline.name} has no enabled stages {sorted(unknown)}")
    return [s for s in enabled if s.type in types]


class PipelineRunner:
    """Runs pipelines against one database. `overrides` replace any service by name
    (e.g. `broker`, `market_data`, `llm`, `sentiment_sources`, `market_clock`)."""

    def __init__(
        self,
        store: ConfigStore,
        db: Database,
        *,
        overrides: Mapping[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.store = store
        self.db = db
        self.repos = Repositories.create(db)
        self._overrides = dict(overrides or {})
        self._env = os.environ if env is None else env

    # ------------------------------------------------------------ services

    def _services(
        self,
        pipeline: PipelineConfig,
        stages: list[StageConfig],
        mode: RunMode,
        options: RunOptions,
        as_of: datetime,
    ) -> Services:
        types = {s.type for s in stages}
        o = self._overrides
        items: dict[str, Any] = {
            "repos": self.repos,
            "config_store": self.store,
            "pipeline": pipeline,
        }
        account: AccountConfig | None = None
        try:
            account = self.store.account(pipeline.account)
            items["account"] = account
        except ConfigError:
            if not options.offline:
                raise

        llm = o.get("llm")
        if llm is None:
            llm = LLMClientPool(self.store.llm_providers(), env=self._env)
            providers = {
                resolve_model(self.store.agent(ref.agent), ref.model).provider
                for s in stages
                for ref in s.agents
            }
            if options.offline:
                for name in providers:
                    llm.set(name, offline_llm(options.offline_llm))
            else:
                llm.check(sorted(providers))  # fail fast on missing API keys
        items["llm"] = llm

        # Symbols the run may touch: the universe, or with a selection stage every candidate.
        symbols = offline_symbols(pipeline, stages) if options.offline else pipeline.universe
        if types & {"selection", "data_update"}:  # one market data connection for both
            if "market_data" in o:
                items["market_data"] = o["market_data"]
            elif options.offline:
                items["market_data"] = offline_market_data(symbols, as_of)
            else:
                assert account is not None
                items["market_data"] = IBKRMarketDataProvider.from_account(account)
        if "selection" in types:
            items["bars_refresher"] = o.get("bars_refresher") or DataUpdater(
                items["market_data"], self.repos
            )
            if "candidate_sources" in o:
                items["candidate_sources"] = o["candidate_sources"]
            elif options.offline:
                stage = next(s for s in stages if s.type == "selection")
                items["candidate_sources"] = offline_candidate_sources(stage)
        if "sentiment" in types:
            if "sentiment_sources" in o:
                items["sentiment_sources"] = o["sentiment_sources"]
            elif options.offline:
                stage = next(s for s in stages if s.type == "sentiment")
                items["sentiment_sources"] = offline_sentiment_sources(
                    getattr(stage, "sources", None) or ["reddit", "stocktwits", "ibkr_news"],
                    symbols,
                    as_of,
                )
        if "trading" in types:
            items["broker"] = o.get("broker") or create_broker(mode, account, self._env)
        for name in ("market_clock",):
            if name in o:
                items[name] = o[name]
        return Services(**items)

    @staticmethod
    async def _close(services: Services, stages: list[Stage]) -> None:
        for stage in stages:
            close = getattr(stage, "aclose", None)
            if close is not None:
                await close()
        market_data = services.optional("market_data", MarketDataProvider)
        if market_data is not None:
            await market_data.disconnect()
        broker = services.optional("broker", Broker)
        if broker is not None:
            await broker.disconnect()
        llm = services.optional("llm", LLMClientPool)
        if llm is not None:
            await llm.aclose()

    # ------------------------------------------------------------ run

    async def _check_not_running(self, pipeline: str, now: datetime, max_minutes: int) -> None:
        for run in await self.repos.runs.running_runs(pipeline):
            if now - run.started_at < timedelta(minutes=max_minutes):
                raise PipelineBusyError(
                    f"pipeline {pipeline} is already running (run {run.run_id}, "
                    f"started {run.started_at.isoformat()})"
                )
            await self.repos.runs.finish_run(
                run.run_id, RunStatus.FAILED, error="stale: never finished (process died?)"
            )
            log.warning("pipeline.stale_run_closed", stale_run_id=str(run.run_id))

    def _config_snapshot(self, pipeline: PipelineConfig) -> tuple[str, dict[str, Any]]:
        agents = {
            ref.agent: self.store.agent(ref.agent) for s in pipeline.stages for ref in s.agents
        }
        models = [pipeline, *agents.values()]
        snapshot = {
            "pipeline": pipeline.model_dump(mode="json"),
            "agents": {k: v.model_dump(mode="json") for k, v in agents.items()},
        }
        return config_hash(*models), snapshot

    async def run(self, pipeline_name: str, options: RunOptions | None = None) -> RunReport:
        options = options or RunOptions()
        pipeline = self.store.validate_pipeline(pipeline_name)
        offline = options.offline
        if options.dry_run and options.paper:
            raise ConfigError("choose either dry_run or paper, not both")
        if options.dry_run or offline:
            mode = RunMode.DRY_RUN
        elif options.paper:
            mode = RunMode.PAPER
        else:
            mode = pipeline.mode
        ensure_mode_allowed(mode, self._env)
        stage_configs = select_stages(pipeline, options.stages)
        started = utcnow()
        as_of = options.as_of or started
        await self._check_not_running(pipeline.name, started, options.max_run_minutes)

        run_id = uuid4()
        digest, snapshot = self._config_snapshot(pipeline)
        await self.repos.runs.start_run(
            PipelineRun(
                run_id=run_id,
                pipeline_name=pipeline.name,
                mode=mode,
                config_hash=digest,
                config={
                    **snapshot,
                    "stages_run": [s.type for s in stage_configs],
                    "offline": offline,
                },
                as_of=as_of,
                started_at=started,
            )
        )
        ctx = PipelineContext(
            run_id=run_id,
            pipeline_name=pipeline.name,
            mode=mode,
            universe=pipeline.universe,
            as_of=as_of,
            started_at=started,
        )
        timings: dict[str, dict[str, Any]] = {}
        services: Services | None = None
        stages: list[Stage] = []
        with bind_run(run_id, pipeline.name):
            log.info(
                "pipeline.start",
                mode=mode.value,
                stages=[s.type for s in stage_configs],
                as_of=as_of.isoformat(),
            )
            try:
                services = self._services(pipeline, stage_configs, mode, options, as_of)
                built = [(cfg, STAGES.get(cfg.type)(cfg, services)) for cfg in stage_configs]
                stages = [stage for _, stage in built]
            except Exception as exc:  # configuration / credentials: nothing ran
                ctx.errors.append(
                    StageError(
                        stage="setup",
                        error_type=type(exc).__name__,
                        message=str(exc),
                        skipped=False,
                    )
                )
                built = []
            for cfg, stage in built:
                t0 = time.perf_counter()
                try:
                    ctx = await stage.run(ctx)
                    ctx.completed_stages.append(cfg.type)
                    status = "ok"
                except Exception as exc:
                    skip = cfg.on_error is OnError.SKIP
                    ctx.errors.append(
                        StageError(
                            stage=cfg.type,
                            error_type=type(exc).__name__,
                            message=str(exc),
                            skipped=skip,
                        )
                    )
                    log.error(
                        "pipeline.stage_failed",
                        stage=cfg.type,
                        skipped=skip,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    status = "failed_skipped" if skip else "failed"
                timings[cfg.type] = {
                    "status": status,
                    "seconds": round(time.perf_counter() - t0, 3),
                }
                if ctx.aborted:
                    break  # fail-safe: later stages (and so trading) never run
            if services is not None:
                await self._close(services, stages)

            status = RunStatus.FAILED if ctx.aborted else RunStatus.SUCCEEDED
            summary = summarize(ctx, timings)
            await self.repos.runs.finish_run(
                run_id,
                status,
                error="; ".join(f"{e.stage}: {e.message}" for e in ctx.errors if not e.skipped)
                or None,
                summary=summary,
            )
            log.info("pipeline.finish", status=status.value, summary=summary)
        return RunReport(run_id, pipeline.name, mode, status, summary, ctx, list(ctx.errors))


def summarize(ctx: PipelineContext, timings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    statuses = {r.client_order_id: r.status.value for r in ctx.order_results}
    selection = ctx.selection
    return {
        "mode": ctx.mode.value,
        "as_of": ctx.as_of.isoformat(),
        "stages": timings,
        "universe": list(ctx.universe),
        **(
            {
                "selection": {
                    "method": selection.method,
                    "candidates": len(selection.candidates),
                    "selected": selection.selected,
                    "holdings": selection.holdings,
                    "scores": {s: selection.scores[s] for s in selection.selected},
                }
            }
            if selection is not None
            else {}
        ),
        "sentiment_results": sum(len(v) for v in ctx.sentiment_results.values()),
        "decisions": sum(len(v) for v in ctx.decisions.values()),
        "final_decisions": {s: d.final_action.value for s, d in ctx.aggregated_decisions.items()},
        "risk": {s: v.adjusted_action.value for s, v in ctx.risk_verdicts.items()},
        "orders": {
            i.symbol: statuses.get(i.client_order_id, "not_submitted") for i in ctx.order_intents
        },
        "errors": [e.model_dump() for e in ctx.errors],
    }
