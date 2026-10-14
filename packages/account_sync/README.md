# quant-account-sync

**English** | [简体中文](README.zh-CN.md)

Account sync: brings the database up to date with the real state of the IBKR account. The problem it solves: after an order is placed, the database only knows it was "submitted", not whether it actually filled.

Each sync (one connection per IBKR account, client id = account client_id + 4, so it never collides with a pipeline's connection):

1. **Open orders** (pending_submit / submitted / partially_filled): reads status, filled quantity and every execution (including commission) from IBKR and writes them back to `orders` / `fills`. An order IBKR cannot find (not open, not among completed orders, no executions) is closed as cancelled once it has been unchanged for `gone_after_minutes`; one that is partly filled but no longer open is closed at the filled quantity.
2. **Late fills**: orders closed within the last `recheck_days` days get their executions checked again. An order that was marked cancelled because IBKR could not find it, but actually filled, gets its fills added and becomes filled (the sync report carries a warning).
3. **Account and position snapshots**: NAV, cash, buying power and positions, written to `account_snapshots` / `position_snapshots`.
4. **Reconciliation**: IBKR positions vs the sum of every pipeline's virtual ledger; open orders on IBKR the database does not know about (manual orders, or orders placed from another database).

Orders of pipelines that are still running are left alone (their own trading stage tracks them). Each sync's result is stored in the `account_syncs` table.

## When it syncs

- **First pipeline step**: live paper / live runs (no `--as-of`) sync the pipeline's account before any stage (other pipelines on the same account are synced too); run details show it as step 1, "Account sync". `--offline`, `--dry-run` and `--as-of` replays do not sync.
- **On a timer**: inside the web console process, every `interval_minutes` (default 20) for all accounts; the "Account sync" page can change it, turn it off, or sync right away. Without the web console, use `quant-sync loop`.
- **Manually**: `quant-sync once`, or "Sync now" in the web console.

## Configuration: `configs/account_sync.yaml`

```yaml
enabled: true                  # scheduled sync (web console / quant-sync loop)
interval_minutes: 20
before_pipeline: true          # sync before every paper/live run
required_before_pipeline: false  # true: a failed sync fails the whole run (default: log it and continue)
gone_after_minutes: 30         # open orders IBKR cannot find are closed as cancelled after this long unchanged
recheck_days: 3                # orders closed within this many days are rechecked for late fills
snapshot: true                 # save account and position snapshots
accounts: []                   # only sync these account configs; empty = every account a pipeline uses
```

Without the file, the defaults above apply.

## Command line

```bash
quant-sync once  --db-url sqlite+aiosqlite:///./paper_test.db   # sync once and print the changes
quant-sync loop  --db-url ...                                    # keep syncing every interval_minutes
```

Note: by default IBKR only keeps the current day's executions (TWS can raise this to 7 days under Global Configuration > API > Settings). The shorter the sync interval, the less likely execution details are missed.
