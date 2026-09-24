"""`data_update` pipeline stage."""

from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel, ConfigDict, Field

from quant_core.config import AccountConfig, StageConfig
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


class DataUpdateError(RuntimeError):
    pass


class DataUpdateStage:
    name = "data_update"

    def __init__(
        self,
        options: DataUpdateOptions,
        updater: DataUpdater,
        account_id: str | None = None,
    ) -> None:
        self.options = options
        self._updater = updater
        self._account_id = account_id

    async def run(self, ctx: PipelineContext) -> PipelineContext:
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
        if report.errors and self.options.fail_on_error:
            raise DataUpdateError(f"data update failed for: {report.errors}")
        return ctx


def build_data_update_stage(config: StageConfig, services: Services) -> DataUpdateStage:
    """Stage factory (entry point `quant.stages: data_update`).

    Services used: `repos` (Repositories), `market_data` (MarketDataProvider),
    optional `account` (AccountConfig) for account/position snapshots.
    """
    options = config.options(DataUpdateOptions)
    account = services.optional("account", AccountConfig)
    updater = DataUpdater(
        services.get("market_data", MarketDataProvider),
        services.get("repos", Repositories),
    )
    return DataUpdateStage(options, updater, account.account_id if account else None)
