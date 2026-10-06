# quant-database

[中文](#中文) | [English](#english)

---

## 中文

数据库管理：ORM 模型、Repository、Alembic 迁移。生产用 PostgreSQL 16（docker-compose 使用 TimescaleDB 镜像），单元测试用 SQLite。依赖 `quant-core`。

### 公开接口

业务包**只通过 Repository 读写数据库**，传入和返回的都是 `quant_core` 的模型，不接触 ORM 或 SQL。

```python
from quant_database import Database, Repositories

db = Database.from_env()  # QUANT_DATABASE_URL
repos = Repositories.create(db)
bars = await repos.bars.get_latest_bars("AAPL", 60, as_of=ctx.as_of)
```

| Repository | 主要方法 |
|---|---|
| `instruments` | `upsert`、`get`、`list` |
| `bars` | `upsert`（按 instrument+timeframe+ts 覆盖写）、`get_latest_bars(symbol, n, timeframe, as_of)`、`get_bars(start, end)`、`get_bar_span`（用于增量更新） |
| `quotes` | `add`、`get_latest_quote(symbol, as_of)` |
| `accounts` | `add_snapshot(account, positions)`（原子写入）、`get_latest_account`、`get_latest_positions` |
| `runs` | `start_run`、`finish_run`、`get_run`、`running_runs`（防重入）、`register_agent_instances`、`get_agent_instances` |
| `llm_calls` | `record`（即 `LLMCallRecorder` 的持久化实现）、`get_by_run`、`get_many` |
| `selection` | `add_results`（每个选股 agent 的输出）、`add_selection`（最终选股结果）、`get_results_by_run`、`get_by_run`、`get_latest` |
| `sentiment` | `add_items`（去重，返回新插入的条数）、`get_items(order_by=recent/score, limit)`、`add_results`、`get_sentiment(symbol, since, as_of)`、`get_results_by_run` |
| `decisions` | `add_decisions`、`add_aggregated`、`get_decisions_by_run`、`get_aggregated_by_run`、`get_recent_aggregated` |
| `risk` | `add_assessments`、`get_by_run` |
| `orders` | `create(intent)`（幂等，返回 `(record, created)`）、`get`、`apply_result`、`get_fills`、`list_by_run`、`list_open`、`count_since` |
| `ledger` | `get_state(pipeline, max_capital, as_of)`：返回流水线的虚拟子账本 |
| `flags` | `is_enabled`、`set(key, enabled, reason)`、`get_reason`、`kill_switch_active` |

### 关键约定

- **不看未来数据**：所有读取方法都支持 `as_of`，默认是当前时间。
  - K 线的 `ts` 是开始时间，只有在 `ts + 周期 <= as_of` 时才可见。所以盘中运行看不到当天尚未收盘的日线；指定过去的 `as_of` 运行时也不会用到之后的数据。
  - 舆情、决策、行情快照、成交都按各自的时间戳过滤。
- **记录时间就是运行的 `as_of`**：选股结果、舆情结果、决策、聚合决策、风控结论、订单的 `created_at` 由各阶段设为本次运行的 `as_of`，而不是写入时的系统时间。实盘运行时两者几乎相同；用过去的 `as_of` 运行时，之后"截至某一时刻"读取到的，正好是那一时刻已经存在的记录。
- **幂等下单**：`orders.client_order_id` 有唯一约束。`create()` 返回 `created=False` 时，说明这笔订单已经记录过（比如同一 `run_id` 重跑），**不能再发给券商**。已经处于终态的订单不能改成别的状态。成交按 `exec_id` 去重。
- **虚拟子账本**：由这条流水线自己的成交推算，不用 IBKR 的账户总持仓。
  - 初始现金为 `max_capital`，买卖和佣金都计入。
  - 平均成本法计算已实现盈亏。
  - 未成交的买单会预留现金，新的买入只能用 `available_cash`。
  - 各流水线的账本互不影响。同一个 IBKR 账户里手动下的单不会进入任何子账本。
- **金额精确**：`DecimalType` 在 PostgreSQL 上是 `NUMERIC(28,10)`；在 SQLite 上存为字符串，因为 SQLite 会悄悄把小数转成 float。代价是**不能在 SQL 里对金额列做加减、求和或排序**，要读出来用 Python 的 Decimal 计算（子账本就是这样做的）。
- **时间**：`UtcDateTime` 拒绝不带时区的 datetime，存 UTC，读出来一定带 UTC 时区。
- **LLM 原始输入输出**：保存在 `llm_calls` 表，包括每次重试和失败。选股、舆情、决策、风控记录通过 `llm_call_ids` 关联过去。
- **一条帖子提到多个标的**时，每个标的存一行，唯一键是 `(source, external_id, symbol)`。
- **Kill Switch**：`system_flags` 表里的 `kill_switch` 标记（常量 `KILL_SWITCH`）。风控阶段和交易阶段都会读取它，开启后不再下单。可以用 `quant kill-switch on|off|status` 或 Web 控制台切换。
- 方言相关的 SQL 只有一处：`repositories/base.py` 里的 `upsert_insert`（ON CONFLICT），支持 SQLite 和 PostgreSQL。

### 迁移

迁移脚本随包一起发布，在 `src/quant_database/migrations/` 目录下（`0001_initial_schema`、`0002_stock_selection`）。

```bash
docker compose up -d postgres
quant-db upgrade                          # 使用 $QUANT_DATABASE_URL，默认升级到 head
quant-db upgrade --url postgresql+asyncpg://...
quant-db downgrade                        # 默认回退一个版本（--revision 可指定）
quant-db revision -m "add x"              # 修改 models.py 后，自动生成新的迁移
quant-db current
# 如果 quant-db 命令不存在，可以用：python -m quant_database.cli upgrade
```

有测试保证迁移建出来的表结构和 ORM 模型**完全一致**，并且能完整降级再升级。

### 运行测试

```bash
python tasks.py test-database             # SQLite
```

同一套 Repository 测试也能在 PostgreSQL 上跑。准备一个可以随意清空的库：

```bash
set QUANT_TEST_DATABASE_URL=postgresql+asyncpg://quant:pw@localhost:5432/quant_test   # Linux/macOS: export
python tasks.py integration
```

---

## English

Database layer: ORM models, repositories and Alembic migrations. Production uses PostgreSQL 16 (docker-compose uses the TimescaleDB image); unit tests use SQLite. Depends on `quant-core`.

### Public API

Business packages **read and write the database only through repositories**, which take and return `quant_core` models; they never touch the ORM or SQL.

```python
from quant_database import Database, Repositories

db = Database.from_env()  # QUANT_DATABASE_URL
repos = Repositories.create(db)
bars = await repos.bars.get_latest_bars("AAPL", 60, as_of=ctx.as_of)
```

| Repository | Main methods |
|---|---|
| `instruments` | `upsert`, `get`, `list` |
| `bars` | `upsert` (overwrites by instrument + timeframe + ts), `get_latest_bars(symbol, n, timeframe, as_of)`, `get_bars(start, end)`, `get_bar_span` (for incremental updates) |
| `quotes` | `add`, `get_latest_quote(symbol, as_of)` |
| `accounts` | `add_snapshot(account, positions)` (atomic), `get_latest_account`, `get_latest_positions` |
| `runs` | `start_run`, `finish_run`, `get_run`, `running_runs` (re-entry guard), `register_agent_instances`, `get_agent_instances` |
| `llm_calls` | `record` (the persistent `LLMCallRecorder`), `get_by_run`, `get_many` |
| `selection` | `add_results` (each selection agent's output), `add_selection` (the final selection), `get_results_by_run`, `get_by_run`, `get_latest` |
| `sentiment` | `add_items` (deduplicated, returns the number of new rows), `get_items(order_by=recent/score, limit)`, `add_results`, `get_sentiment(symbol, since, as_of)`, `get_results_by_run` |
| `decisions` | `add_decisions`, `add_aggregated`, `get_decisions_by_run`, `get_aggregated_by_run`, `get_recent_aggregated` |
| `risk` | `add_assessments`, `get_by_run` |
| `orders` | `create(intent)` (idempotent, returns `(record, created)`), `get`, `apply_result`, `get_fills`, `list_by_run`, `list_open`, `count_since` |
| `ledger` | `get_state(pipeline, max_capital, as_of)`: the pipeline's virtual sub-ledger |
| `flags` | `is_enabled`, `set(key, enabled, reason)`, `get_reason`, `kill_switch_active` |

### Key conventions

- **No look-ahead**: every read supports `as_of` (default: now).
  - A bar's `ts` is its start; it becomes visible only when `ts + bar length <= as_of`. An intraday run therefore never sees today's unfinished daily bar, and a run with a past `as_of` never uses later data.
  - Sentiment, decisions, quotes and fills are filtered by their own timestamps.
- **Records are stamped with the run's `as_of`**: stages set `created_at` of selections, sentiment results, decisions, aggregated decisions, risk verdicts and orders to the run's `as_of`, not to the wall clock at write time. In live runs the two are nearly equal; for runs with a past `as_of`, later "as of" reads see exactly the records that existed at that moment.
- **Idempotent orders**: `orders.client_order_id` is unique. When `create()` returns `created=False` the order was already recorded (e.g. the same `run_id` re-ran) and **must not be sent to the broker again**. An order in a terminal state cannot move to another state. Fills are deduplicated by `exec_id`.
- **Virtual sub-ledger**: derived from the pipeline's own fills, not from the IBKR account's total positions.
  - Starting cash is `max_capital`; buys, sells and commissions are applied.
  - Realised P&L uses average cost.
  - Open buy orders reserve cash; new buys may only use `available_cash`.
  - Pipelines' ledgers are independent. Orders placed by hand in the same IBKR account do not enter any sub-ledger.
- **Exact money**: `DecimalType` is `NUMERIC(28,10)` on PostgreSQL and a string on SQLite (SQLite would silently turn decimals into floats). The price: **no arithmetic, sums or sorting on money columns in SQL** — read them and compute with Python `Decimal` (as the sub-ledger does).
- **Time**: `UtcDateTime` rejects naive datetimes, stores UTC and always returns UTC-aware values.
- **Raw LLM input / output** is kept in `llm_calls`, including every retry and failure. Selection, sentiment, decision and risk records link to it via `llm_call_ids`.
- **A post that mentions several symbols** is stored once per symbol; the unique key is `(source, external_id, symbol)`.
- **Kill switch**: the `kill_switch` flag in `system_flags` (constant `KILL_SWITCH`). Both the risk and trading stages read it; while it is on, no orders are sent. Toggle it with `quant kill-switch on|off|status` or from the web console.
- There is exactly one piece of dialect-specific SQL: `upsert_insert` (ON CONFLICT) in `repositories/base.py`, for SQLite and PostgreSQL.

### Migrations

Migrations ship with the package under `src/quant_database/migrations/` (`0001_initial_schema`, `0002_stock_selection`).

```bash
docker compose up -d postgres
quant-db upgrade                          # uses $QUANT_DATABASE_URL, upgrades to head by default
quant-db upgrade --url postgresql+asyncpg://...
quant-db downgrade                        # one revision back by default (--revision to choose)
quant-db revision -m "add x"              # autogenerate a migration after changing models.py
quant-db current
# if the quant-db command is missing: python -m quant_database.cli upgrade
```

Tests guarantee that the schema built by the migrations **matches the ORM models exactly** and that a full downgrade and upgrade works.

### Running tests

```bash
python tasks.py test-database             # SQLite
```

The same repository tests run on PostgreSQL. Prepare a database that may be wiped:

```bash
export QUANT_TEST_DATABASE_URL=postgresql+asyncpg://quant:pw@localhost:5432/quant_test   # Windows: set
python tasks.py integration
```
