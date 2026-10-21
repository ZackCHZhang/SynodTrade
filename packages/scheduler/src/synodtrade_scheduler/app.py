"""The scheduler: only decides *when* to run *which* pipeline; the pipeline does the rest.

Jobs live in the database (APScheduler SQLAlchemyJobStore), so a restart keeps them and a
run missed while the scheduler was down still happens if within `misfire_grace_minutes`.
Overlapping runs are prevented twice: APScheduler `max_instances=1` in-process, and the
pipeline runner's database check across processes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from synodtrade_core.config import AccountConfig, ConfigError, ConfigStore
from synodtrade_core.logging import get_logger
from synodtrade_core.timeutil import DISPLAY_TZ, EXCHANGE_TZ
from synodtrade_pipeline import PipelineBusyError, PipelineRunner, RunOptions
from synodtrade_scheduler.config import JobConfig, SchedulesConfig
from synodtrade_scheduler.health import HealthChecker
from synodtrade_scheduler.notify import Level, Notifier
from synodtrade_scheduler.triggers import build_trigger

log = get_logger(__name__)

JOB_FUNC = "synodtrade_scheduler.app:run_scheduled_job"
_current: SchedulerApp | None = None


async def run_scheduled_job(pipeline: str, dry_run: bool) -> None:
    """What APScheduler stores and calls (by reference, so jobs survive restarts)."""
    if _current is None:
        raise RuntimeError("no scheduler app is running")
    await _current.run_job(pipeline, dry_run)


def sync_jobstore_url(url: str) -> str:
    """APScheduler 3 needs a synchronous SQLAlchemy driver."""
    return url.replace("+asyncpg", "+psycopg").replace("+aiosqlite", "")


def times(t: datetime | None) -> dict[str, str | None]:
    if t is None:
        return {"new_york": None, "berlin": None}
    return {
        "new_york": t.astimezone(EXCHANGE_TZ).isoformat(timespec="minutes"),
        "berlin": t.astimezone(DISPLAY_TZ).isoformat(timespec="minutes"),
    }


class SchedulerApp:
    def __init__(
        self,
        schedules: SchedulesConfig,
        store: ConfigStore,
        runner: PipelineRunner,
        health: HealthChecker,
        notifier: Notifier,
        *,
        jobstore_url: str | None = None,
    ) -> None:
        self.schedules = schedules
        self.store = store
        self.runner = runner
        self.health = health
        self.notifier = notifier
        store_: Any = (
            SQLAlchemyJobStore(url=sync_jobstore_url(jobstore_url))
            if jobstore_url
            else MemoryJobStore()
        )
        self.scheduler = AsyncIOScheduler(
            jobstores={"default": store_}, timezone=ZoneInfo(schedules.timezone)
        )

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Start (paused), reconcile stored jobs with the config, then resume.

        Jobs whose definition did not change are kept as stored, so a fire time missed
        while the scheduler was down is still honoured (within the misfire grace).
        """
        global _current
        _current = self
        self.scheduler.start(paused=True)
        wanted: dict[str, JobConfig] = {
            job_id: job
            for job_id, job in zip(self.schedules.job_ids(), self.schedules.jobs, strict=True)
            if job.enabled
        }
        for job in self.scheduler.get_jobs():
            if job.id not in wanted:
                job.remove()
                log.info("scheduler.job_removed", job_id=job.id)
        for job_id, cfg in wanted.items():
            trigger = build_trigger(cfg, self.schedules)
            args = [cfg.pipeline, cfg.dry_run]
            existing = self.scheduler.get_job(job_id)
            unchanged = (
                existing is not None
                and str(existing.trigger) == str(trigger)
                and list(existing.args) == args
                and existing.misfire_grace_time == cfg.misfire_grace_minutes * 60
            )
            if not unchanged:
                self.scheduler.add_job(
                    JOB_FUNC,
                    trigger=trigger,
                    args=args,
                    id=job_id,
                    name=cfg.pipeline,
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=cfg.misfire_grace_minutes * 60,
                )
        self.scheduler.resume()
        for job in self.scheduler.get_jobs():
            log.info(
                "scheduler.job",
                job_id=job.id,
                trigger=str(job.trigger),
                next_run=times(job.next_run_time),
            )

    def shutdown(self) -> None:
        global _current
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        if _current is self:
            _current = None

    # ------------------------------------------------------------ one run

    async def run_job(self, pipeline: str, dry_run: bool) -> None:
        log.info("scheduler.wake", pipeline=pipeline, dry_run=dry_run)
        try:
            config = self.store.pipeline(pipeline)
            account: AccountConfig | None = self.store.account(config.account)
        except ConfigError as exc:
            await self.notifier.notify(Level.ERROR, f"{pipeline}: invalid config", str(exc))
            return
        health = await self.health.check(config, account, dry_run=dry_run)
        if not health.ok:
            await self.notifier.notify(
                Level.ERROR,
                f"{pipeline}: health check failed, run skipped",
                "\n".join(health.problems),
            )
            return
        try:
            report = await self.runner.run(pipeline, RunOptions(dry_run=dry_run))
        except PipelineBusyError as exc:
            await self.notifier.notify(
                Level.WARNING, f"{pipeline}: previous run still busy", str(exc)
            )
            return
        except Exception as exc:
            await self.notifier.notify(
                Level.ERROR, f"{pipeline}: run crashed", f"{type(exc).__name__}: {exc}"
            )
            return
        if report.ok:
            log.info("scheduler.run_ok", pipeline=pipeline, run_id=str(report.run_id))
        else:
            errors = "\n".join(f"{e.stage}: {e.message}" for e in report.errors)
            await self.notifier.notify(
                Level.ERROR, f"{pipeline}: run {report.run_id} failed", errors
            )
