"""`synodtrade` command line.

    synodtrade run --pipeline long_term_stocks --dry-run
    synodtrade run --pipeline long_term_stocks --stages data,sentiment
    synodtrade run --pipeline long_term_stocks --offline          # no gateway, keys or network
    synodtrade validate [--pipeline NAME]
    synodtrade kill-switch on --reason "..." | off | status

The database comes from --db-url or SYNODTRADE_DATABASE_URL (offline runs default to a local
SQLite file). Configs come from --configs (default ./configs).
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer

from synodtrade_core.config import ConfigError, ConfigStore
from synodtrade_core.envfile import load_env_file
from synodtrade_core.logging import configure_logging
from synodtrade_core.timeutil import to_utc
from synodtrade_database import DATABASE_URL_ENV, KILL_SWITCH, Database, Repositories
from synodtrade_pipeline.benchmark import build_curves, write_benchmark
from synodtrade_pipeline.runner import PipelineRunner, RunOptions

app = typer.Typer(help="Multi-agent IBKR trading pipelines.", no_args_is_help=True)


@app.callback()
def _load_env(
    env_file: Annotated[Path, typer.Option("--env-file", help="settings/secrets file")] = Path(
        ".env"
    ),
) -> None:
    """Loads --env-file (default .env) without overriding variables already set."""
    load_env_file(env_file)


OFFLINE_DB = "sqlite+aiosqlite:///./synodtrade_offline.db"
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
    paper: Annotated[
        bool, typer.Option("--paper", help="run in paper mode whatever the config says")
    ] = False,
    stages: Annotated[
        str | None, typer.Option("--stages", help="comma list, e.g. select,data,sentiment")
    ] = None,
    offline: Annotated[
        bool, typer.Option("--offline", help="fake data/LLM/broker; implies --dry-run")
    ] = False,
    offline_llm: Annotated[
        str,
        typer.Option("--offline-llm", help="offline fake LLM: neutral (holds) or bullish (buys)"),
    ] = "neutral",
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
        paper=paper,
        stages=stages.split(",") if stages else None,
        as_of=parse_as_of(as_of) if as_of is not None else None,
        offline=offline,
        offline_llm="bullish" if offline_llm == "bullish" else "neutral",
    )
    if offline_llm not in ("neutral", "bullish"):
        raise typer.BadParameter("--offline-llm must be neutral or bullish")

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


@app.command()
def benchmark(
    pipeline: Annotated[
        list[str] | None,
        typer.Option("--pipeline", "-p", help="pipeline to include (repeatable); default: all"),
    ] = None,
    out: Annotated[Path, typer.Option("--out", help="output folder")] = Path("benchmark"),
    end: Annotated[
        str | None, typer.Option("--end", help="last day, YYYY-MM-DD (default: today)")
    ] = None,
    readme: Annotated[
        list[Path] | None,
        typer.Option("--readme", help="README to update between the benchmark markers"),
    ] = None,
    configs: ConfigsOption = Path("configs"),
    db_url: DbOption = None,
) -> None:
    """Write the paper-trading benchmark (README pages, equity.svg, data.json) to --out.

    Covers every pipeline that ran in paper or live mode, and updates the summary between
    `<!-- benchmark:start -->` and `<!-- benchmark:end -->` in README.md and README.zh-CN.md.
    """
    url = _db_url(db_url, offline=False)
    try:
        last = date.fromisoformat(end) if end else None
    except ValueError as exc:
        raise typer.BadParameter(f"--end: not a date: {end!r}") from exc
    readmes = readme if readme is not None else [Path("README.md"), Path("README.zh-CN.md")]

    async def main() -> list[Path]:
        db = Database(url)
        try:
            curves = await build_curves(
                Repositories.create(db),
                ConfigStore(configs, env=dict(os.environ)),
                pipeline,
                end=last,
            )
        finally:
            await db.dispose()
        for c in curves:
            if c.bars_through is None or c.bars_through < c.points[-1].day:
                typer.echo(
                    f"warning: {c.pipeline}: {c.benchmark} daily bars end {c.bars_through};"
                    " later sessions use the last known closes. Run data_update first.",
                    err=True,
                )
        return write_benchmark(curves, out, readmes=readmes)

    try:
        written = asyncio.run(main())
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    for path in written:
        typer.echo(f"wrote {path}")


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
