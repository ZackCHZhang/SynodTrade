# synodtrade-trading

**English** | [简体中文](README.zh-CN.md)

Order execution: turns the actions approved by risk into orders, submits them idempotently, tracks them until filled, cancelled or rejected, and writes fills to the database (which updates the sub-ledger). Depends on `synodtrade-core` and `synodtrade-database`.

## Flow (`trading` stage)

1. **Safety checks**:
   - `ensure_mode_allowed`: `mode: live` requires `SYNODTRADE_ALLOW_LIVE=1`.
   - The broker's `mode` must match the run's `mode`; a dry-run pipeline cannot use a real broker.
   - Connect to the broker.
2. **Reconcile**: open orders left by this pipeline's earlier runs are looked up at the broker and updated first.
3. **Kill switch**: the database flag is checked again right before ordering; while it is on, no new orders are sent.
4. **Plan orders** (`OrderPlanner`):
   - Only symbols whose final risk verdict (`ctx.risk_verdicts`) is not HOLD.
   - Same order as the risk stage: sells first, then buys by signal strength.
   - Price: a quote from the last `max_quote_age_minutes`, otherwise the last completed bar's close.
   - Limit price (the default order type, a "marketable limit"):
     - buy = ask × (1 + `limit_offset_bps` / 10000), rounded up to the tick; the reference price if there is no ask;
     - sell = bid × (1 − offset), rounded down to the tick;
     - tick: $0.01 at or above $1, otherwise $0.0001.
   - `order_type: market` sets no limit.
   - Quantity: core's five-tier sizing on the sub-ledger (available cash, position), floored to the lot size; zero-quantity orders are skipped. **Buys are sized at the limit price**, so they never exceed the shares risk evaluated. Earlier buys reduce the cash available to later ones. With an `account` service, spendable cash never exceeds the real account's available funds.
   - `client_order_id = hash(run_id, symbol, action)` is the idempotency key.
5. **Submit** (idempotent): the order is written to the database first, then sent.
   - Already recorded and sent (e.g. the same `run_id` re-ran) → not sent again.
   - Recorded but still PENDING_SUBMIT (crash after the write) → looked up at the broker first and **sent only if the broker really does not have it**.
   - Error while sending → stays PENDING_SUBMIT with the error recorded; the next run looks it up before deciding; this stage fails at the end.
6. **Track** (`wait_for_fills: true`, default): polls every `poll_interval_seconds` until every order is filled, cancelled or rejected; orders still open after `cancel_after_minutes` are cancelled (partial fills are kept). Fills are deduplicated by `exec_id` into `fills`, and the sub-ledger's cash and positions follow.
   - With `wait_for_fills: false` orders are only submitted; the next run reconciles them.
   - Note: with `wait_for_fills: true` unfilled orders are cancelled at the deadline whether `time_in_force` is DAY or GTC; a GTC order stays open across runs only with `wait_for_fills: false`.

## Brokers

| Implementation | Purpose | mode |
|---|---|---|
| `DryRunBroker` | records only (status `DRY_RUN`); never sends, never fills | dry_run |
| `SimulatedBroker` | in-memory fills: fill fully at once, fill half, never fill, reject. For tests and offline simulation | dry_run |
| `IBKRBroker` | real orders to TWS / IB Gateway through `ib_async` (paper accounts use it too) | paper / live |

`create_broker(mode, account)` picks by run mode: dry_run → `DryRunBroker`, paper / live → `IBKRBroker` (needs an account config).

**`IBKRBroker` safeguards**:
- Live mode checks `SYNODTRADE_ALLOW_LIVE=1` both when created and when connecting.
- After connecting it checks the accounts logged in on the gateway:
  - paper mode refuses if any non-paper account is present (paper account ids start with `D`);
  - live mode refuses paper accounts;
  - the configured account must be among the gateway's managed accounts.
- Every order carries the account id and the `client_order_id` in `orderRef`. After a restart, orders are found again through the current session, `reqAllOpenOrders` and executions, so nothing is placed twice.
- Fills are written once their commission report arrives; when an order completes, any remaining fills are written (commission 0).
- Client id: the trading connection uses the account config's `client_id + 1` (market data the plain id, news +2, the selection scanner +3).

## Configuration

```yaml
- type: trading
  order_type: limit          # limit | market, default limit
  limit_offset_bps: 5        # 0–500, default 5
  time_in_force: DAY         # DAY | GTC, default DAY
  cancel_after_minutes: 30   # default 30
  poll_interval_seconds: 5   # default 5
  wait_for_fills: true       # default true
  max_quote_age_minutes: 30  # default 30
  timeframe: 1d              # bars used for the close when there is no quote, default 1d
```

Services needed by the stage factory `build_trading_stage(config, services)`:
- Required: `repos`, `broker` (`Broker`), `pipeline` (`PipelineConfig`: budget and sizing).
- Optional: `account` (`AccountConfig`: spendable cash never exceeds the real account's available funds).

To test the real order path by hand: `scripts/paper_order_smoke.py` skips decision and risk, injects an approved buy for one symbol and runs the trading stage with `IBKRBroker` in paper mode; it refuses to run if the gateway reports any non-paper account.

## Running tests

```bash
python tasks.py test-trading
```
