# quant-decision

[中文](#中文) | [English](#english)

---

## 中文

决策：构造每个标的的决策上下文、决策 agent、多 agent 决策聚合。技术指标由 `quant_core.indicators` 计算（与风控、选股共用），本包只是重新导出。依赖 `quant-core`、`quant-database`。

### 流程（`decision` 阶段）

1. 读取流水线的**虚拟子账本**（截至 `as_of` 的现金、持仓、预留资金），用最新收盘价算出这条流水线的净值。
2. 对每个标的：
   - 读取最近 `bars_lookback` 根**已收盘**的 K 线。少于 `min_bars` 根时直接给出 HOLD（`method=insufficient_data`），不调用任何 agent。
   - 用代码计算技术指标（`compute_indicators`）。
   - 读取本次运行的舆情结果（去掉分析失败的）。
   - 读取最近 `history_limit` 次最终决策，并用代码算出每次决策之后价格的变化：决策时价格取决策前最后一根已收盘 K 线的收盘价。
3. 每个 agent 实例对每个标的调用一次 LLM，所有调用并发执行，得到 `Decision`。
4. 聚合器把同一标的的所有决策合成 `AggregatedDecision`。
5. 结果写入 `decisions` 和 `aggregated_decisions` 表，并写进 `PipelineContext`；agent 实例登记到 `agent_instances`。

### Agent 看到的数据

全部由代码计算，LLM 不做任何计算：

- 技术指标（见 `packages/core/README.md`）：1/5/20/60/120/250 日收益率；20 日、60 日年化波动率；SMA 20/50/200 及偏离；RSI 14；MACD(12,26,9)；52 周高低点及距离；近一年最大回撤；成交量相对前 20 日均量的倍数。历史数据不够时，对应指标为空，不会出现在 prompt 里。
- 最近 `recent_bars_in_prompt` 根 K 线（开高低收量）。
- 这条流水线的可用现金、净值，以及该标的的持仓（数量、成本、市值、浮动盈亏、占比）。
- 本次运行的舆情摘要。
- 历史最终决策及之后的价格变化。

**没有提供**基本面、财报、宏观、ATR 等数据。部分决策 agent 的 `instructions` 提到了这些数据（例如 `earnings_drift` 要求 EPS 意外、`garp_investor` 要求 PEG、`macro_regime` 要求利率和收益率曲线），模型只能根据上面的信息推断。

### Prompt 中的数据引用

每条数据都带一个 id：`ind:rsi_14`、`bar:2026-09-23`、`pos:AAPL`、`sent:<uuid>`、`hist:<uuid>`。agent 在 `referenced_data_ids` 中引用这些 id；不在本次 prompt 里的 id 会被丢弃并记录警告，所以每条决策引用的数据都能追溯到。prompt 还会告诉模型：

- 五档动作的确切含义：买入按可用现金的 15% / 30%，卖出按持仓的 15% / 30%。
- 不能做空；没有持仓时的卖出会被忽略。
- 之后的风控只会降低风险，不会放大仓位。

### 聚合（`aggregation`）

先把置信度低于 `min_confidence`（默认 0）的票，以及 agent 失败后回退的票，都当作 HOLD。

| 方法 | 规则 |
|---|---|
| `weighted_vote`（默认） | 以 agent 权重 × 置信度为权重，对五档的数值求加权平均，再映射回最近的档位；距离相等时取更靠近 HOLD 的档位 |
| `majority` | 某个方向（买 / 持有 / 卖）的 agent 权重之和必须**严格超过一半**；档位取该方向各票的加权平均，距离相等时取更靠近 HOLD 的档位。否则 HOLD |
| `unanimous` | 所有票必须同一方向，且都不是 HOLD；取其中**最保守**的档位。否则 HOLD |

`AggregatedDecision.votes` 保留每一票的**原始**动作、置信度和权重，`method` 字段记录所用的方法和阈值。

### 配置项

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

### 运行测试

```bash
python tasks.py test-decision
```

---

## English

Decision: builds each symbol's decision context, runs the decision agents and aggregates their votes. Technical indicators are computed by `quant_core.indicators` (shared with risk and selection); this package only re-exports them. Depends on `quant-core` and `quant-database`.

### Flow (`decision` stage)

1. Reads the pipeline's **virtual sub-ledger** (cash, positions and reserved cash as of `as_of`) and values it at the latest closes to get the pipeline's NAV.
2. For each symbol:
   - Reads the latest `bars_lookback` **completed** bars. With fewer than `min_bars` the result is HOLD (`method=insufficient_data`) without asking any agent.
   - Computes the technical indicators in code (`compute_indicators`).
   - Reads this run's sentiment results (failed analyses excluded).
   - Reads the last `history_limit` final decisions and computes in code how the price moved since each one; the price at decision time is the close of the last bar completed before it.
3. Every agent instance calls the LLM once per symbol; all calls run concurrently and produce `Decision`s.
4. The aggregator combines a symbol's decisions into an `AggregatedDecision`.
5. Results go to the `decisions` and `aggregated_decisions` tables and into `PipelineContext`; agent instances are registered in `agent_instances`.

### What agents see

All computed in code; the LLM does no arithmetic:

- Technical indicators (see `packages/core/README.md`): returns over 1/5/20/60/120/250 days; annualised 20- and 60-day volatility; SMA 20/50/200 and distances; RSI 14; MACD(12,26,9); 52-week high / low and distances; 1-year maximum drawdown; volume relative to the previous 20-day average. An indicator without enough history is omitted from the prompt.
- The latest `recent_bars_in_prompt` bars (OHLCV).
- The pipeline's available cash and NAV, and the position in the symbol (quantity, cost, market value, unrealised P&L, weight).
- This run's sentiment summaries.
- Past final decisions and the price move since.

Fundamentals, earnings, macro data and ATR are **not provided**. Some decision agents' `instructions` mention such data (e.g. `earnings_drift` asks for EPS surprises, `garp_investor` for PEG, `macro_regime` for rates and the yield curve); the model can only infer it from the information above.

### Data references in the prompt

Every piece of data carries an id: `ind:rsi_14`, `bar:2026-09-23`, `pos:AAPL`, `sent:<uuid>`, `hist:<uuid>`. Agents cite them in `referenced_data_ids`; ids that were not in this prompt are dropped with a warning, so the data behind every decision is traceable. The prompt also tells the model:

- The exact meaning of the five actions: buys use 15% / 30% of available cash, sells 15% / 30% of the position.
- No shorting; a sell without a position is ignored.
- Later risk controls can only reduce risk, never enlarge a position.

### Aggregation (`aggregation`)

Votes below `min_confidence` (default 0) and fallback votes of failed agents count as HOLD first.

| Method | Rule |
|---|---|
| `weighted_vote` (default) | Weighted average of the five tiers' values with weight = agent weight × confidence, mapped back to the nearest tier; ties go toward HOLD |
| `majority` | One direction (buy / hold / sell) needs **strictly more than half** of the total agent weight; the tier is the weighted average of that direction's votes, ties toward HOLD. Otherwise HOLD |
| `unanimous` | All votes in one direction and none HOLD; the **most conservative** of them wins. Otherwise HOLD |

`AggregatedDecision.votes` keeps every vote's **original** action, confidence and weight; `method` records the method and thresholds used.

### Configuration

```yaml
- type: decision
  agents:
    - { agent: value_investor, count: 2, weight: 1.0, model: { provider: anthropic, name: claude-opus-5 } }
    - { agent: trend_follower, count: 1, weight: 0.8, model: { provider: deepseek, name: deepseek-chat } }
  aggregation: { method: weighted_vote, min_confidence: 0.6 }
  timeframe: 1d               # default 1d
  bars_lookback: 260          # 30–2000, default 260 (enough for SMA 200 and the 52-week range)
  min_bars: 30                # default 30
  recent_bars_in_prompt: 20   # 0–250, default 20
  history_limit: 5            # 0–50, default 5
```

The repository ships 21 decision agent configs (files with `role: decision` in `configs/agents/`, e.g. `value_investor`, `trend_follower`, `pullback_buyer`, `mean_reversion_swing`, `breakout_trader`). All use the same implementation `DecisionAgent` (`decision` in the `quant.agents` entry point) and the same template `configs/agents/prompts/decision_v1.j2`; they differ only in persona and `params.instructions`. The model is chosen in the pipeline's agent reference.

Services needed by the stage factory `build_decision_stage(config, services)`: `repos`, `config_store`, `llm` (`LLMClientPool`), `pipeline` (`PipelineConfig`; its `budget.max_capital` is used for the sub-ledger).

### Running tests

```bash
python tasks.py test-decision
```
