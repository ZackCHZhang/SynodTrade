# quant-trading

交易执行：把风控批准的动作换算成订单，幂等地提交给券商，跟踪到成交、撤销或拒绝，成交写入数据库（子账本随之更新）。依赖 `quant-core`、`quant-database`。

## 流程（`trading` 阶段）

1. **安全检查**：
   - `ensure_mode_allowed`：`mode: live` 时必须设置 `QUANT_ALLOW_LIVE=1`。
   - Broker 的 `mode` 必须与本次运行的 `mode` 一致，比如 dry-run 流水线不能接真实券商。
   - 连接券商。
2. **对账**：先把之前运行遗留的未完成订单向券商查询并更新。
3. **Kill Switch**：下单前再查一次数据库标志；开启时不发任何新订单。
4. **生成订单**（`OrderPlanner`）：
   - 只处理风控最终结论（`ctx.risk_verdicts`）中不是 HOLD 的标的。
   - 顺序与风控阶段一致：卖单在前，买单按信号强弱排序。
   - 价格：最近 `max_quote_age_minutes` 内的报价，否则用最后一根已收盘 K 线的收盘价。
   - 限价（默认订单类型）：
     - 买入价 = 卖一价 × (1 + `limit_offset_bps`)，向上取到最小报价单位；
     - 卖出价 = 买一价 × (1 − offset)，向下取到最小报价单位；
     - 最小报价单位：股价 ≥ $1 时为 $0.01，否则为 $0.0001。
   - 数量：用 core 的五档仓位计算和子账本（可用现金、持仓），按交易单位向下取整；数量为 0 的订单跳过。**买单按限价计算数量**，所以股数不会超过风控评估时的股数。前一笔买单会从后面订单的可用现金中扣除。
   - `client_order_id = hash(run_id, symbol, action)`，作为幂等键。
5. **提交**（幂等）：先把订单写入数据库，再发给券商。
   - 订单已存在且已发出（例如同一 `run_id` 重跑）→ 不再发送。
   - 订单已存在但还是 PENDING_SUBMIT（上次写库后崩溃）→ 先向券商查询，**只有券商那边确实没有这笔单才发送**。
   - 发送时出错 → 订单保持 PENDING_SUBMIT 并记录错误，下次运行先查询再决定；本阶段最后报错。
6. **跟踪**：每隔 `poll_interval_seconds` 查询一次，直到全部订单成交、撤销或被拒；超过 `cancel_after_minutes` 仍未完成的订单自动撤销（已部分成交的部分保留）。成交按 `exec_id` 去重写入 `fills`，子账本的现金和持仓随之变化。`wait_for_fills: false` 时只提交不等待，由下次运行对账。

## Broker

| 实现 | 用途 | mode |
|---|---|---|
| `DryRunBroker` | 只记录（状态为 `DRY_RUN`），从不发送，也不会成交 | dry_run |
| `SimulatedBroker` | 在内存中模拟成交：立即全部成交、成交一半、永不成交、拒绝。用于测试和离线模拟 | dry_run |
| `IBKRBroker` | 通过 `ib_async` 向 TWS / IB Gateway 真实下单（paper 账户就是文档中的 PaperBroker） | paper / live |

`create_broker(mode, account)` 按运行模式创建：dry_run → `DryRunBroker`，paper / live → `IBKRBroker`。

**`IBKRBroker` 的安全措施**：
- live 模式在创建和连接时都检查 `QUANT_ALLOW_LIVE=1`。
- 连接后核对网关登录的账户：
  - paper 模式下，只要有任何非 paper 账户（paper 账户号以 `D` 开头）就拒绝；
  - live 模式下，拒绝 paper 账户；
  - 配置的账户必须在网关管理的账户之中。
- 每笔订单都带上账户号，以及写在 `orderRef` 里的 `client_order_id`。重启后可以通过当前会话、`reqAllOpenOrders`、执行记录三种途径找回订单，不会重复下单。
- 佣金报告到达后才写入成交；订单完成时，剩余成交一律写入（佣金为 0）。
- client id：交易连接使用 `IBKR_CLIENT_ID + 1`（行情用原 id，新闻用 +2）。

## 配置项

```yaml
- type: trading
  order_type: limit          # limit | market
  limit_offset_bps: 5
  time_in_force: DAY         # DAY | GTC
  cancel_after_minutes: 30
  poll_interval_seconds: 5
  wait_for_fills: true
  max_quote_age_minutes: 30
```

阶段工厂 `build_trading_stage(config, services)` 需要的服务：
- 必需：`repos`、`broker`（`Broker`）、`pipeline`（`PipelineConfig`：预算与 sizing）。
- 可选：`account`（`AccountConfig`：可动用现金不超过真实账户的可用资金）。

## 运行测试

```bash
python tasks.py test-trading
```
