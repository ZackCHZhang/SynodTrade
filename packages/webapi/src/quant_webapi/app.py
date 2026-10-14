"""FastAPI application: JSON API under /api, the built web UI (web/dist) everywhere else."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from quant_core.config import ConfigError
from quant_core.logging import configure_logging, get_logger
from quant_core.timeutil import utcnow
from quant_database import KILL_SWITCH, Database
from quant_webapi.account_sync import AccountSyncController
from quant_webapi.catalog import catalog
from quant_webapi.configs import (
    ConfigFiles,
    ConflictError,
    InvalidConfigError,
    NotFoundError,
)
from quant_webapi.data import DataService, jsonable
from quant_webapi.events import EventHub
from quant_webapi.jobs import JobManager, RunRequest
from quant_webapi.scheduling import SchedulerController

log = get_logger(__name__)

# Environment variables whose presence (never value) the UI may show.
WATCHED_ENV = (
    "QUANT_DATABASE_URL",
    "QUANT_ALLOW_LIVE",
    "IBKR_ACCOUNT",
    "IBKR_HOST",
    "IBKR_PORT",
    "IBKR_CLIENT_ID",
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "SEC_EDGAR_USER_AGENT",
    "TELEGRAM_BOT_TOKEN",
)


@dataclass(slots=True)
class WebSettings:
    configs: Path
    db_url: str
    # Offline runs (fake market data, sentiment and LLM) write here, never into `db_url`:
    # their synthetic bars would overwrite real ones. None or equal to db_url: same database.
    offline_db_url: str | None = None
    static_dir: Path | None = None
    env: Mapping[str, str] | None = None  # None: os.environ (after .env was loaded)
    create_tables: bool = False
    log_level: str = "INFO"
    configure_logs: bool = True
    overrides: Mapping[str, Any] = field(default_factory=dict)  # pipeline service overrides
    # Synchronise the IBKR accounts periodically in this process (configs/account_sync.yaml).
    account_sync_loop: bool = False


class WebState:
    def __init__(self, settings: WebSettings) -> None:
        self.settings = settings
        self.db = Database(settings.db_url)
        offline_url = settings.offline_db_url
        self.offline_db = (
            Database(offline_url) if offline_url and offline_url != settings.db_url else None
        )
        self.hub = EventHub()
        self.configs = ConfigFiles(settings.configs, env=settings.env)
        self.data = DataService(self.db, settings.configs, env=settings.env)
        self.offline_data = (
            DataService(self.offline_db, settings.configs, env=settings.env)
            if self.offline_db is not None
            else None
        )
        self.account_sync = AccountSyncController(
            settings.configs,
            self.db,
            env=settings.env,
            service=settings.overrides.get("account_sync"),
        )
        self.jobs = JobManager(
            settings.configs,
            self.db,
            self.hub,
            env=settings.env,
            # runs share the loop's service: one account is never synchronised twice at once
            overrides={"account_sync": self.account_sync.service, **settings.overrides},
            offline_db=self.offline_db,
        )
        self.scheduler = SchedulerController(settings.configs, self.db, env=settings.env)

    @property
    def env(self) -> Mapping[str, str]:
        return os.environ if self.settings.env is None else self.settings.env

    def data_for(self, db: str) -> DataService:
        """`main`, or `offline`: the sandbox of offline runs (main if not separate)."""
        if db not in ("main", "offline"):
            raise ValueError("db must be main or offline")
        return self.offline_data if db == "offline" and self.offline_data else self.data

    async def find_run(self, run_id: UUID) -> tuple[str, dict[str, Any]]:
        try:
            return "main", await self.data.run_detail(run_id)
        except LookupError:
            if self.offline_data is None:
                raise
            return "offline", await self.offline_data.run_detail(run_id)


def state(request: Request) -> WebState:
    web: WebState = request.app.state.web
    return web


# ---------------------------------------------------------------- request bodies


class SaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    etag: str | None = None
    force: bool = False


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    text: str
    force: bool = False


class TextBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


class WatchlistBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9.\- ]+$")
    pinned: bool = False
    note: str | None = Field(default=None, max_length=500)


class KillSwitchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    reason: str | None = None


# ---------------------------------------------------------------- routes

api = APIRouter(prefix="/api")


@api.get("/meta")
def get_meta(request: Request) -> dict[str, Any]:
    web = state(request)
    env = web.env
    providers = web.configs.load_data("llm_providers", "llm_providers") or {}
    key_envs = sorted(
        {
            str(p["api_key_env"])
            for p in (providers.get("providers") or {}).values()
            if isinstance(p, dict) and p.get("api_key_env")
        }
    )
    return {
        **catalog(),
        "env": {name: bool(env.get(name)) for name in (*WATCHED_ENV, *key_envs)},
        "configs_root": str(web.settings.configs.resolve()),
        "database": {"dialect": web.db.dialect},
        "offline_db": web.offline_db is not None,
    }


# ---- configs


@api.get("/configs")
def list_configs(request: Request) -> dict[str, Any]:
    return state(request).configs.list_all()


@api.get("/configs/{kind}/{name}")
def read_config(request: Request, kind: str, name: str) -> dict[str, Any]:
    return state(request).configs.read(kind, name)


@api.post("/configs/{kind}/{name}/validate")
def validate_config(request: Request, kind: str, name: str, body: TextBody) -> dict[str, Any]:
    return state(request).configs.validate(kind, name, body.text).as_dict()


@api.put("/configs/{kind}/{name}")
def save_config(request: Request, kind: str, name: str, body: SaveBody) -> dict[str, Any]:
    return state(request).configs.write(
        kind, name, body.text, expected_etag=body.etag, force=body.force
    )


@api.post("/configs/{kind}")
def create_config(request: Request, kind: str, body: CreateBody) -> dict[str, Any]:
    return state(request).configs.create(kind, body.name, body.text, force=body.force)


@api.delete("/configs/{kind}/{name}")
def delete_config(request: Request, kind: str, name: str) -> dict[str, Any]:
    state(request).configs.delete(kind, name)
    return {"deleted": f"{kind}/{name}"}


# ---- runs started from the UI


@api.post("/jobs")
async def start_job(request: Request, body: RunRequest) -> dict[str, Any]:
    job = await state(request).jobs.start(body)
    return job.as_dict()


@api.get("/jobs")
def list_jobs(request: Request) -> list[dict[str, Any]]:
    return [j.as_dict() for j in state(request).jobs.all()]


@api.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str) -> dict[str, Any]:
    return state(request).jobs.get(job_id).as_dict()


@api.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
    return state(request).jobs.cancel(job_id).as_dict()


# ---- runs (database) and live events


@api.get("/runs")
async def list_runs(
    request: Request,
    pipeline: str | None = None,
    status: str | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    db: str = "main",
) -> dict[str, Any]:
    web = state(request)
    result = await web.data_for(db).runs(
        pipeline=pipeline, status=status, offset=offset, limit=limit
    )
    for run in result["runs"]:
        run["live"] = web.hub.is_live(run["run_id"])
    return result


@api.get("/runs/{run_id}")
async def get_run(request: Request, run_id: UUID) -> dict[str, Any]:
    web = state(request)
    database, detail = await web.find_run(run_id)
    detail["database"] = database
    key = str(run_id)
    detail["live"] = web.hub.is_live(key)
    detail["has_events"] = web.hub.has_run(key)
    detail["progress"] = web.hub.stage_progress(key)
    return detail


@api.get("/runs/{run_id}/events")
async def run_events(request: Request, run_id: UUID, after: int = 0) -> StreamingResponse:
    """Server-Sent Events: past and live log events of a run in this process."""
    web = state(request)
    key = str(run_id)

    async def stream() -> AsyncIterator[str]:
        if not web.hub.has_run(key):
            yield "event: end\ndata: {}\n\n"
            return
        async for event in web.hub.stream(key, after):
            if await request.is_disconnected():
                return
            if event is None:
                yield ": keep-alive\n\n"
                continue
            yield f"id: {event['seq']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.get("/llm_calls/{call_id}")
async def get_llm_call(request: Request, call_id: UUID) -> dict[str, Any]:
    web = state(request)
    try:
        return await web.data.llm_call(call_id)
    except LookupError:
        if web.offline_data is None:
            raise
        return await web.offline_data.llm_call(call_id)


# ---- generic database browser


@api.get("/db/tables")
async def db_tables(request: Request, db: str = "main") -> list[dict[str, Any]]:
    return await state(request).data_for(db).table_counts()


@api.get("/db/tables/{table}")
async def db_rows(
    request: Request,
    table: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    sort: str | None = None,
    desc: bool = True,
    filters: str | None = None,
    db: str = "main",
) -> dict[str, Any]:
    parsed = json.loads(filters) if filters else []
    if not isinstance(parsed, list):
        raise ValueError("filters must be a JSON list")
    return (
        await state(request)
        .data_for(db)
        .rows(table, offset=offset, limit=limit, sort=sort, desc=desc, filters=parsed)
    )


@api.get("/db/tables/{table}/rows/{pk}")
async def db_row(request: Request, table: str, pk: str, db: str = "main") -> dict[str, Any]:
    return await state(request).data_for(db).row(table, pk)


# ---- market data and portfolio


@api.get("/market/instruments")
async def market_instruments(request: Request) -> list[dict[str, Any]]:
    return await state(request).data.instruments()


@api.get("/market/bars")
async def market_bars(
    request: Request,
    symbol: str,
    timeframe: str = "1d",
    limit: Annotated[int, Query(ge=1, le=5000)] = 400,
) -> dict[str, Any]:
    return await state(request).data.bars(symbol, timeframe, limit)


@api.get("/portfolio")
async def portfolio(request: Request) -> dict[str, Any]:
    return await state(request).data.portfolio()


@api.get("/watchlists")
async def watchlists(request: Request) -> list[dict[str, Any]]:
    return await state(request).data.watchlists()


@api.post("/watchlists/{pipeline}")
async def watchlist_add(request: Request, pipeline: str, body: WatchlistBody) -> dict[str, Any]:
    web = state(request)
    if pipeline not in web.configs.names(web.configs.kind("pipelines")):
        raise HTTPException(404, f"unknown pipeline {pipeline!r}")
    entry = await web.data.repos.watchlist.add(
        pipeline, body.symbol, utcnow(), pinned=body.pinned, note=body.note
    )
    return {**jsonable(entry), "active": entry.active}


@api.delete("/watchlists/{pipeline}/{symbol}")
async def watchlist_remove(request: Request, pipeline: str, symbol: str) -> dict[str, Any]:
    removed = await state(request).data.repos.watchlist.remove(pipeline, symbol, utcnow())
    if not removed:
        raise HTTPException(404, f"{symbol} is not on the watchlist of {pipeline}")
    return {"removed": symbol.upper()}


@api.get("/overview")
async def overview(request: Request) -> dict[str, Any]:
    web = state(request)
    result = await web.data.overview()
    result["scheduler"] = web.scheduler.status()
    try:
        latest = [
            s.model_dump(mode="json", exclude={"report"})
            for s in await web.account_sync.service.repos.account_syncs.latest()
        ]
    except SQLAlchemyError as exc:  # e.g. a database not migrated yet: keep the overview up
        log.warning("web.account_sync_unavailable", error=str(exc).splitlines()[0])
        latest = []
    result["account_sync"] = {**web.account_sync.loop_status(), "latest": latest}
    result["jobs"] = [j.as_dict() for j in web.jobs.active()]
    return result


# ---- system


@api.get("/system/kill-switch")
async def get_kill_switch(request: Request) -> dict[str, Any]:
    flags = state(request).data.repos.flags
    return {
        "active": await flags.kill_switch_active(),
        "reason": await flags.get_reason(KILL_SWITCH),
    }


@api.put("/system/kill-switch")
async def set_kill_switch(request: Request, body: KillSwitchBody) -> dict[str, Any]:
    flags = state(request).data.repos.flags
    await flags.set(KILL_SWITCH, body.active, body.reason)
    return {
        "active": await flags.kill_switch_active(),
        "reason": await flags.get_reason(KILL_SWITCH),
    }


# ---- account synchronisation


@api.get("/account-sync")
async def account_sync_status(
    request: Request, history: Annotated[int, Query(ge=0, le=500)] = 30
) -> dict[str, Any]:
    return await state(request).account_sync.status(history)


@api.post("/account-sync/run")
async def account_sync_run(request: Request) -> list[dict[str, Any]]:
    return await state(request).account_sync.run_now()


# ---- scheduler


@api.get("/scheduler/plan")
def scheduler_plan(
    request: Request, days: Annotated[int, Query(ge=1, le=366)] = 7
) -> dict[str, Any]:
    return state(request).scheduler.plan(days)


@api.get("/scheduler/status")
def scheduler_status(request: Request) -> dict[str, Any]:
    return state(request).scheduler.status()


@api.post("/scheduler/{action}")
async def scheduler_action(request: Request, action: str) -> Any:
    controller = state(request).scheduler
    if action == "start":
        return controller.start()
    if action == "stop":
        return controller.stop()
    if action == "reload":
        return controller.reload()
    if action == "check":
        return await controller.check()
    raise NotFoundError(f"unknown scheduler action {action!r}")


# ---------------------------------------------------------------- application


def _error(status: int, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"detail": message, **extra}, status_code=status)


def create_app(settings: WebSettings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        web = WebState(settings)
        app.state.web = web
        if settings.configure_logs:
            verbose = settings.log_level.upper() == "DEBUG"
            configure_logging("DEBUG" if verbose else "INFO")
        web.hub.bind_loop(asyncio.get_running_loop())
        web.hub.install(settings.log_level)
        if settings.create_tables:
            await web.db.create_all()
        if web.offline_db is not None:
            await web.offline_db.create_all()  # a local sandbox file
        if settings.account_sync_loop:
            web.account_sync.start()
        try:
            yield
        finally:
            await web.account_sync.stop()
            web.scheduler.stop()
            await web.jobs.shutdown()
            web.hub.uninstall()
            await web.db.dispose()
            if web.offline_db is not None:
                await web.offline_db.dispose()

    app = FastAPI(title="quant-system web", lifespan=lifespan)
    app.include_router(api)

    @app.exception_handler(NotFoundError)
    @app.exception_handler(LookupError)
    async def not_found(_: Request, exc: Exception) -> JSONResponse:
        return _error(404, str(exc).strip("'\""))

    @app.exception_handler(ConflictError)
    async def conflict(_: Request, exc: Exception) -> JSONResponse:
        return _error(409, str(exc))

    @app.exception_handler(InvalidConfigError)
    async def invalid(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, InvalidConfigError)
        return _error(422, "Config validation failed", diagnostics=exc.diagnostics.as_dict())

    @app.exception_handler(ConfigError)
    @app.exception_handler(ValueError)
    async def bad_request(_: Request, exc: Exception) -> JSONResponse:
        return _error(400, str(exc))

    static = settings.static_dir
    if static is not None and (static / "index.html").is_file():
        root = static.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404)
            candidate = (root / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(root):
                return FileResponse(candidate)
            return FileResponse(root / "index.html")

    return app
