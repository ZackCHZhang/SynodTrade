"""configs/schedules.yaml: when to wake which pipeline."""

from __future__ import annotations

from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from quant_core.config import ConfigError, ConfigStore, load_model

SLUG = r"^[a-z][a-z0-9_]*$"


class JobConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pipeline: str = Field(pattern=SLUG)
    trigger: Literal["market_relative", "cron"]
    # market_relative: minutes after (positive) or before (negative) the open/close
    anchor: Literal["open", "close"] | None = None
    offset_minutes: int = Field(default=0, ge=-600, le=600)
    # cron: standard 5-field crontab, in the exchange timezone
    cron: str | None = None
    skip_non_trading_days: bool = True  # cron only; market_relative always uses sessions
    dry_run: bool = False
    enabled: bool = True
    misfire_grace_minutes: int = Field(default=15, ge=0, le=24 * 60)

    @model_validator(mode="after")
    def _check_trigger(self) -> Self:
        if self.trigger == "market_relative":
            if self.anchor is None:
                raise ValueError("market_relative jobs need an anchor (open or close)")
            if self.cron is not None:
                raise ValueError("market_relative jobs do not take a cron expression")
        else:
            if not self.cron:
                raise ValueError("cron jobs need a cron expression")
            if self.anchor is not None:
                raise ValueError("cron jobs do not take an anchor")
            CronTrigger.from_crontab(self.cron)  # raises ValueError if malformed
        return self


class SchedulesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    calendar: str = "XNYS"  # exchange_calendars code
    timezone: str = "America/New_York"  # cron expressions are read in this timezone
    jobs: list[JobConfig] = Field(default_factory=list)

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value

    def job_ids(self) -> list[str]:
        """Stable ids: `<pipeline>#<n>` for the n-th job of that pipeline."""
        seen: dict[str, int] = {}
        ids = []
        for job in self.jobs:
            n = seen.get(job.pipeline, 0)
            seen[job.pipeline] = n + 1
            ids.append(f"{job.pipeline}#{n}")
        return ids


def load_schedules(store: ConfigStore, *, strict: bool = True) -> SchedulesConfig:
    """Load and check that every scheduled pipeline exists. `strict` also validates
    everything the pipelines reference (accounts, agents, providers; needs the env)."""
    config = load_model(store.root / "schedules.yaml", SchedulesConfig, store._env)
    problems = []
    for job in config.jobs:
        try:
            if strict:
                store.validate_pipeline(job.pipeline)
            else:
                store.pipeline(job.pipeline)
        except ConfigError as exc:
            problems.append(f"schedule for {job.pipeline}: {exc}")
    if problems:
        raise ConfigError("\n".join(problems))
    return config
