# quant-scheduler

[中文](#中文) | [English](#english)

---

## 中文

调度器：只负责"什么时候唤醒哪条流水线"，不包含业务逻辑。依赖 `quant-pipeline`（以及其下的所有包）。

### 命令行

```bash
quant-scheduler run                 # 启动调度器，直到收到 Ctrl+C 或 SIGTERM
quant-scheduler plan --days 7       # 列出接下来 N 天（1–366，默认 7）的运行时间（纽约时间 + 柏林时间），不需要凭据
quant-scheduler check               # 对每条已排程的流水线做一次健康检查
```

数据库：`--db-url` 或 `QUANT_DATABASE_URL`。配置目录：`--configs`，默认 `./configs`。`run` 还接受 `--log-level`。和 `quant` 一样，默认读取 `./.env`（`quant-scheduler --env-file ... run`）。

### 调度配置 `configs/schedules.yaml`

```yaml
calendar: XNYS                 # exchange_calendars 代码
timezone: America/New_York     # 所有时间都按交易所时区定义
jobs:
  - pipeline: long_term_stocks
    trigger: market_relative   # 相对开盘或收盘
    anchor: open               # open | close
    offset_minutes: 30         # 正数为之后，负数为之前
  - pipeline: etf_allocation
    trigger: cron
    cron: "0 11 * * MON"       # 交易所时区下的 5 字段 crontab
# 每个 job 可选：dry_run、enabled、misfire_grace_minutes（默认 15）、
#               skip_non_trading_days（仅 cron，默认 true）
```

**所有时间都按交易所日历计算**（`exchange_calendars`，XNYS）：
- `market_relative` 取每个交易日实际的开盘或收盘时间再加上偏移，所以夏令时切换、节假日、提前收盘（例如感恩节次日 13:00 收盘）都自动正确。
- `cron` 按纽约时间解释，默认跳过非交易日：如果周一是假日，这一周就不运行。

日志时间戳一律为 UTC，另附柏林时间（`ts_local`）；`plan` 和启动日志同时显示纽约时间和柏林时间。

### 为什么用 APScheduler 3.x（而不是 4）

4.x 仍是预发布版本，API 还在变化；3.x 稳定且广泛使用，`AsyncIOScheduler` 可以直接运行我们的 async 任务，`SQLAlchemyJobStore` 可以把任务存进同一个数据库。3.x 的 job store 需要同步驱动，所以 async 的数据库地址会自动转换（asyncpg → psycopg，aiosqlite → sqlite）。`apscheduler_jobs` 表不由我们的 Alembic 迁移管理：自动生成迁移时会忽略它，不会建议删除。

### 行为

- **任务存进数据库，重启不丢**：启动时先以暂停状态启动，再把数据库里存的任务与配置对齐。
  - 定义没变的任务原样保留，所以调度器停机期间错过的运行，只要还在 `misfire_grace_minutes` 之内，重启后仍会执行。
  - 定义变了的任务会被替换；配置里已删除或禁用的任务会被移除。
- **防止重复运行，有两层**：
  - 同一进程内：APScheduler 的 `max_instances=1` + `coalesce=True`，同一条流水线同时最多跑一个，积压的多次触发合并成一次；
  - 跨进程：流水线 runner 会检查数据库里是否已有未结束的运行（超过 3 小时的视为崩溃并关闭）。

  两条流水线使用不同的 IBKR client id（见 `configs/accounts/ibkr_etf.yaml`），所以可以同时运行。
- **每次运行前的健康检查**：
  - 数据库能否连通；
  - 流水线需要 IBKR 时（行情更新、IBKR 新闻、非 dry-run 的交易），检查能否与 IB Gateway 建立 TCP 连接（不登录，不影响网关会话）。

  检查失败时**跳过本次运行**并发出告警。
- **告警**：默认写日志。设置了 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID` 时同时发 Telegram，默认只发 warning 及以上级别；发送失败只记日志，不会中断运行。邮件等其他渠道：实现 `Notifier` 协议（`async notify(level, title, message)`），再加到 `default_notifier` 中即可。
  - 会告警的情况：健康检查失败、配置无效、运行崩溃、运行失败（附带各阶段错误）、上一次运行仍在进行。

Web 控制台（`quant-web`）也可以在自己的进程里启停一个调度器（任务只保存在内存中）。不要同时运行它和独立的 `quant-scheduler run`。

### 部署（docker-compose）

仓库根目录的 `docker-compose.yml` 包含三个服务：
- `postgres`：TimescaleDB 镜像（`timescale/timescaledb:latest-pg16`），只监听本机端口。
- `ib-gateway`：`ghcr.io/gnzsnz/ib-gateway`，用 IBC 自动登录；在 compose 网络内部，paper 端口是 4004，live 端口是 4003。
- `scheduler`：用仓库的 `Dockerfile` 构建，先执行 `quant-db upgrade`，再运行 `quant-scheduler run`。configs 目录以只读方式挂载，修改配置不需要重建镜像，重启 scheduler 即可生效。

```bash
cp .env.example .env    # 填写 TWS_USERID / TWS_PASSWORD / IBKR_ACCOUNT / API keys / POSTGRES_PASSWORD
docker compose up -d
docker compose logs -f scheduler
```

### 运行测试

```bash
python tasks.py test-scheduler
```

---

## English

Scheduler: decides only *when* to wake *which* pipeline; it contains no business logic. Depends on `quant-pipeline` (and everything below it).

### Command line

```bash
quant-scheduler run                 # run until Ctrl+C or SIGTERM
quant-scheduler plan --days 7       # list runs for the next N days (1–366, default 7) in New York and Berlin time; no credentials needed
quant-scheduler check               # one health check per scheduled pipeline
```

Database: `--db-url` or `QUANT_DATABASE_URL`. Config folder: `--configs`, default `./configs`. `run` also takes `--log-level`. Like `quant`, it reads `./.env` by default (`quant-scheduler --env-file ... run`).

### Schedule config `configs/schedules.yaml`

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

### Why APScheduler 3.x (not 4)

4.x is still a pre-release with a changing API; 3.x is stable and widely used, its `AsyncIOScheduler` runs our async jobs directly, and `SQLAlchemyJobStore` keeps jobs in the same database. The 3.x job store needs a sync driver, so async database URLs are converted automatically (asyncpg → psycopg, aiosqlite → sqlite). The `apscheduler_jobs` table is not managed by our Alembic migrations: autogenerate ignores it and never proposes to drop it.

### Behaviour

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

The web console (`quant-web`) can also start and stop a scheduler inside its own process (jobs kept in memory only). Do not run it together with a separate `quant-scheduler run`.

### Deployment (docker-compose)

`docker-compose.yml` at the repository root has three services:
- `postgres`: the TimescaleDB image (`timescale/timescaledb:latest-pg16`), bound to localhost.
- `ib-gateway`: `ghcr.io/gnzsnz/ib-gateway` with IBC auto-login; inside the compose network the paper port is 4004 and the live port 4003.
- `scheduler`: built from the repository's `Dockerfile`; runs `quant-db upgrade`, then `quant-scheduler run`. The configs folder is mounted read-only, so config changes need no rebuild — just restart the scheduler.

```bash
cp .env.example .env    # fill in TWS_USERID / TWS_PASSWORD / IBKR_ACCOUNT / API keys / POSTGRES_PASSWORD
docker compose up -d
docker compose logs -f scheduler
```

### Running tests

```bash
python tasks.py test-scheduler
```
