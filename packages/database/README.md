# quant-database

**English** | [简体中文](README.zh-CN.md)

Database layer: ORM models, repositories and Alembic migrations. Production uses PostgreSQL 16 (docker-compose uses the TimescaleDB image); unit tests use SQLite. Depends on `quant-core`.

## Public API

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

## Key conventions

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

## Migrations

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

## Running tests

```bash
python tasks.py test-database             # SQLite
```

The same repository tests run on PostgreSQL. Prepare a database that may be wiped:

```bash
export QUANT_TEST_DATABASE_URL=postgresql+asyncpg://quant:pw@localhost:5432/quant_test   # Windows: set
python tasks.py integration
```
