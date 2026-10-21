# synodtrade-webapi

**English** | [简体中文](README.zh-CN.md)

Backend of the web console (FastAPI). The frontend lives in `web/` at the repository root (React + MUI + Vite) and is served by this service once built.
It sits at the top of the dependency graph (`scheduler ← webapi`) and may use every package.

## Start

```bash
python tasks.py web                       # first time: install frontend dependencies and build web/dist
poetry run synodtrade-web serve                # http://127.0.0.1:8765
poetry run synodtrade-web serve --db-url sqlite+aiosqlite:///./paper_test.db --port 8000
```

- Options: `--host` (default `127.0.0.1`), `--port` (default 8765), `--configs` (default `./configs`), `--db-url`, `--static` (the built frontend, default `web/dist`), `--init-db` (create tables), `--log-level`. `.env` is loaded (`synodtrade-web --env-file ... serve`).
- Database: `--db-url` or `SYNODTRADE_DATABASE_URL`; without either, the local `./synodtrade_offline.db` (tables created automatically).
- Listens on `127.0.0.1` only by default. The console has no login yet can start runs that place orders on a paper (and, if allowed, live) account — **do not expose it**.

## Features

| Area | Description |
| --- | --- |
| Config editing | Read and write pipelines, agents, prompt templates, accounts, risk rules, LLM providers and schedules under `configs/`. Validation uses exactly the runtime Pydantic models (including every stage's options and the candidate-source and sentiment-source options) and checks references (accounts, agent roles, LLM providers, risk rules, prompt templates exist); it also lists which pipelines reference an agent / account / risk-rule set. |
| Safe writes | Validate before saving (syntax errors are always refused, semantic errors can be forced); etags detect concurrent edits (409); backups go to `configs/.web_backups/` before overwrite or delete; the file's line endings (CRLF / LF) are kept. |
| Runs | Start pipelines inside the server process (dry_run / paper / as configured; optionally offline, a subset of stages, as_of). Offline runs write to a separate sandbox database `./synodtrade_offline.db`, so fake market data never overwrites real data. Runs can be cancelled: connections are closed and the run is marked failed. |
| Live progress | A structlog processor pushes log events carrying a `run_id` (including `pipeline.stage_start` / `stage_done`) to the browser (SSE). Runs started from the CLI or a separate scheduler show only their database results. |
| Scheduler | Preview the next N days of runs (New York / Berlin time); start / stop a scheduler inside the server process (jobs kept in memory); health checks (database, IB Gateway). Do not also run a separate `synodtrade-scheduler run`. |
| Data | Read-only browsing of every table (paging, sorting, filters, full row view); each run's selection, sentiment, decisions, risk, orders, agent instances and full LLM requests / responses; bar charts; each pipeline's virtual sub-ledger and the IBKR account snapshots; the global kill switch. |

## API overview

```
GET  /api/meta                         JSON Schemas for the forms, registries, which env vars are set (no values)
GET  /api/configs                      every config file
GET  /api/configs/{kind}/{name}        content + etag + who references it
POST /api/configs/{kind}/{name}/validate
PUT  /api/configs/{kind}/{name}        {text, etag, force}
POST /api/configs/{kind}               {name, text}       DELETE /api/configs/{kind}/{name}
POST /api/jobs                         start a run; GET /api/jobs; GET /api/jobs/{id}; POST /api/jobs/{id}/cancel
GET  /api/runs?db=main|offline         GET /api/runs/{id}; GET /api/runs/{id}/events (SSE)
GET  /api/llm_calls/{id}
GET  /api/db/tables?db=…               GET /api/db/tables/{table}?offset&limit&sort&desc&filters
GET  /api/db/tables/{table}/rows/{pk}  one full row
GET  /api/market/instruments           GET /api/market/bars?symbol&timeframe&limit
GET  /api/portfolio                    GET /api/overview
GET|PUT /api/system/kill-switch
GET  /api/scheduler/plan?days=7        GET /api/scheduler/status; POST /api/scheduler/{start|stop|reload|check}
```

`kind` is one of `pipelines`, `agents`, `prompts`, `accounts`, `risk`, `llm_providers`, `schedules`
(the last two are single files; `name` equals `kind`).

Any other path returns the frontend (single-page app).
