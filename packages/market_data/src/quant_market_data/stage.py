"""`data_update` pipeline stage."""

from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel, ConfigDict, Field

from quant_core.config import AccountConfig, PipelineConfig, StageConfig
from quant_core.interfaces import FundamentalsRefresher
from quant_core.logging import get_logger
from quant_core.models import PipelineContext, Timeframe
from quant_core.services import Services
from quant_database import Repositories
from quant_market_data.provider import MarketDataProvider
from quant_market_data.updater import DataUpdater

log = get_logger(__name__)


class DataUpdateOptions(BaseModel):
    """Options of the `data_update` stage in configs/pipelines/*.yaml."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    timeframes: list[Timeframe] = Field(default_factory=lambda: [Timeframe.D1], min_length=1)
    lookback_days: int = Field(default=365, gt=0, le=3650)
    quotes: bool = True
    account: bool = True
    # Fail the stage (and so, by default, the run) if any symbol could not be updated.
    # Decisions on stale data are worse than no decisions.
    fail_on_error: bool = True
    # Company fundamentals (SEC EDGAR filings) for the universe; failures never fail the stage.
    fundamentals: bool = False
    fundamentals_max_age_hours: float = Field(default=20, gt=0)


class DataUpdateError(RuntimeError):
    pass


class DataUpdateStage:
    name = "data_update"

    def __init__(
        self,
        options: DataUpdateOptions,
        updater: DataUpdater,
        account_id: str | None = None,
        *,
        benchmark: str | None = None,
        fundamentals: FundamentalsRefresher | None = None,
    ) -> None:
        self.options = options
        self._updater = updater
        self._account_id = account_id
        self._benchmark = benchmark
        self._fundamentals = fundamentals

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        await self._updater.provider.connect()  # idempotent; the pipeline disconnects at the end
        report = await self._updater.update(
            ctx.universe,
            timeframes=self.options.timeframes,
            lookback=timedelta(days=self.options.lookback_days),
            now=ctx.as_of,
            quotes=self.options.quotes,
            account_id=self._account_id if self.options.account else None,
        )
        log.info(
            "data_update.done",
            bars=sum(report.bars_written.values()),
            quotes=report.quotes_written,
            positions=report.positions_written,
            errors=report.errors,
        )
        await self._update_benchmark(ctx)
        await self._update_fundamentals(ctx)
        if report.errors and self.options.fail_on_error:
            raise DataUpdateError(f"data update failed for: {report.errors}")
        return ctx

    async def _update_benchmark(self, ctx: PipelineContext) -> None:
        """Daily bars of the market benchmark: context for the later stages, never traded."""
        if self._benchmark is None or self._benchmark in ctx.universe:
            return
        errors = await self._updater.refresh_bars(
            [self._benchmark],
            timeframe=Timeframe.D1,
            lookback=timedelta(days=self.options.lookback_days),
            now=ctx.as_of,
        )
        if errors:
            log.warning("data_update.benchmark_failed", benchmark=self._benchmark, errors=errors)

    async def _update_fundamentals(self, ctx: PipelineContext) -> None:
        if not self.options.fundamentals:
            return
        if self._fundamentals is None:
            log.warning("data_update.fundamentals_unavailable", reason="no fundamentals source")
            return
        try:
            errors = await self._fundamentals.refresh_fundamentals(
                ctx.universe,
                now=ctx.as_of,
                max_age=timedelta(hours=self.options.fundamentals_max_age_hours),
            )
        except Exception as exc:  # fundamentals are context, not a reason to stop trading
            log.warning("data_update.fundamentals_failed", error=f"{type(exc).__name__}: {exc}")
            return
        if errors:
            log.warning("data_update.fundamentals_errors", errors=errors)


def build_data_update_stage(config: StageConfig, services: Services) -> DataUpdateStage:
    """Stage factory (entry point `quant.stages: data_update`).

    Services used: `repos` (Repositories), `market_data` (MarketDataProvider),
    optional `account` (AccountConfig) for account/position snapshots, `pipeline`
    (PipelineConfig: the benchmark) and `fundamentals` (FundamentalsRefresher).
    """
    options = config.options(DataUpdateOptions)
    account = services.optional("account", AccountConfig)
    updater = DataUpdater(
        services.get("market_data", MarketDataProvider),
        services.get("repos", Repositories),
    )
    pipeline = services.optional("pipeline", PipelineConfig)
    return DataUpdateStage(
        options,
        updater,
        account.account_id if account else None,
        benchmark=pipeline.benchmark if pipeline else None,
        fundamentals=services.optional("fundamentals", FundamentalsRefresher),
    )
