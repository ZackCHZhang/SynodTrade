"""`quant` command line.

    quant run --pipeline long_term_stocks --dry-run
    quant run --pipeline long_term_stocks --stages data,sentiment
    quant run --pipeline long_term_stocks --offline          # no gateway, keys or network
    quant validate [--pipeline NAME]
    quant kill-switch on --reason "..." | off | status

The database comes from --db-url or QUANT_DATABASE_URL (offline runs default to a local
SQLite file). Configs come from --configs (default ./configs).
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from quant_core.config import ConfigError, ConfigStore
from quant_core.logging import configure_logging
from quant_core.timeutil import to_utc
from quant_database import DATABASE_URL_ENV, KILL_SWITCH, Database, Repositories
from quant_pipeline.runner import PipelineRunner, RunOptions

app = typer.Typer(help="Multi-agent IBKR trading pipelines.", no_args_is_help=True)

OFFLINE_DB = "sqlite+aiosqlite:///./quant_offline.db"
OFFLINE_ENV = {"IBKR_ACCOUNT": "DU0000000"}  # placeholder account for offline runs

ConfigsOption = Annotated[Path, typer.Option("--configs", help="configs directory")]
DbOption = Annotated[str | None, typer.Option("--db-url", help="database URL")]


def parse_as_of(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"--as-of: not an ISO-8601 datetime: {value!r}") from exc
    return to_utc(parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC))


def _db_url(explicit: str | None, offline: bool) -> str:
    url = explicit or os.environ.get(DATABASE_URL_ENV)
    if url:
        return url
    if offline:
        return OFFLINE_DB
    raise typer.BadParameter(f"no database: pass --db-url or set {DATABASE_URL_ENV}")


def _store(configs: Path, offline: bool) -> ConfigStore:
    env = {**OFFLINE_ENV, **os.environ} if offline else dict(os.environ)
    return ConfigStore(configs, env=env)


@app.command()
def run(
    pipeline: Annotated[str, typer.Option("--pipeline", "-p", help="pipeline name")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="never send orders")] = False,
    stages: Annotated[
        str | None, typer.Option("--stages", help="comma list, e.g. data,sentiment")
    ] = None,
    offline: Annotated[
        bool, typer.Option("--offline", help="fake data/LLM/broker; implies --dry-run")
    ] = False,
    as_of: Annotated[
        str | None,
        typer.Option("--as-of", help="ISO-8601 point in time; no offset means UTC (default: now)"),
    ] = None,
    configs: ConfigsOption = Path("configs"),
    db_url: DbOption = None,
    init_db: Annotated[bool, typer.Option("--init-db", help="create missing tables")] = False,
    log_level: Annotated[str, typer.Option("--log-level")] = "INFO",
) -> None:
    """Run one pipeline once."""
    configure_logging(log_level)
    url = _db_url(db_url, offline)
    options = RunOptions(
        dry_run=dry_run,
        stages=stages.split(",") if stages else None,
        as_of=parse_as_of(as_of) if as_of is not None else None,
        offline=offline,
    )

    async def main() -> int:
        db = Database(url)
        try:
            if init_db or (offline and url == OFFLINE_DB):
                await db.create_all()
            report = await PipelineRunner(_store(configs, offline), db).run(pipeline, options)
        finally:
            await db.dispose()
        typer.echo(
            json.dumps(
                {"run_id": str(report.run_id), "status": report.status.value, **report.summary},
                indent=2,
                default=str,
            )
        )
        return 0 if report.ok else 1

    raise typer.Exit(asyncio.run(main()))


@app.command()
def validate(
    pipeline: Annotated[str | None, typer.Option("--pipeline", "-p")] = None,
    configs: ConfigsOption = Path("configs"),
) -> None:
    """Validate pipeline configs and everything they reference."""
    store = ConfigStore(configs)
    names = [pipeline] if pipeline else store.list("pipelines")
    failed = False
    for name in names:
        try:
            store.validate_pipeline(name)
            typer.echo(f"ok      {name}")
        except ConfigError as exc:
            failed = True
            typer.echo(f"invalid {name}:\n{exc}", err=True)
    raise typer.Exit(1 if failed else 0)


@app.command("kill-switch")
def kill_switch(
    action: Annotated[str, typer.Argument(help="on | off | status")],
    reason: Annotated[str | None, typer.Option("--reason")] = None,
    db_url: DbOption = None,
) -> None:
    """Global kill switch: while on, no pipeline sends orders."""
    if action not in ("on", "off", "status"):
        raise typer.BadParameter("action must be on, off or status")
    url = _db_url(db_url, offline=False)

    async def main() -> str:
        db = Database(url)
        try:
            flags = Repositories.create(db).flags
            if action != "status":
                await flags.set(KILL_SWITCH, action == "on", reason)
            active = await flags.kill_switch_active()
            why = await flags.get_reason(KILL_SWITCH)
        finally:
            await db.dispose()
        return f"kill switch {'ON' if active else 'off'}" + (f" ({why})" if active and why else "")

    typer.echo(asyncio.run(main()))
