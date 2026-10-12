"""`quant-web` command line.

    quant-web serve                          # http://127.0.0.1:8765, UI from web/dist
    quant-web serve --db-url sqlite+aiosqlite:///./paper_test.db --port 8000

The database comes from --db-url or QUANT_DATABASE_URL; without either, the local SQLite
file used by offline runs (created if missing). Offline runs started from the UI always use
that local file (./quant_offline.db), so their synthetic data never mixes with real data.

Binds to 127.0.0.1 by default: the UI can start runs that place paper (or, if allowed, live)
orders and has no login, so do not expose it publicly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from quant_core.envfile import load_env_file
from quant_database import DATABASE_URL_ENV
from quant_webapi.app import WebSettings, create_app

app = typer.Typer(help="Web console for configs, runs, scheduler and data.", no_args_is_help=True)

DEFAULT_DB = "sqlite+aiosqlite:///./quant_offline.db"  # same file as `quant run --offline`


@app.callback()
def _load_env(
    env_file: Annotated[Path, typer.Option("--env-file", help="settings/secrets file")] = Path(
        ".env"
    ),
) -> None:
    """Loads --env-file (default .env) without overriding variables already set."""
    load_env_file(env_file)


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8765,
    configs: Annotated[Path, typer.Option("--configs", help="configs directory")] = Path("configs"),
    db_url: Annotated[str | None, typer.Option("--db-url", help="database URL")] = None,
    static: Annotated[
        Path, typer.Option("--static", help="built web UI (npm run build in web/)")
    ] = Path("web/dist"),
    init_db: Annotated[bool, typer.Option("--init-db", help="create missing tables")] = False,
    log_level: Annotated[str, typer.Option("--log-level")] = "INFO",
    account_sync: Annotated[
        bool,
        typer.Option(
            "--account-sync/--no-account-sync",
            help="synchronise IBKR accounts periodically (configs/account_sync.yaml)",
        ),
    ] = True,
) -> None:
    """Start the web console."""
    if not configs.is_dir():
        raise typer.BadParameter(f"--configs: {configs} is not a directory")
    url = db_url or os.environ.get(DATABASE_URL_ENV) or DEFAULT_DB
    settings = WebSettings(
        configs=configs,
        db_url=url,
        offline_db_url=DEFAULT_DB,
        static_dir=static if static.is_dir() else None,
        create_tables=init_db or url == DEFAULT_DB,
        log_level=log_level,
        account_sync_loop=account_sync,
    )
    if settings.static_dir is None:
        typer.echo(f"note: {static} not found; serving the API only (use the Vite dev server)")
    typer.echo(f"quant-web on http://{host}:{port}  (database: {url.split('@')[-1]})")
    uvicorn.run(create_app(settings), host=host, port=port, log_level=log_level.lower())
