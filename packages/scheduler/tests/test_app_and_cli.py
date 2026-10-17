import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml
from typer.testing import CliRunner

import quant_scheduler.app as app_module
from quant_core.config import ConfigStore
from quant_core.models import RunMode, StageError
from quant_database import Database, RunStatus
from quant_pipeline import PipelineBusyError, RunOptions, RunReport
from quant_scheduler import (
    HealthChecker,
    Level,
    SchedulerApp,
    load_schedules,
    run_scheduled_job,
    sync_jobstore_url,
)
from quant_scheduler.cli import app as cli_app

# The model arena's scheduled pipelines (configs/schedules.yaml): multi-agent and single-agent.
ARENA_MODELS = ("deepseek", "qwen", "glm", "gpt", "claude")
ARENA_JOBS = {f"arena_{m}#0" for m in ARENA_MODELS} | {f"arena_solo_{m}#0" for m in ARENA_MODELS}


@dataclass
class Recorder:
    alerts: list[tuple[Level, str, str]] = field(default_factory=list)

    async def notify(self, level: Level, title: str, message: str) -> None:
        self.alerts.append((level, title, message))


class FakeRunner:
    def __init__(self, outcome: Any = "ok") -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, RunOptions]] = []

    async def run(self, pipeline: str, options: RunOptions) -> RunReport:
        self.calls.append((pipeline, options))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        status = RunStatus.SUCCEEDED if self.outcome == "ok" else RunStatus.FAILED
        errors = (
            []
            if self.outcome == "ok"
            else [StageError(stage="decision", error_type="X", message="boom", skipped=False)]
        )
        return RunReport(uuid4(), pipeline, RunMode.PAPER, status, {}, None, errors)


async def up(host: str, port: int, limit_s: float) -> bool:
    return True


async def down(host: str, port: int, limit_s: float) -> bool:
    return False


def make_app(
    store: ConfigStore,
    db: Database,
    runner: Any = None,
    *,
    tcp: Any = up,
    jobstore_url: str | None = None,
) -> tuple[SchedulerApp, Recorder, Any]:
    recorder = Recorder()
    runner = runner or FakeRunner()
    scheduler = SchedulerApp(
        load_schedules(store),
        store,
        runner,
        HealthChecker(db, tcp_check=tcp),
        recorder,
        jobstore_url=jobstore_url,
    )
    return scheduler, recorder, runner


def test_sync_jobstore_url() -> None:
    assert sync_jobstore_url("postgresql+asyncpg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert sync_jobstore_url("sqlite+aiosqlite:///x.db") == "sqlite:///x.db"


# ------------------------------------------------------------------ scheduling


async def test_jobs_are_registered_with_overlap_protection(
    store: ConfigStore, db: Database
) -> None:
    scheduler, _, _ = make_app(store, db)
    scheduler.start()
    try:
        jobs = {j.id: j for j in scheduler.scheduler.get_jobs()}
        assert set(jobs) == {"long_term_stocks#0", "etf_allocation#0", *ARENA_JOBS}
        job = jobs["long_term_stocks#0"]
        assert (job.max_instances, job.coalesce, job.misfire_grace_time) == (1, True, 900)
        assert job.args == ("long_term_stocks", False)
        assert str(job.trigger) == "market_relative[XNYS open+30m]"
        assert job.next_run_time is not None
        assert app_module._current is scheduler
    finally:
        scheduler.shutdown()
    assert app_module._current is None


async def test_jobs_survive_restarts_and_follow_config_changes(
    configs: Path, store: ConfigStore, db: Database, tmp_path: Path
) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}"
    first, _, _ = make_app(store, db, jobstore_url=url)
    first.start()
    before = {j.id: j.next_run_time for j in first.scheduler.get_jobs()}
    first.shutdown()

    second, _, _ = make_app(store, db, jobstore_url=url)
    second.start()
    assert {j.id: j.next_run_time for j in second.scheduler.get_jobs()} == before  # kept as stored
    second.shutdown()

    path = configs / "schedules.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["jobs"] = data["jobs"][:2]  # removed jobs go away too
    data["jobs"][0]["offset_minutes"] = 45
    data["jobs"][1]["enabled"] = False
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    third, _, _ = make_app(ConfigStore(configs, env=store._env), db, jobstore_url=url)
    third.start()
    jobs = third.scheduler.get_jobs()
    assert [j.id for j in jobs] == ["long_term_stocks#0"]  # disabled job removed
    assert str(jobs[0].trigger) == "market_relative[XNYS open+45m]"  # changed job replaced
    third.shutdown()


# ------------------------------------------------------------------ one wake-up


async def test_run_job_success(store: ConfigStore, db: Database) -> None:
    scheduler, recorder, runner = make_app(store, db)
    await scheduler.run_job("long_term_stocks", False)
    assert runner.calls[0][0] == "long_term_stocks"
    assert runner.calls[0][1].dry_run is False
    assert recorder.alerts == []


async def test_run_job_skips_on_failed_health_check(store: ConfigStore, db: Database) -> None:
    scheduler, recorder, runner = make_app(store, db, tcp=down)
    await scheduler.run_job("long_term_stocks", False)
    assert runner.calls == []
    [(level, title, message)] = recorder.alerts
    assert level is Level.ERROR
    assert "health check failed" in title
    assert "IB Gateway unreachable" in message


@pytest.mark.parametrize(
    ("outcome", "level", "title"),
    [
        (PipelineBusyError("still running"), Level.WARNING, "previous run still busy"),
        (RuntimeError("kaput"), Level.ERROR, "run crashed"),
        ("failed", Level.ERROR, "failed"),
    ],
)
async def test_run_job_alerts(
    store: ConfigStore, db: Database, outcome: Any, level: Level, title: str
) -> None:
    scheduler, recorder, _ = make_app(store, db, FakeRunner(outcome))
    await scheduler.run_job("long_term_stocks", False)
    [(got_level, got_title, _)] = recorder.alerts
    assert got_level is level
    assert title in got_title


async def test_run_job_with_invalid_config(store: ConfigStore, db: Database) -> None:
    scheduler, recorder, runner = make_app(store, db)
    await scheduler.run_job("ghost", False)
    assert runner.calls == []
    assert "invalid config" in recorder.alerts[0][1]


async def test_scheduled_job_function_uses_the_running_app(
    store: ConfigStore, db: Database
) -> None:
    with pytest.raises(RuntimeError, match="no scheduler app"):
        await run_scheduled_job("long_term_stocks", False)
    scheduler, _, runner = make_app(store, db)
    scheduler.start()
    try:
        await run_scheduled_job("long_term_stocks", True)
    finally:
        scheduler.shutdown()
    assert runner.calls[0][1].dry_run is True


# ------------------------------------------------------------------ CLI


def test_cli_plan(configs: Path) -> None:
    result = CliRunner().invoke(cli_app, ["plan", "--days", "8", "--configs", str(configs)])
    assert result.exit_code == 0, result.output
    assert "long_term_stocks#0  market_relative[XNYS open+30m]" in result.output
    assert "etf_allocation#0  cron[0 11 * * MON" in result.output
    assert "Berlin" in result.output


def test_cli_check_reports_unreachable_gateway(
    configs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
    monkeypatch.setenv("IBKR_ACCOUNT", "DU1")
    monkeypatch.setenv("IBKR_PORT", str(closed))
    url = f"sqlite+aiosqlite:///{tmp_path / 'c.db'}"
    result = CliRunner().invoke(cli_app, ["check", "--configs", str(configs), "--db-url", url])
    assert result.exit_code == 1
    assert "FAIL  long_term_stocks" in result.output
    assert f"IB Gateway unreachable at 127.0.0.1:{closed}" in result.output


def test_cli_invalid_config_and_missing_db(configs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IBKR_ACCOUNT", raising=False)
    monkeypatch.delenv("QUANT_DATABASE_URL", raising=False)
    result = CliRunner().invoke(cli_app, ["check", "--configs", str(configs)])
    assert result.exit_code == 1
    assert "invalid configuration" in result.output


def test_cli_run_starts_and_stops(
    configs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    async def stop_immediately(self: asyncio.Event) -> bool:
        return True  # as if SIGINT/SIGTERM arrived right after start-up

    monkeypatch.setattr(asyncio.Event, "wait", stop_immediately)
    monkeypatch.setenv("IBKR_ACCOUNT", "DU1")
    url = f"sqlite+aiosqlite:///{tmp_path / 'run.db'}"
    result = CliRunner().invoke(
        cli_app, ["run", "--configs", str(configs), "--db-url", url, "--log-level", "WARNING"]
    )
    assert result.exit_code == 0, result.output
    assert app_module._current is None  # shut down cleanly

    import sqlite3

    with sqlite3.connect(tmp_path / "run.db") as conn:  # jobs were persisted
        ids = {row[0] for row in conn.execute("SELECT id FROM apscheduler_jobs")}
    assert ids == {"long_term_stocks#0", "etf_allocation#0", *ARENA_JOBS}
