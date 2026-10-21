# synodtrade-market-data

**English** | [简体中文](README.zh-CN.md)

Market and account data updates: fetches historical bars, live quotes, account funds and positions from IBKR and writes them to the database. Depends on `synodtrade-core` and `synodtrade-database`.

## Public API

- `MarketDataProvider` (protocol): `connect` / `disconnect` / `is_healthy` / `resolve_instrument` / `fetch_bars` / `fetch_quotes` / `fetch_account`
  - `IBKRMarketDataProvider`: built on `ib_async`, connects to the **TWS or IB Gateway socket API** (paper ports 4002/7497) with a **read-only connection** (`readonly=True`); it never places orders.
  - `FakeMarketDataProvider`: in-memory data, optionally loaded from a fixture folder with `from_fixture_dir()`; `generate_daily_bars()` produces reproducible daily bars from a fixed seed. Used by tests and offline runs.
- `DataUpdater`:
  - `update(...)`: incremental update of bars, quotes and account; returns an `UpdateReport` (rows written and per-symbol errors).
  - `update_bars(...)`: bars only, for any symbols; this implements core's `BarsRefresher` protocol, which the selection stage uses to fetch candidates' daily bars.
- `DataUpdateStage`: the `data_update` pipeline stage, registered through the entry point `synodtrade.stages` with the factory `build_data_update_stage(config, services)`. Services:
  - `repos`: `Repositories`
  - `market_data`: `MarketDataProvider`
  - `account`: `AccountConfig` (optional, to record account snapshots)

## Behaviour

- **Incremental updates**: only what the database is missing is fetched.
  - Nothing stored yet: the whole lookback window.
  - The newest stored bar is always fetched again, since it may not have been complete when written.
  - Earlier data is back-filled only when the oldest stored bar is clearly later than the window start. A margin (at least 4 days, or 2 bar lengths) keeps a window start on a weekend from causing a request every day.
  - Gaps in the middle are not detected; that would need the exchange calendar.
  - For a stock listed after the window start, every run sends one extra back-fill request that returns nothing.
- **Pacing**: `PacingLimiter` allows at most 50 historical-data requests per 10 minutes and 5 per contract per 2 seconds, below IBKR's limits (60 / 6), so pacing violations never happen. The maximum span of one request depends on the bar size: 1 day for 1-minute bars, 7 days for 5-minute, 14 for 15-minute, 30 for 1-hour, 365 for daily and weekly. Connection errors and timeouts are retried up to 3 times with exponential backoff.
- **Bar timestamps**: daily and weekly bars have `ts` = 00:00 of that day in the exchange timezone (New York), stored as UTC. By the database rule, **today's daily bar becomes readable only after the day ends**, so intraday decisions only use completed bars.
- **Quotes**: IBKR's "no price" values (NaN, -1, 0) become `None`; crossed quotes (bid above ask) keep only `last`. Paper accounts usually lack real-time subscriptions, so the default is `market_data_type=3` (delayed).
  - When even delayed data is missing (e.g. the paper account has no market-data sharing: TWS returns NaN without an error), the latest 1-minute TRADES bar is used instead: `last` = its close, `ts` = its end, no bid / ask. That price is about 15 minutes old, which is why the `demo_all_modules` pipeline widens `limit_offset_bps` to 25.
- **Account currency**: account snapshots are converted to USD. The base currency is taken from the currency of the `NetLiquidation` row (e.g. a EUR account); only values in that currency are kept and multiplied by the IDEALPRO rate (MIDPOINT close of the latest daily bar of a pair such as `EURUSD`; if the pair does not exist, the inverse pair is used and inverted), rounded to two decimals. The rate used is logged as `ibkr.account_fx`.
- **Instruments**: the `con_id` is looked up from IBKR once and then cached in the `instruments` table.
- **Failures**: one symbol failing does not affect the others; quote and account failures are recorded separately. By default any error fails the stage (`fail_on_error: true`) and the run stops before trading: better not to trade than to decide on stale data.

## Configuration (`data_update` stage in `configs/pipelines/*.yaml`)

```yaml
- type: data_update
  timeframes: [1d]        # 1m 5m 15m 1h 1d 1w; default [1d]
  lookback_days: 365      # 1–3650, default 365
  quotes: true            # record quote snapshots
  account: true           # record account and position snapshots (needs the account service)
  fail_on_error: true
```

Connection settings come from `configs/accounts/*.yaml` (`host` / `port` / `client_id`). IBKR client ids: market data uses the account's `client_id`, trading +1, news (sentiment source) +2, the selection scanner +3.

## Running tests

```bash
python tasks.py test-market_data
```

Tests against a real paper gateway must be enabled explicitly:

```bash
export SYNODTRADE_TEST_IBKR=1     # Windows: set
export IBKR_PORT=4002
python tasks.py integration
```
