"""`synodtrade-sync` command line.

synodtrade-sync once   # synchronise every account once and print what changed
synodtrade-sync loop   # synchronise every interval_minutes (configs/account_sync.yaml)
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from pathlib import Path
from typing import Annotated

import typer

from synodtrade_account_sync.service import AccountSyncService, PeriodicSync
from synodtrade_core.config import ConfigError, ConfigStore
from synodtrade_core.envfile import load_env_file
from synodtrade_core.logging import configure_logging
from synodtrade_database import DATABASE_URL_ENV, AccountSync, Database, Repositories, SyncStatus

app = typer.Typer(
    help="Synchronises IBKR accounts (orders, fills, positions) with the database.",
    no_args_is_help=True,
)


@app.callback()
def _load_env(
    env_file: Annotated[Path, typer.Option("--env-file", help="settings/secrets file")] = Path(
        ".env"
    ),
) -> None:
    """Loads --env-file (default .env) without overriding variables already set."""
    load_env_file(env_file)


ConfigsOption = Annotated[Path, typer.Option("--configs", help="configs directory")]
DbOption = Annotated[str | None, typer.Option("--db-url", help="database URL")]


def _db_url(explicit: str | None) -> str:
    url = explicit or os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise typer.BadParameter(f"no database: pass --db-url or set {DATABASE_URL_ENV}")
    return url


def describe(sync: AccountSync) -> str:
    """A few lines per synchronisation, for the terminal."""
    report = sync.report
    lines = [
        f"{sync.status.value.upper():8} {sync.account_id}  checked {sync.orders_checked}, "
        f"updated {sync.orders_updated}, new fills {sync.fills_added}"
    ]
    if sync.error:
        lines.append(f"    error: {sync.error}")
    for change in [*report.get("orders", []), *report.get("late_fills", [])]:
        lines.append(
            f"    {change['symbol']:6} {change['side']:4} {change['from_status']} -> "
            f"{change['to_status']}  filled {change['filled_qty']}  ({change['pipeline']})"
        )
    lines += [f"    warning: {w}" for w in report.get("warnings", [])]
    return "\n".join(lines)


@app.command()
def once(
    configs: ConfigsOption = Path("configs"),
    db_url: DbOption = None,
    log_level: Annotated[str, typer.Option("--log-level")] = "WARNING",
) -> None:
    """Synchronise every account once."""
    configure_logging(log_level)
    url = _db_url(db_url)

    async def main() -> bool:
        db = Database(url)
        try:
            service = AccountSyncService(ConfigStore(configs), Repositories.create(db))
            results = await service.sync_all(trigger="cli")
        finally:
            await db.dispose()
        for sync in results:
            typer.echo(describe(sync))
        if not results:
            typer.echo("no account to synchronise (no valid pipeline uses one)")
        return all(s.status is SyncStatus.OK for s in results)

    try:
        ok = asyncio.run(main())
    except ConfigError as exc:
        typer.echo(f"invalid configuration:\n{exc}", err=True)
        raise typer.Exit(1) from exc
    raise typer.Exit(0 if ok else 1)


@app.command()
def loop(
    configs: ConfigsOption = Path("configs"),
    db_url: DbOption = None,
    log_level: Annotated[str, typer.Option("--log-level")] = "INFO",
) -> None:
    """Synchronise periodically until interrupted (`enabled` / `interval_minutes`)."""
    configure_logging(log_level)
    url = _db_url(db_url)

    async def main() -> None:
        db = Database(url)
        periodic = PeriodicSync(
            AccountSyncService(ConfigStore(configs), Repositories.create(db)), trigger="cli"
        )
        stop = asyncio.Event()
        event_loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):  # not available on Windows
                event_loop.add_signal_handler(sig, stop.set)
        periodic.start()
        try:
            await stop.wait()
        finally:
            await periodic.stop()
            await db.dispose()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
