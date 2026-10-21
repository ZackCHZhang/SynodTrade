"""The scheduler as seen from the web UI: plan preview, health checks, and an optional
scheduler embedded in the server process (start/stop from the UI).

The embedded scheduler keeps its jobs in memory, so it never competes with a standalone
`synodtrade-scheduler run` over the database job store. Running both at once is still safe
(the pipeline runner refuses overlapping runs) but wakes pipelines twice; don't.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from synodtrade_core.config import ConfigError, ConfigStore
from synodtrade_core.timeutil import utcnow
from synodtrade_database import Database
from synodtrade_pipeline import PipelineRunner
from synodtrade_scheduler import (
    HealthChecker,
    SchedulerApp,
    build_trigger,
    default_notifier,
    load_schedules,
    upcoming,
)
from synodtrade_scheduler.app import times


def _times(t: datetime | None) -> dict[str, str | None]:
    return {"utc": t.isoformat() if t else None, **times(t)}


class SchedulerController:
    def __init__(self, configs: Path, db: Database, env: Mapping[str, str] | None = None) -> None:
        self._configs = configs
        self._db = db
        self._env = env
        self.app: SchedulerApp | None = None
        self.started_at: datetime | None = None

    def _store(self) -> ConfigStore:
        return ConfigStore(self._configs, env=self._env)

    def plan(self, days: int) -> dict[str, Any]:
        store = self._store()
        schedules = load_schedules(store, strict=False)
        now = utcnow()
        jobs = []
        for job_id, job in zip(schedules.job_ids(), schedules.jobs, strict=True):
            trigger = build_trigger(job, schedules)
            fires = upcoming(trigger, now, now + timedelta(days=days)) if job.enabled else []
            jobs.append(
                {
                    "id": job_id,
                    "config": job.model_dump(mode="json"),
                    "trigger": str(trigger),
                    "upcoming": [_times(t) for t in fires],
                }
            )
        return {
            "calendar": schedules.calendar,
            "timezone": schedules.timezone,
            "days": days,
            "jobs": jobs,
        }

    def status(self) -> dict[str, Any]:
        app = self.app
        running = app is not None and app.scheduler.running
        jobs = []
        if running and app is not None:
            for job in app.scheduler.get_jobs():
                jobs.append(
                    {
                        "id": job.id,
                        "pipeline": job.name,
                        "trigger": str(job.trigger),
                        "dry_run": bool(job.args[1]) if len(job.args) > 1 else False,
                        "next_run": _times(job.next_run_time),
                    }
                )
        return {
            "running": running,
            "started_at": self.started_at.isoformat() if running and self.started_at else None,
            "jobs": jobs,
        }

    def start(self) -> dict[str, Any]:
        if self.app is not None and self.app.scheduler.running:
            return self.status()
        store = self._store()
        schedules = load_schedules(store, strict=True)  # raises ConfigError with all problems
        app = SchedulerApp(
            schedules,
            store,
            PipelineRunner(store, self._db, env=self._env),
            HealthChecker(self._db),
            default_notifier(),
        )
        app.start()
        self.app = app
        self.started_at = utcnow()
        return self.status()

    def stop(self) -> dict[str, Any]:
        if self.app is not None:
            self.app.shutdown()
        self.app = None
        self.started_at = None
        return self.status()

    def reload(self) -> dict[str, Any]:
        self.stop()
        return self.start()

    async def check(self) -> list[dict[str, Any]]:
        """Pre-run health checks (database, IB Gateway) for every scheduled pipeline."""
        store = self._store()
        schedules = load_schedules(store, strict=False)
        checker = HealthChecker(self._db)
        results = []
        for job in schedules.jobs:
            try:
                pipeline = store.pipeline(job.pipeline)
                account = store.account(pipeline.account)
            except ConfigError as exc:
                results.append({"pipeline": job.pipeline, "ok": False, "problems": [str(exc)]})
                continue
            report = await checker.check(pipeline, account, dry_run=job.dry_run)
            results.append(
                {"pipeline": job.pipeline, "ok": report.ok, "problems": list(report.problems)}
            )
        return results
