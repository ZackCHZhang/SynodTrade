# quant-pipeline

**English** | [简体中文](README.zh-CN.md)

Pipeline orchestration: assembles a pipeline from `configs/pipelines/<name>.yaml`, creates a `run_id` that follows the whole run, applies the failure policy, and provides the `quant` command. Depends on every business package.

## Command line

```bash
quant run -p long_term_stocks                  # run in the config's mode (paper / live / dry_run)
quant run -p long_term_stocks --dry-run        # force dry-run: orders are recorded, never sent
quant run -p long_term_stocks --paper          # force paper whatever the config says (never live)
quant run -p long_term_stocks --stages data,sentiment   # run only some stages
quant run -p long_term_stocks --offline        # no gateway, no API keys, no network: fake data + neutral fake LLM, forces dry-run
quant run -p demo_all_modules --offline --offline-llm bullish --as-of 2026-09-30T14:00:00Z   # exercises every module
quant run -p long_term_stocks --as-of 2026-10-01T10:00:00-04:00   # no offset means UTC
quant validate [-p NAME]                       # validate pipelines and everything they reference
quant kill-switch on --reason "..." | off | status
quant benchmark                                # paper-trading benchmark into ./benchmark (see below)
quant --env-file other.env run -p ...          # ./.env is read by default (never overrides variables already set)
```

- Names accepted by `--stages`: `select` / `selection`, `data` (= `data_update`), `sentiment`, `decision`, `risk`, `trading` / `trade`.
- `--dry-run` and `--paper` cannot be combined.
- Database: `--db-url` or `QUANT_DATABASE_URL`. Without either, `--offline` uses the local `./quant_offline.db` and creates its tables; `--init-db` creates tables in any other database (for development — use `quant-db upgrade` in production).
- Config folder: `--configs`, default `./configs`. Log level: `--log-level`, default INFO.
- Output: the run summary (JSON) on stdout, logs (JSON) on stderr. A failed run exits with code 1 so the scheduler can tell.

## One run (`PipelineRunner.run`)

1. Validate the pipeline config and everything it references (account, agents, prompt templates, LLM vendors).
2. Choose the run mode: dry_run with `--dry-run` or `--offline`, paper with `--paper`, otherwise the config's value. Live mode requires `QUANT_ALLOW_LIVE=1`; otherwise the run is refused before anything is written to the database.
3. **Re-entry guard**: if the same pipeline has an unfinished run that started within `max_run_minutes` (default 180), `PipelineBusyError` is raised; older unfinished runs are considered crashed, marked FAILED, and the run continues.
4. Write a `pipeline_runs` row with `run_id`, mode, `as_of`, `config_hash` and a config snapshot (the pipeline and all agent configs).
5. **Only the services the selected stages need are built**:
   - repositories, ConfigStore, LLM vendor pool, pipeline config, account config;
   - the market-data provider (IBKR) only with a `data_update` or `selection` stage; both share that one connection, and selection uses it (`bars_refresher`) to fetch candidates' daily bars;
   - the selection stage replaces the run's universe with its picks plus existing holdings; later stages only handle that universe;
   - the broker (`create_broker(mode)`) only with a `trading` stage, so `--stages data,sentiment` never connects to a broker;
   - API keys of the LLM vendors in use are checked up front; a missing key fails immediately.
6. Stages are created through the registry (entry point `quant.stages`) and run in order. **Every log line carries `run_id` and `pipeline` automatically.**
7. **Failure policy**:
   - When a stage raises: a stage with `on_error: skip` (e.g. sentiment) records the error and the run continues;
   - the default is `abort`: stop immediately, **later stages (including trading) never run**, and the run is FAILED;
   - errors while assembling (config, credentials) also fail the run.
8. Close connections (each stage's `aclose`, market data, broker, LLM clients) and write the final status and summary (each stage's status and duration, record counts, final actions, order states, errors).

**Service overrides**: `PipelineRunner(store, db, overrides={...})` can replace any service, e.g. `broker`, `market_data`, `llm`, `sentiment_sources`, `market_clock`. This is how tests inject fakes.

`--as-of` only makes one run behave as if it were at that moment (reads are bound by `as_of` and records are stamped with it); there is currently **no** backtest that replays many points in time and reports performance.

## Offline mode (`--offline`)

These modules are replaced by fakes; everything else runs exactly as in a normal run (prompt rendering, structured-output validation, risk rules, ordering, database writes), which makes it a good check of configs and deployment:

| Module | Offline replacement |
|---|---|
| Market data | generated daily bars up to `as_of`, about 300 per symbol |
| Selection candidate sources | static lists as configured; IBKR scanners return a fixed set of large caps (`OFFLINE_SCANNER_SYMBOLS`) |
| Sentiment sources | a few synthetic posts and headlines per symbol (marked `synthetic` in metadata); the sentiment agents run too |
| LLM | `schema_reply` returns valid output for the requested schema. Selection agents pick the first three candidates. Default `--offline-llm neutral`: every decision is HOLD, no orders; `--offline-llm bullish`: decisions buy, so the risk agents and order flow run as well |
| Broker | DryRunBroker (orders recorded, never sent, never filled) |

## Paper-trading benchmark (`quant benchmark`)

Publishes how the pipelines actually did on their paper (or live) accounts:

```bash
quant benchmark                                  # every pipeline that ran in paper/live mode
quant benchmark -p long_term_stocks --end 2026-12-31 --out benchmark
```

- Each pipeline's curve starts on the day of its first paper/live run at `budget.max_capital`. Every exchange session, its fills up to that day are booked with the same arithmetic as the trading ledger (`LedgerState.apply_fill`, commissions included) and open positions are valued at that day's daily close. Dry-run and offline runs never count.
- The benchmark is the pipeline's `benchmark` symbol (SPY by default), indexed to the same base day. Reported: return, benchmark return, excess return, max drawdown, Sharpe and volatility (from 20 sessions), CAGR (from 60 sessions), fills, sells at a profit, realised P&L, commissions.
- Writes `README.md` / `README.zh-CN.md`, `equity.svg` (light and dark) and `data.json` (the daily series) to `--out`, and refreshes the summary between `<!-- benchmark:start -->` and `<!-- benchmark:end -->` in `./README.md` and `./README.zh-CN.md` (`--readme` picks other files). Commit the result to publish it.
- Daily bars come from the database: run a `data_update` stage (or a pipeline with one) first so the closes are current.

## Running tests

```bash
python tasks.py test-pipeline
```

The end-to-end test (`test_full_dry_run_end_to_end`) uses the repository's real config (`long_term_stocks`) with fake market data, fake sentiment, a fake LLM (always buy) and the simulated broker for a full dry run, then checks the database item by item: run record, agent instances (2 + 3 + 1), sentiment results, 12 decisions, 4 aggregated decisions, 12 risk records, 4 orders and fills, 18 LLM calls. Every record belongs to the same `run_id`, and the sub-ledger is updated accordingly.
