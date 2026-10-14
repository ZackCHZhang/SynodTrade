# quant-decision

[English](README.md) | **简体中文**

决策：构造每个标的的决策上下文、决策 agent、多 agent 决策聚合。技术指标由 `quant_core.indicators` 计算（与风控、选股共用），本包只是重新导出。依赖 `quant-core`、`quant-database`。

## 流程（`decision` 阶段）

1. 读取流水线的**虚拟子账本**（截至 `as_of` 的现金、持仓、预留资金），用最新收盘价算出这条流水线的净值。
2. 对每个标的：
   - 读取最近 `bars_lookback` 根**已收盘**的 K 线。少于 `min_bars` 根时直接给出 HOLD（`method=insufficient_data`），不调用任何 agent。
   - 用代码计算技术指标（`compute_indicators`）。
   - 读取本次运行的舆情结果（去掉分析失败的）。
   - 读取最近 `history_limit` 次最终决策，并用代码算出每次决策之后价格的变化：决策时价格取决策前最后一根已收盘 K 线的收盘价。
3. 每个 agent 实例对每个标的调用一次 LLM，所有调用并发执行，得到 `Decision`。
4. 聚合器把同一标的的所有决策合成 `AggregatedDecision`。
5. 结果写入 `decisions` 和 `aggregated_decisions` 表，并写进 `PipelineContext`；agent 实例登记到 `agent_instances`。

## Agent 看到的数据

全部由代码计算，LLM 不做任何计算：

- 技术指标（见 `packages/core/README.md`）：1/5/20/60/120/250 日收益率；20 日、60 日年化波动率；SMA 20/50/200 及偏离；RSI 14；MACD(12,26,9)；52 周高低点及距离；近一年最大回撤；成交量相对前 20 日均量的倍数。历史数据不够时，对应指标为空，不会出现在 prompt 里。
- 最近 `recent_bars_in_prompt` 根 K 线（开高低收量）。
- 这条流水线的可用现金、净值，以及该标的的持仓（数量、成本、市值、浮动盈亏、占比）。
- 本次运行的舆情摘要。
- 历史最终决策及之后的价格变化。

**没有提供**基本面、财报、宏观、ATR 等数据。部分决策 agent 的 `instructions` 提到了这些数据（例如 `earnings_drift` 要求 EPS 意外、`garp_investor` 要求 PEG、`macro_regime` 要求利率和收益率曲线），模型只能根据上面的信息推断。

## Prompt 中的数据引用

每条数据都带一个 id：`ind:rsi_14`、`bar:2026-09-23`、`pos:AAPL`、`sent:<uuid>`、`hist:<uuid>`。agent 在 `referenced_data_ids` 中引用这些 id；不在本次 prompt 里的 id 会被丢弃并记录警告，所以每条决策引用的数据都能追溯到。prompt 还会告诉模型：

- 五档动作的确切含义：买入按可用现金的 15% / 30%，卖出按持仓的 15% / 30%。
- 不能做空；没有持仓时的卖出会被忽略。
- 之后的风控只会降低风险，不会放大仓位。

## 聚合（`aggregation`）

先把置信度低于 `min_confidence`（默认 0）的票，以及 agent 失败后回退的票，都当作 HOLD。

| 方法 | 规则 |
|---|---|
| `weighted_vote`（默认） | 以 agent 权重 × 置信度为权重，对五档的数值求加权平均，再映射回最近的档位；距离相等时取更靠近 HOLD 的档位 |
| `majority` | 某个方向（买 / 持有 / 卖）的 agent 权重之和必须**严格超过一半**；档位取该方向各票的加权平均，距离相等时取更靠近 HOLD 的档位。否则 HOLD |
| `unanimous` | 所有票必须同一方向，且都不是 HOLD；取其中**最保守**的档位。否则 HOLD |

`AggregatedDecision.votes` 保留每一票的**原始**动作、置信度和权重，`method` 字段记录所用的方法和阈值。

## 配置项

```yaml
- type: decision
  agents:
    - { agent: value_investor, count: 2, weight: 1.0, model: { provider: anthropic, name: claude-opus-5 } }
    - { agent: trend_follower, count: 1, weight: 0.8, model: { provider: deepseek, name: deepseek-chat } }
  aggregation: { method: weighted_vote, min_confidence: 0.6 }
  timeframe: 1d               # 默认 1d
  bars_lookback: 260          # 30–2000，默认 260（足够计算 SMA 200 和 52 周区间）
  min_bars: 30                # 默认 30
  recent_bars_in_prompt: 20   # 0–250，默认 20
  history_limit: 5            # 0–50，默认 5
```

仓库自带 21 个决策 agent 配置（`configs/agents/` 中 `role: decision` 的文件，例如 `value_investor`、`trend_follower`、`pullback_buyer`、`mean_reversion_swing`、`breakout_trader`）。它们都使用同一个实现 `DecisionAgent`（entry point `quant.agents` 中的 `decision`）和同一个模板 `configs/agents/prompts/decision_v1.j2`，区别只在人格和 `params.instructions`。模型在流水线的 agent 引用中指定。

阶段工厂 `build_decision_stage(config, services)` 需要的服务：`repos`、`config_store`、`llm`（`LLMClientPool`）、`pipeline`（`PipelineConfig`，用其中的 `budget.max_capital` 计算子账本）。

## 运行测试

```bash
python tasks.py test-decision
```
