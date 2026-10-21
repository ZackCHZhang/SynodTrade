# synodtrade-risk

[English](README.md) | **简体中文**

风控分两层：确定性硬规则 + 风控 agent（LLM，只能降低风险）。依赖 `synodtrade-core`、`synodtrade-database`。

## 流程（`risk` 阶段）

1. **载入组合状态**（截至 `as_of`）：
   - 流水线虚拟子账本里的现金、持仓，以及未成交买单预留的现金。
   - 各标的当前价格：优先用最近 `max_quote_age_minutes` 内的报价，否则用最后一根已收盘 K 线的收盘价。
   - 净值（NAV）。
   - 今日和本周收益：用当日（或本周一）开始时的子账本和当时价格推算。
   - 今日已下单数、各标的今日订单数。
   - Kill Switch 数据库标志。
   - 交易所是否开市（`exchange_calendars`，默认 XNYS，节假日和半日市都已考虑）。
   - 可动用现金：配置了 `account` 服务时，还会受真实账户可用资金的限制。
2. **第一层：硬规则**。逐个标的顺序评估，**卖单先于买单**，买单按信号强弱排序。每通过一笔，就从状态中扣除它占用的现金、敞口和交易次数，所以同一次运行里的多笔买单不会合起来突破限额。
3. **第二层：风控 agent**。只审查硬规则放行、且不是 HOLD 的标的，所有调用并发执行。
4. **合并**：`most_conservative`（默认）取最保守的结果，`median` 取偏保守的中位数，得出最终结果。
5. **写库**：每个标的写入三类记录，都进 `risk_assessments` 表：
   - `source="rules"`：硬规则的结论与全部命中规则；
   - 每个风控 agent 各一条；
   - `source="final"`：最终结论。

   `PipelineContext.risk_verdicts[symbol]` 保存最终结论，交易阶段只认这个结论。

## 第一层：硬规则（`configs/risk/<name>.yaml`）

比例均相对**本流水线的净值**（虚拟子账本），不是整个 IBKR 账户。

**关卡**（与订单大小无关）：

| 规则 | 效果 |
|---|---|
| `kill_switch`（配置）或数据库标志 `kill_switch` | 全部改为 HOLD（买、卖都拒绝） |
| 白名单（`whitelist`，为空时不限制）、黑名单（`blacklist`） | 全部改为 HOLD |
| 交易时间（`trading_hours.enabled`，非常规交易时段） | 全部改为 HOLD |
| 没有价格 | 全部改为 HOLD |
| 今日交易数 ≥ `max_trades_per_day` | 全部改为 HOLD |
| `one_order_per_symbol_per_day`：该标的今天已下过单 | 全部改为 HOLD |
| 今日亏损 ≥ `max_daily_loss_pct`，或本周亏损 ≥ `max_weekly_loss_pct` | **只禁止买入**，卖出照常 |
| 流动性：价差 > `max_spread_bps`；20 日均量 < `min_avg_volume`；`require_quote` 时缺少报价 | **只禁止买入** |

**规模规则**：用 core 的仓位计算函数算出这笔订单的实际数量和金额再检查。某一档不通过时，逐档降级：STRONG_BUY → BUY → HOLD。

| 规则 | 适用 |
|---|---|
| 单笔金额 > `max_order_notional` | 买、卖 |
| 买后单标的占比 > `max_position_pct` | 买 |
| 买后总敞口 > `max_gross_exposure_pct` | 买 |
| 买后现金 < `min_cash_pct` | 买 |

**代码中的默认值**（`RiskRulesConfig`）：`max_position_pct` 0.20、`max_gross_exposure_pct` 0.90、`min_cash_pct` 0.10、`max_daily_loss_pct` 0.03、`max_weekly_loss_pct` 0.06、`max_trades_per_day` 4、`max_order_notional` 不限制、`one_order_per_symbol_per_day` true、`max_spread_bps` 50、`min_avg_volume` 100000、`require_quote` false、`trading_hours` 开启（XNYS）。仓库里的 `default.yaml` 另外把 `max_order_notional` 设为 2000；`etf.yaml` 放宽了仓位和敞口，并加了白名单。

**边界约定**：
- 恰好等于上限算通过。
- 亏损恰好达到阈值算触发熔断。
- 卖出所得在本次运行中不计入可用现金，因为卖单可能晚于买单成交。
- 算出来不足一股的订单，只记录一条提示，不算违规；交易阶段会直接跳过它。

硬规则里**没有**基于波动率的仓位计算、交易成本检查、板块 / 相关性集中度限制或财报前禁买。

## 第二层：风控 agent

- 看到的内容：
  - 最初的决策和规则调整后的动作；
  - 拟下订单（方向、数量、金额）和组合状态（现金、敞口、今日 / 本周收益等）；
  - 6 个市场指标（由 `synodtrade_core.indicators` 计算）：最新收盘价、1 日收益、20 日收益、20 日波动率、距 52 周高点、RSI 14；
  - 各决策 agent 的动作、置信度和理由，舆情摘要，规则命中情况。
- **"只能降低风险"由代码强制执行**：每次调用都用一个绑定了本次拟定动作的输出模型来校验（`bounded_output`）。模型给出的动作如果比拟定的更激进或方向相反，就算校验失败：先把错误信息反馈给模型重试，仍不合格则按失败策略处理。之后 `RiskVerdict` 模型还会再校验一次。
- 失败策略 `on_agent_failure`：默认 `reject`，LLM 不可用时拒绝交易（fail-safe）；也可以设为 `approve`，放行硬规则已通过的动作。
- 模型在实例化时选择：流水线 agent 引用里的 `model`，或者代码里 `RiskAgent(..., model=...)`。
- 仓库自带 21 个风控 agent 配置（`role: risk`），例如 `conservative_risk_officer`、`volatility_position_sizer`、`earnings_event_risk`、`gap_risk_monitor`。它们共用模板 `configs/agents/prompts/risk_v1.j2`。其中一些 agent 的 `instructions` 要求 ATR、财报日期、历史跳空、相关性等数据，但风控 agent 只看到上面列出的数据，模型只能据此推断。

## 配置项

```yaml
- type: risk
  rules: default               # configs/risk/default.yaml
  agents:
    - { agent: conservative_risk_officer, count: 1, model: { provider: anthropic, name: claude-opus-5 } }
  combine: most_conservative   # most_conservative | median
  on_agent_failure: reject     # reject | approve
  max_quote_age_minutes: 30
  timeframe: 1d                # 读取 K 线用的周期，默认 1d
```

阶段工厂 `build_risk_stage(config, services)` 需要的服务：
- 必需：`repos`、`config_store`、`llm`、`pipeline`（`PipelineConfig`，用其中的预算与 sizing 设置）。
- 可选：`account`（`AccountConfig`，用真实账户的可用资金限制可动用现金）、`market_clock`（`MarketClock`，默认 `ExchangeCalendarClock`，使用规则配置里的交易所日历；测试或离线运行可以换成 `AlwaysOpenClock`）。

## 运行测试

```bash
python tasks.py test-risk
```
