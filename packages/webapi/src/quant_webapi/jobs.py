"""Pipeline runs started from the web UI, executed as tasks inside the server process."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import structlog
from pydantic import BaseModel, ConfigDict, Field

from quant_core.config import ConfigStore
from quant_core.logging import get_logger
from quant_core.timeutil import to_utc, utcnow
from quant_database import Database
from quant_pipeline import PipelineRunner, RunOptions
from quant_webapi.events import JOB_KEY, EventHub

log = get_logger(__name__)

OFFLINE_ENV = {"IBKR_ACCOUNT": "DU0000000"}  # same placeholder as `quant run --offline`

JobStatus = Literal["starting", "running", "succeeded", "failed", "error", "cancelled"]


class RunRequest(BaseModel):
    """What the "run pipeline" dialog sends."""

    model_config = ConfigDict(extra="forbid")

    pipeline: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    # config: the pipeline's own `mode`; dry_run / paper override it (never live).
    mode: Literal["config", "dry_run", "paper"] = "dry_run"
    offline: bool = False  # fake data, sentiment and LLM; implies dry_run
    offline_llm: Literal["neutral", "bullish"] = "neutral"
    stages: list[str] | None = None
    as_of: datetime | None = None


@dataclass(slots=True)
class Job:
    id: str
    request: RunRequest
    created_at: datetime
    status: JobStatus = "starting"
    run_id: str | None = None
    finished_at: datetime | None = None
    error: str | None = None
    summary: dict[str, Any] | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pipeline": self.request.pipeline,
            "request": self.request.model_dump(mode="json"),
            "status": self.status,
            "run_id": self.run_id,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
            "summary": self.summary,
            "database": "offline" if self.request.offline else "main",
        }


class JobManager:
    def __init__(
        self,
        configs_root: Path,
        db: Database,
        hub: EventHub,
        *,
        env: Mapping[str, str] | None = None,
        overrides: Mapping[str, Any] | None = None,
        max_jobs: int = 200,
        offline_db: Database | None = None,
    ) -> None:
        self._configs = configs_root
        self._db = db
        self._offline_db = offline_db
        self._hub = hub
        self._env = env
        self._overrides = overrides
        self._max_jobs = max_jobs
        self.jobs: dict[str, Job] = {}

    def _environment(self, offline: bool) -> dict[str, str]:
        env = dict(os.environ if self._env is None else self._env)
        return {**OFFLINE_ENV, **env} if offline else env

    def _database(self, request: RunRequest) -> Database:
        """Offline runs use the sandbox database: their fake bars must not replace real ones."""
        return self._offline_db if request.offline and self._offline_db is not None else self._db

    def all(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

    def get(self, job_id: str) -> Job:
        try:
            return self.jobs[job_id]
        except KeyError:
            raise LookupError(f"unknown job {job_id}") from None

    def active(self) -> list[Job]:
        return [j for j in self.jobs.values() if j.status in ("starting", "running")]

    async def start(self, request: RunRequest, *, wait_s: float = 3.0) -> Job:
        """Start a run; waits briefly so immediate failures (bad config, busy pipeline,
        live not allowed, missing keys) are reported to the caller right away."""
        job = Job(id=uuid4().hex[:12], request=request, created_at=utcnow())
        self.jobs[job.id] = job
        self._trim()
        job.task = asyncio.create_task(self._run(job), name=f"web-run-{job.id}")
        bound = asyncio.create_task(self._hub.wait_for_job(job.id))
        await asyncio.wait({job.task, bound}, timeout=wait_s, return_when="FIRST_COMPLETED")
        bound.cancel()
        if job.run_id is None:
            job.run_id = self._hub.job_runs.get(job.id)
        return job

    async def _run(self, job: Job) -> None:
        request = job.request
        env = self._environment(request.offline)
        options = RunOptions(
            dry_run=request.mode == "dry_run",
            paper=request.mode == "paper",
            stages=request.stages or None,
            as_of=to_utc(request.as_of) if request.as_of is not None else None,
            offline=request.offline,
            offline_llm=request.offline_llm,
        )
        runner = PipelineRunner(
            ConfigStore(self._configs, env=env),
            self._database(request),
            overrides=self._overrides,
            env=env,
        )
        job.status = "running"
        try:
            with structlog.contextvars.bound_contextvars(**{JOB_KEY: job.id}):
                report = await runner.run(request.pipeline, options)
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.error = "cancelled from the web UI"
            raise
        except Exception as exc:  # config errors, busy pipeline, live not allowed ...
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"
            log.warning("web.run_rejected", job=job.id, error=job.error)
        else:
            job.run_id = str(report.run_id)
            job.status = "succeeded" if report.ok else "failed"
            job.summary = report.summary
            if not report.ok:
                job.error = "; ".join(f"{e.stage}: {e.message}" for e in report.errors) or None
        finally:
            job.finished_at = utcnow()
            run_id = job.run_id or self._hub.job_runs.get(job.id)
            job.run_id = run_id
            if run_id is not None:
                self._hub.mark_ended(run_id)

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.task is not None and not job.task.done():
            job.task.cancel()
        return job

    async def shutdown(self) -> None:
        tasks = [j.task for j in self.jobs.values() if j.task is not None and not j.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _trim(self) -> None:
        finished = [j for j in self.all() if j.status not in ("starting", "running")]
        for job in finished[self._max_jobs :]:
            self.jobs.pop(job.id, None)
