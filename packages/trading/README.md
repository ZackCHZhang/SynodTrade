# quant-trading

[中文](#中文) | [English](#english)

---

## 中文

交易执行：把风控批准的动作换算成订单，幂等地提交给券商，跟踪到成交、撤销或拒绝，成交写入数据库（子账本随之更新）。依赖 `quant-core`、`quant-database`。

### 流程（`trading` 阶段）

1. **安全检查**：
   - `ensure_mode_allowed`：`mode: live` 时必须设置 `QUANT_ALLOW_LIVE=1`。
   - Broker 的 `mode` 必须与本次运行的 `mode` 一致，比如 dry-run 流水线不能接真实券商。
   - 连接券商。
2. **对账**：先把这条流水线之前运行遗留的未完成订单向券商查询并更新。
3. **Kill Switch**：下单前再查一次数据库标志；开启时不发任何新订单。
4. **生成订单**（`OrderPlanner`）：
   - 只处理风控最终结论（`ctx.risk_verdicts`）中不是 HOLD 的标的。
   - 顺序与风控阶段一致：卖单在前，买单按信号强弱排序。
   - 价格：最近 `max_quote_age_minutes` 内的报价，否则用最后一根已收盘 K 线的收盘价。
   - 限价（默认订单类型，即"立即成交型限价单"）：
     - 买入价 = 卖一价 × (1 + `limit_offset_bps` / 10000)，向上取到最小报价单位；没有卖一价时用参考价；
     - 卖出价 = 买一价 × (1 − offset)，向下取到最小报价单位；
     - 最小报价单位：股价 ≥ $1 时为 $0.01，否则为 $0.0001。
   - `order_type: market` 时不设限价。
   - 数量：用 core 的五档仓位计算和子账本（可用现金、持仓），按交易单位向下取整；数量为 0 的订单跳过。**买单按限价计算数量**，所以股数不会超过风控评估时的股数。前一笔买单会从后面订单的可用现金中扣除。配置了 `account` 时，可动用现金不超过真实账户的可用资金。
   - `client_order_id = hash(run_id, symbol, action)`，作为幂等键。
5. **提交**（幂等）：先把订单写入数据库，再发给券商。
   - 订单已存在且已发出（例如同一 `run_id` 重跑）→ 不再发送。
   - 订单已存在但还是 PENDING_SUBMIT（上次写库后崩溃）→ 先向券商查询，**只有券商那边确实没有这笔单才发送**。
   - 发送时出错 → 订单保持 PENDING_SUBMIT 并记录错误，下次运行先查询再决定；本阶段最后报错。
6. **跟踪**（`wait_for_fills: true`，默认）：每隔 `poll_interval_seconds` 查询一次，直到全部订单成交、撤销或被拒；超过 `cancel_after_minutes` 仍未完成的订单自动撤销（已部分成交的部分保留）。成交按 `exec_id` 去重写入 `fills`，子账本的现金和持仓随之变化。
   - `wait_for_fills: false` 时只提交不等待，由下次运行对账。
   - 注意：`wait_for_fills: true` 时，无论 `time_in_force` 是 DAY 还是 GTC，到期未成交的订单都会被撤销；只有 `wait_for_fills: false` 时，GTC 订单才会跨运行继续挂着。

### Broker

| 实现 | 用途 | mode |
|---|---|---|
| `DryRunBroker` | 只记录（状态为 `DRY_RUN`），从不发送，也不会成交 | dry_run |
| `SimulatedBroker` | 在内存中模拟成交：立即全部成交、成交一半、永不成交、拒绝。用于测试和离线模拟 | dry_run |
| `IBKRBroker` | 通过 `ib_async` 向 TWS / IB Gateway 真实下单（paper 账户也走这个实现） | paper / live |

`create_broker(mode, account)` 按运行模式创建：dry_run → `DryRunBroker`，paper / live → `IBKRBroker`（需要账户配置）。

**`IBKRBroker` 的安全措施**：
- live 模式在创建和连接时都检查 `QUANT_ALLOW_LIVE=1`。
- 连接后核对网关登录的账户：
  - paper 模式下，只要有任何非 paper 账户（paper 账户号以 `D` 开头）就拒绝；
  - live 模式下，拒绝 paper 账户；
  - 配置的账户必须在网关管理的账户之中。
- 每笔订单都带上账户号，以及写在 `orderRef` 里的 `client_order_id`。重启后可以通过当前会话、`reqAllOpenOrders`、执行记录三种途径找回订单，不会重复下单。
- 佣金报告到达后才写入成交；订单完成时，剩余成交一律写入（佣金为 0）。
- client id：交易连接使用账户配置的 `client_id + 1`（行情用原 id，新闻用 +2，选股扫描器用 +3）。

### 配置项

```yaml
- type: trading
  order_type: limit          # limit | market，默认 limit
  limit_offset_bps: 5        # 0–500，默认 5
  time_in_force: DAY         # DAY | GTC，默认 DAY
  cancel_after_minutes: 30   # 默认 30
  poll_interval_seconds: 5   # 默认 5
  wait_for_fills: true       # 默认 true
  max_quote_age_minutes: 30  # 默认 30
  timeframe: 1d              # 没有报价时用哪个周期的收盘价，默认 1d
```

阶段工厂 `build_trading_stage(config, services)` 需要的服务：
- 必需：`repos`、`broker`（`Broker`）、`pipeline`（`PipelineConfig`：预算与 sizing）。
- 可选：`account`（`AccountConfig`：可动用现金不超过真实账户的可用资金）。

手动测试真实下单路径：`scripts/paper_order_smoke.py` 跳过决策和风控，直接给一个标的注入一笔已批准的买单，用 `IBKRBroker` 在 paper 模式下走完交易阶段；网关上只要有非 paper 账户就拒绝运行。

### 运行测试

```bash
python tasks.py test-trading
```

---

## English

Order execution: turns the actions approved by risk into orders, submits them idempotently, tracks them until filled, cancelled or rejected, and writes fills to the database (which updates the sub-ledger). Depends on `quant-core` and `quant-database`.

### Flow (`trading` stage)

1. **Safety checks**:
   - `ensure_mode_allowed`: `mode: live` requires `QUANT_ALLOW_LIVE=1`.
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

### Brokers

| Implementation | Purpose | mode |
|---|---|---|
| `DryRunBroker` | records only (status `DRY_RUN`); never sends, never fills | dry_run |
| `SimulatedBroker` | in-memory fills: fill fully at once, fill half, never fill, reject. For tests and offline simulation | dry_run |
| `IBKRBroker` | real orders to TWS / IB Gateway through `ib_async` (paper accounts use it too) | paper / live |

`create_broker(mode, account)` picks by run mode: dry_run → `DryRunBroker`, paper / live → `IBKRBroker` (needs an account config).

**`IBKRBroker` safeguards**:
- Live mode checks `QUANT_ALLOW_LIVE=1` both when created and when connecting.
- After connecting it checks the accounts logged in on the gateway:
  - paper mode refuses if any non-paper account is present (paper account ids start with `D`);
  - live mode refuses paper accounts;
  - the configured account must be among the gateway's managed accounts.
- Every order carries the account id and the `client_order_id` in `orderRef`. After a restart, orders are found again through the current session, `reqAllOpenOrders` and executions, so nothing is placed twice.
- Fills are written once their commission report arrives; when an order completes, any remaining fills are written (commission 0).
- Client id: the trading connection uses the account config's `client_id + 1` (market data the plain id, news +2, the selection scanner +3).

### Configuration

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

### Running tests

```bash
python tasks.py test-trading
```
