# synodtrade-selection

**English** | [简体中文](README.zh-CN.md)

Stock selection: picks the stocks this run follows from a candidate pool. The selection **replaces the run's universe**; the later data, sentiment, decision, risk and trading stages only handle the selected stocks (plus existing holdings). Depends on `synodtrade-core` and `synodtrade-database`.

## Flow

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

## Example configuration (`configs/pipelines/*.yaml`)

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

To add a selection agent: create a `role: selection` YAML in `configs/agents/` with a persona and `params.instructions`, using the template `prompts/selection_v1.j2`. For entirely different logic, subclass `SelectionAgent`, register it through the entry point `synodtrade.agents` and select it with `impl:` in the agent config.

To add a candidate source: implement core's `CandidateSource` (`name` and `async fetch(as_of) -> list[Candidate]`) and register it through the entry point `synodtrade.candidate_sources`.

## IBKR scanner

- The scanner uses its own read-only connection; the default client id is `IBKR_CLIENT_ID + 3` (market data uses the configured id, trading +1, news +2).
- Results depend on the account's market-data subscriptions; an empty result only logs a warning. In practice MOST_ACTIVE works on a paper account without subscriptions.
- Without `stock_type`, ETFs (e.g. SOXL, TQQQ, TLT) show up in the results. `stock_type: CORP` is recommended for stock selection, but it also excludes ADRs.
- `Error 162 ... API scanner subscription cancelled` in the log is expected: ib_async cancels the subscription itself once it has the results; the message does not affect them.
- A scanner only sees the present and has no history, so when running with a past `as_of` the scanner results are not bound by `as_of`.

## Running tests

```bash
python tasks.py test-selection
```
