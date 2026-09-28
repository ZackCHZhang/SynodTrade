"""`quant-scheduler` command line.

quant-scheduler run                # start the scheduler (until Ctrl+C / SIGTERM)
quant-scheduler plan --days 7      # upcoming runs, New York and Berlin time
quant-scheduler check              # health checks for every scheduled pipeline, once
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import typer

from quant_core.config import ConfigError, ConfigStore
from quant_core.logging import configure_logging
from quant_core.timeutil import utcnow
from quant_database import DATABASE_URL_ENV, Database
from quant_pipeline import PipelineRunner
from quant_scheduler.app import SchedulerApp, times
from quant_scheduler.config import SchedulesConfig, load_schedules
from quant_scheduler.health import HealthChecker
from quant_scheduler.notify import default_notifier
from quant_scheduler.triggers import build_trigger, upcoming

app = typer.Typer(help="Wakes pipelines on exchange-calendar schedules.", no_args_is_help=True)

ConfigsOption = Annotated[Path, typer.Option("--configs", help="configs directory")]
DbOption = Annotated[str | None, typer.Option("--db-url", help="database URL")]


def _load(store: ConfigStore, *, strict: bool = True) -> SchedulesConfig:
    try:
        return load_schedules(store, strict=strict)
    except ConfigError as exc:
        typer.echo(f"invalid configuration:\n{exc}", err=True)
        raise typer.Exit(1) from exc


def _db_url(explicit: str | None) -> str:
    url = explicit or os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise typer.BadParameter(f"no database: pass --db-url or set {DATABASE_URL_ENV}")
    return url


@app.command()
def run(
    configs: ConfigsOption = Path("configs"),
    db_url: DbOption = None,
    log_level: Annotated[str, typer.Option("--log-level")] = "INFO",
) -> None:
    """Start the scheduler and keep running until interrupted."""
    configure_logging(log_level)
    url = _db_url(db_url)
    store = ConfigStore(configs)
    schedules = _load(store)

    async def main() -> None:
        db = Database(url)
        scheduler = SchedulerApp(
            schedules,
            store,
            PipelineRunner(store, db),
            HealthChecker(db),
            default_notifier(),
            jobstore_url=url,
        )
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):  # not available on Windows
                loop.add_signal_handler(sig, stop.set)
        scheduler.start()
        try:
            await stop.wait()
        finally:
            scheduler.shutdown()
            await db.dispose()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())


@app.command()
def plan(
    days: Annotated[int, typer.Option("--days", min=1, max=366)] = 7,
    configs: ConfigsOption = Path("configs"),
) -> None:
    """Show when each scheduled pipeline will run next."""
    store = ConfigStore(configs)
    schedules = _load(store, strict=False)
    now = utcnow()
    for job_id, job in zip(schedules.job_ids(), schedules.jobs, strict=True):
        state = "" if job.enabled else "  (disabled)"
        trigger = build_trigger(job, schedules)
        typer.echo(f"{job_id}  {trigger}{state}")
        for t in upcoming(trigger, now, now + timedelta(days=days)):
            local = times(t)
            typer.echo(f"    New York {local['new_york']}   Berlin {local['berlin']}")


@app.command()
def check(configs: ConfigsOption = Path("configs"), db_url: DbOption = None) -> None:
    """Run the pre-run health checks for every scheduled pipeline."""
    store = ConfigStore(configs)
    schedules = _load(store)
    url = _db_url(db_url)

    async def main() -> bool:
        db = Database(url)
        checker = HealthChecker(db)
        healthy = True
        try:
            for job in schedules.jobs:
                pipeline = store.pipeline(job.pipeline)
                report = await checker.check(
                    pipeline, store.account(pipeline.account), dry_run=job.dry_run
                )
                typer.echo(
                    f"{'ok  ' if report.ok else 'FAIL'}  {job.pipeline}"
                    + "".join(f"\n      {p}" for p in report.problems)
                )
                healthy &= report.ok
        finally:
            await db.dispose()
        return healthy

    raise typer.Exit(0 if asyncio.run(main()) else 1)
