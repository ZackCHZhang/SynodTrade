# quant-selection

[中文](#中文) | [English](#english)

---

## 中文

选股模块：从候选池里挑出本次运行要跟踪的股票。选股结果会**替换本次运行的 universe**，后面的行情、舆情、决策、风控、交易阶段都只处理选出的股票（加上已有持仓）。依赖 `quant-core`、`quant-database`。

### 流程

1. **收集候选**：来自多个候选来源。
   - `universe`：流水线 YAML 里的 `universe`，默认算作一个来源（`include_universe: true`）。
   - `static`：YAML 里写死的股票列表，顺序即排名。
   - `ibkr_scanner`：IBKR 市场扫描器，例如 MOST_ACTIVE、TOP_PERC_GAIN。

   某个来源失败时只记录警告，全部来源都失败才让阶段失败。总数上限是 `max_raw_candidates`（默认 60），用来限制 K 线请求数，避免触发 IBKR pacing。
2. **拉 K 线**：通过 core 的 `BarsRefresher` 协议（由行情模块的 `DataUpdater.update_bars` 实现）增量更新候选股的日线（`refresh_bars: true`，回看 `lookback_days`，默认 400 天），然后只读取 `as_of` 之前已收盘的最近 `bars_lookback` 根（默认 260）。
3. **量化初筛**（`screen`，纯代码）：
   - 按已收盘 K 线数量（`min_bars`）、价格区间（`min_price` / `max_price`）、20 日平均成交额（`min_avg_dollar_volume`）、60 日年化波动率（`max_volatility`）过滤。
   - 通过的股票按成交额从高到低排序，只留前 `max_candidates` 只给 agent。
   - 每只被淘汰的股票都记录原因。
4. **多个选股 agent 各自挑选**：
   - 每个 agent 看到完整的候选表。指标都由代码算好，LLM 不做计算。
   - 候选表只包含价格 / 成交量类数据：收盘价、20 日 / 60 日 / 1 年收益、60 日波动率、相对 SMA50 / SMA200 的偏离、RSI14、距 52 周高点、1 年最大回撤、日均成交额。**没有基本面数据**，所以基本面类的选股 agent（如 `piotroski_screen`、`net_net_screen`）只能根据这些信息推断。
   - 每个 agent 最多挑 `max_picks_per_agent` 只（默认 10），每只给 0–1 的分数和理由。
   - 不在候选里的代码会被丢弃并记日志。
5. **聚合**（`aggregation`）：
   - `weighted_score`（默认）：按 agent 权重对分数加权平均，没选某只股票的 agent 对它记 0 分。
   - `approval`：按权重计算选中某只股票的 agent 占比。

   失败的 agent 不参与聚合。按分数取前 `top_n` 只（默认 5），并要求分数不低于 `min_score`（默认 0）。
6. **保留持仓**（`keep_holdings: true`，默认开启）：这条流水线子账本里已持有的股票始终留在 universe 里，所以落选的股票仍然可以被决策阶段卖出。
7. **全部 agent 都失败时**（`fallback`）：
   - `previous`（默认）：沿用上次的选股结果（还没有时只保留持仓）。
   - `holdings`：只保留持仓，本次不会买入新股票。
   - `fail`：阶段失败。

每个 agent 的输出写入 `selection_results` 表，最终结果写入 `stock_selections` 表，包括候选、入选、持仓、分数和淘汰原因。下一次选股时，agent 会看到上次的结果，这样可以避免无谓的换股。

### 配置示例（`configs/pipelines/*.yaml`）

```yaml
universe: [AAPL, MSFT, NVDA, AMZN, GOOGL]   # 有 selection 阶段时，universe 就是候选池，可以为空
stages:
  - type: selection                  # 必须排在所有阶段之前
    sources:
      - { type: static, symbols: [JPM, V, COST, LLY] }
      - { type: ibkr_scanner, scan_code: MOST_ACTIVE, rows: 20, above_price: 10,
          market_cap_above: 10000, stock_type: CORP }  # 市值：百万美元；CORP 排除 ETF
    screen: { min_price: 5, min_avg_dollar_volume: 20000000, max_candidates: 25 }
    agents:                          # 选股 agent 和模型都在实例化时指定
      - { agent: momentum_screener,  count: 1, weight: 1.0,
          model: { provider: deepseek, name: deepseek-chat } }
      - { agent: defensive_screener, count: 1, weight: 1.0,
          model: { provider: anthropic, name: claude-sonnet-5-5 } }
    aggregation: { method: weighted_score, top_n: 3, min_score: 0.3 }
    max_picks_per_agent: 5
  - type: data_update
  # ... sentiment / decision / risk / trading
```

`ibkr_scanner` 的其他选项：`instrument`（默认 STK）、`location`（默认 `STK.US.MAJOR`）、`rows`（1–50，默认 25）、`below_price`、`above_volume`、`market_cap_below`、`filters`（额外的 IBKR 过滤标签）、`host` / `port` / `client_id`。

仓库自带 22 个选股 agent 配置（`configs/agents/*_screen*.yaml` 等，`role: selection`），共用模板 `prompts/selection_v1.j2`。

自定义选股 agent 的方法：在 `configs/agents/` 下新建一个 `role: selection` 的 YAML，写上人设和 `params.instructions`，模板用 `prompts/selection_v1.j2`。如果要换一套完全不同的逻辑，可以继承 `SelectionAgent`，通过 entry point `quant.agents` 注册后，在 agent 配置里用 `impl:` 指定。

自定义候选来源的方法：实现 core 的 `CandidateSource`（包含 `name` 和 `async fetch(as_of) -> list[Candidate]`），然后通过 entry point `quant.candidate_sources` 注册。

### IBKR 扫描器

- 扫描器使用独立的只读连接，默认 client id 是 `IBKR_CLIENT_ID + 3`：行情用配置的 id，交易用 +1，新闻用 +2。
- 扫描结果取决于账户的行情订阅。结果为空时只记录警告。实测 paper 账户没有行情订阅也能用 MOST_ACTIVE。
- 不设 `stock_type` 时，扫描结果里会混入 ETF（例如 SOXL、TQQQ、TLT）。选股时建议设 `stock_type: CORP`，但这样也会排除 ADR。
- 日志里的 `Error 162 ... API scanner subscription cancelled` 是正常现象：ib_async 拿到结果后会主动取消订阅，这条消息不影响结果。
- 扫描器只能看到当前时刻的结果，没有历史数据，所以用过去的 `as_of` 运行时，扫描结果不受 `as_of` 约束。

### 运行测试

```bash
python tasks.py test-selection
```

---

## English

Stock selection: picks the stocks this run follows from a candidate pool. The selection **replaces the run's universe**; the later data, sentiment, decision, risk and trading stages only handle the selected stocks (plus existing holdings). Depends on `quant-core` and `quant-database`.

### Flow

1. **Collect candidates** from several candidate sources.
   - `universe`: the pipeline YAML's `universe` counts as a source by default (`include_universe: true`).
   - `static`: a fixed list in the YAML; its order is the rank.
   - `ibkr_scanner`: IBKR market scanners such as MOST_ACTIVE or TOP_PERC_GAIN.

   A failing source only logs a warning; the stage fails only when every source fails. The total is capped by `max_raw_candidates` (default 60) to limit bar requests and stay clear of IBKR pacing.
2. **Fetch bars** through core's `BarsRefresher` protocol (implemented by the market-data package's `DataUpdater.update_bars`): candidates' daily bars are updated incrementally (`refresh_bars: true`, looking back `lookback_days`, default 400), then only the latest `bars_lookback` (default 260) bars completed before `as_of` are read.
3. **Quantitative screen** (`screen`, code only):
   - Filters on the number of completed bars (`min_bars`), price range (`min_price` / `max_price`), 20-day average dollar volume (`min_avg_dollar_volume`) and annualised 60-day volatility (`max_volatility`).
   - Survivors are sorted by dollar volume, highest first; only the top `max_candidates` are shown to the agents.
   - Every rejected stock is recorded with its reason.
4. **Several selection agents pick independently**:
   - Every agent sees the full candidate table. All numbers are computed in code; the LLM does no arithmetic.
   - The table contains price / volume data only: close, 20-day / 60-day / 1-year return, 60-day volatility, distance from SMA50 / SMA200, RSI14, distance from the 52-week high, 1-year maximum drawdown, average dollar volume. **There is no fundamental data**, so fundamental-style selection agents (e.g. `piotroski_screen`, `net_net_screen`) can only infer from this information.
   - Each agent picks at most `max_picks_per_agent` (default 10), each with a 0–1 score and a reason.
   - Symbols that are not candidates are dropped and logged.
5. **Aggregation** (`aggregation`):
   - `weighted_score` (default): weighted average of the scores by agent weight; an agent that did not pick a stock counts as 0 for it.
   - `approval`: the weighted share of agents that picked the stock.

   Failed agents are left out. The top `top_n` (default 5) by score are kept, provided their score is at least `min_score` (default 0).
6. **Keep holdings** (`keep_holdings: true`, default): stocks held in this pipeline's sub-ledger always stay in the universe, so a stock that drops out can still be sold by the decision stage.
7. **When every agent fails** (`fallback`):
   - `previous` (default): reuse the last selection (holdings only if there is none yet).
   - `holdings`: holdings only; nothing new is bought this run.
   - `fail`: fail the stage.

Each agent's output goes to `selection_results`, the final result to `stock_selections` (candidates, picks, holdings, scores and rejection reasons). The next selection shows the agents the previous result, which avoids needless turnover.

### Example configuration (`configs/pipelines/*.yaml`)

```yaml
universe: [AAPL, MSFT, NVDA, AMZN, GOOGL]   # with a selection stage the universe is the candidate pool and may be empty
stages:
  - type: selection                  # must come before every other stage
    sources:
      - { type: static, symbols: [JPM, V, COST, LLY] }
      - { type: ibkr_scanner, scan_code: MOST_ACTIVE, rows: 20, above_price: 10,
          market_cap_above: 10000, stock_type: CORP }  # market cap in millions of USD; CORP excludes ETFs
    screen: { min_price: 5, min_avg_dollar_volume: 20000000, max_candidates: 25 }
    agents:                          # selection agents and their models are chosen here
      - { agent: momentum_screener,  count: 1, weight: 1.0,
          model: { provider: deepseek, name: deepseek-chat } }
      - { agent: defensive_screener, count: 1, weight: 1.0,
          model: { provider: anthropic, name: claude-sonnet-5-5 } }
    aggregation: { method: weighted_score, top_n: 3, min_score: 0.3 }
    max_picks_per_agent: 5
  - type: data_update
  # ... sentiment / decision / risk / trading
```

Other `ibkr_scanner` options: `instrument` (default STK), `location` (default `STK.US.MAJOR`), `rows` (1–50, default 25), `below_price`, `above_volume`, `market_cap_below`, `filters` (extra IBKR filter tags), `host` / `port` / `client_id`.

The repository ships 22 selection agent configs (`role: selection` in `configs/agents/`), all using the template `prompts/selection_v1.j2`.

To add a selection agent: create a `role: selection` YAML in `configs/agents/` with a persona and `params.instructions`, using the template `prompts/selection_v1.j2`. For entirely different logic, subclass `SelectionAgent`, register it through the entry point `quant.agents` and select it with `impl:` in the agent config.

To add a candidate source: implement core's `CandidateSource` (`name` and `async fetch(as_of) -> list[Candidate]`) and register it through the entry point `quant.candidate_sources`.

### IBKR scanner

- The scanner uses its own read-only connection; the default client id is `IBKR_CLIENT_ID + 3` (market data uses the configured id, trading +1, news +2).
- Results depend on the account's market-data subscriptions; an empty result only logs a warning. In practice MOST_ACTIVE works on a paper account without subscriptions.
- Without `stock_type`, ETFs (e.g. SOXL, TQQQ, TLT) show up in the results. `stock_type: CORP` is recommended for stock selection, but it also excludes ADRs.
- `Error 162 ... API scanner subscription cancelled` in the log is expected: ib_async cancels the subscription itself once it has the results; the message does not affect them.
- A scanner only sees the present and has no history, so when running with a past `as_of` the scanner results are not bound by `as_of`.

### Running tests

```bash
python tasks.py test-selection
```
