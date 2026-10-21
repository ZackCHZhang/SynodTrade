# synodtrade-scheduler

**English** | [简体中文](README.zh-CN.md)

Scheduler: decides only *when* to wake *which* pipeline; it contains no business logic. Depends on `synodtrade-pipeline` (and everything below it).

## Command line

```bash
synodtrade-scheduler run                 # run until Ctrl+C or SIGTERM
synodtrade-scheduler plan --days 7       # list runs for the next N days (1–366, default 7) in New York and Berlin time; no credentials needed
synodtrade-scheduler check               # one health check per scheduled pipeline
```

Database: `--db-url` or `SYNODTRADE_DATABASE_URL`. Config folder: `--configs`, default `./configs`. `run` also takes `--log-level`. Like `synodtrade`, it reads `./.env` by default (`synodtrade-scheduler --env-file ... run`).

## Schedule config `configs/schedules.yaml`

```yaml
calendar: XNYS                 # exchange_calendars code
timezone: America/New_York     # all times are in exchange time
jobs:
  - pipeline: long_term_stocks
    trigger: market_relative   # relative to the open or close
    anchor: open               # open | close
    offset_minutes: 30         # positive: after, negative: before
  - pipeline: etf_allocation
    trigger: cron
    cron: "0 11 * * MON"       # 5-field crontab in exchange time
# Optional per job: dry_run, enabled, misfire_grace_minutes (default 15),
#                   skip_non_trading_days (cron only, default true)
```

**Every time follows the exchange calendar** (`exchange_calendars`, XNYS):
- `market_relative` uses each trading day's actual open or close plus the offset, so DST changes, holidays and early closes (e.g. 13:00 on the day after Thanksgiving) are handled automatically.
- `cron` is interpreted in New York time and skips non-trading days by default: if Monday is a holiday, there is no run that week.

Log timestamps are UTC with Berlin time added (`ts_local`); `plan` and the startup log show both New York and Berlin time.

## Why APScheduler 3.x (not 4)

4.x is still a pre-release with a changing API; 3.x is stable and widely used, its `AsyncIOScheduler` runs our async jobs directly, and `SQLAlchemyJobStore` keeps jobs in the same database. The 3.x job store needs a sync driver, so async database URLs are converted automatically (asyncpg → psycopg, aiosqlite → sqlite). The `apscheduler_jobs` table is not managed by our Alembic migrations: autogenerate ignores it and never proposes to drop it.

## Behaviour

- **Jobs are stored in the database and survive restarts**: the scheduler starts paused, then reconciles the stored jobs with the config.
  - Unchanged jobs are kept as they are, so a run missed while the scheduler was down still happens after a restart if it is within `misfire_grace_minutes`.
  - Changed jobs are replaced; jobs removed or disabled in the config are deleted.
- **Two layers against overlapping runs**:
  - in-process: APScheduler `max_instances=1` + `coalesce=True` — at most one run per pipeline at a time, and a backlog of triggers collapses into one;
  - across processes: the pipeline runner checks the database for unfinished runs (older than 3 hours = crashed and closed).

  The two pipelines use different IBKR client ids (see `configs/accounts/ibkr_etf.yaml`), so they can run at the same time.
- **Health check before every run**:
  - the database is reachable;
  - when the pipeline needs IBKR (data update, IBKR news, non-dry-run trading), a TCP connection to IB Gateway can be opened (no login, so the gateway session is not disturbed).

  A failed check **skips the run** and raises an alert.
- **Alerts**: always logged. With `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` set they also go to Telegram (warning and above by default); a failed send is only logged and never stops a run. For other channels such as email, implement the `Notifier` protocol (`async notify(level, title, message)`) and add it to `default_notifier`.
  - Alerts are raised for: failed health checks, invalid config, crashed runs, failed runs (with each stage's errors), and a previous run still busy.

The web console (`synodtrade-web`) can also start and stop a scheduler inside its own process (jobs kept in memory only). Do not run it together with a separate `synodtrade-scheduler run`.

## Deployment (docker-compose)

`docker-compose.yml` at the repository root has three services:
- `postgres`: the TimescaleDB image (`timescale/timescaledb:latest-pg16`), bound to localhost.
- `ib-gateway`: `ghcr.io/gnzsnz/ib-gateway` with IBC auto-login; inside the compose network the paper port is 4004 and the live port 4003.
- `scheduler`: built from the repository's `Dockerfile`; runs `synodtrade-db upgrade`, then `synodtrade-scheduler run`. The configs folder is mounted read-only, so config changes need no rebuild — just restart the scheduler.

```bash
cp .env.example .env    # fill in TWS_USERID / TWS_PASSWORD / IBKR_ACCOUNT / API keys / POSTGRES_PASSWORD
docker compose up -d
docker compose logs -f scheduler
```

## Running tests

```bash
python tasks.py test-scheduler
```
