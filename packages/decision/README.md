# synodtrade-decision

**English** | [简体中文](README.zh-CN.md)

Decision: builds each symbol's decision context, runs the decision agents and aggregates their votes. Technical indicators are computed by `synodtrade_core.indicators` (shared with risk and selection); this package only re-exports them. Depends on `synodtrade-core` and `synodtrade-database`.

## Flow (`decision` stage)

1. Reads the pipeline's **virtual sub-ledger** (cash, positions and reserved cash as of `as_of`) and values it at the latest closes to get the pipeline's NAV.
2. For each symbol:
   - Reads the latest `bars_lookback` **completed** bars. With fewer than `min_bars` the result is HOLD (`method=insufficient_data`) without asking any agent.
   - Computes the technical indicators in code (`compute_indicators`).
   - Reads this run's sentiment results (failed analyses excluded).
   - Reads the last `history_limit` final decisions and computes in code how the price moved since each one; the price at decision time is the close of the last bar completed before it.
3. Every agent instance calls the LLM once per symbol; all calls run concurrently and produce `Decision`s.
4. The aggregator combines a symbol's decisions into an `AggregatedDecision`.
5. Results go to the `decisions` and `aggregated_decisions` tables and into `PipelineContext`; agent instances are registered in `agent_instances`.

## What agents see

All computed in code; the LLM does no arithmetic:

- Technical indicators (see `packages/core/README.md`): returns over 1/5/20/60/120/250 days; annualised 20- and 60-day volatility; SMA 20/50/200 and distances; RSI 14; MACD(12,26,9); 52-week high / low and distances; 1-year maximum drawdown; volume relative to the previous 20-day average. An indicator without enough history is omitted from the prompt.
- The latest `recent_bars_in_prompt` bars (OHLCV).
- The pipeline's available cash and NAV, and the position in the symbol (quantity, cost, market value, unrealised P&L, weight).
- This run's sentiment summaries.
- Past final decisions and the price move since.

Fundamentals, earnings, macro data and ATR are **not provided**. Some decision agents' `instructions` mention such data (e.g. `earnings_drift` asks for EPS surprises, `garp_investor` for PEG, `macro_regime` for rates and the yield curve); the model can only infer it from the information above.

## Data references in the prompt

Every piece of data carries an id: `ind:rsi_14`, `bar:2026-09-23`, `pos:AAPL`, `sent:<uuid>`, `hist:<uuid>`. Agents cite them in `referenced_data_ids`; ids that were not in this prompt are dropped with a warning, so the data behind every decision is traceable. The prompt also tells the model:

- The exact meaning of the five actions: buys use 15% / 30% of available cash, sells 15% / 30% of the position.
- No shorting; a sell without a position is ignored.
- Later risk controls can only reduce risk, never enlarge a position.

## Aggregation (`aggregation`)

Votes below `min_confidence` (default 0) and fallback votes of failed agents count as HOLD first.

| Method | Rule |
|---|---|
| `weighted_vote` (default) | Weighted average of the five tiers' values with weight = agent weight × confidence, mapped back to the nearest tier; ties go toward HOLD |
| `majority` | One direction (buy / hold / sell) needs **strictly more than half** of the total agent weight; the tier is the weighted average of that direction's votes, ties toward HOLD. Otherwise HOLD |
| `unanimous` | All votes in one direction and none HOLD; the **most conservative** of them wins. Otherwise HOLD |

`AggregatedDecision.votes` keeps every vote's **original** action, confidence and weight; `method` records the method and thresholds used.

## Configuration

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

The repository ships 21 decision agent configs (files with `role: decision` in `configs/agents/`, e.g. `value_investor`, `trend_follower`, `pullback_buyer`, `mean_reversion_swing`, `breakout_trader`). All use the same implementation `DecisionAgent` (`decision` in the `synodtrade.agents` entry point) and the same template `configs/agents/prompts/decision_v1.j2`; they differ only in persona and `params.instructions`. The model is chosen in the pipeline's agent reference.

Services needed by the stage factory `build_decision_stage(config, services)`: `repos`, `config_store`, `llm` (`LLMClientPool`), `pipeline` (`PipelineConfig`; its `budget.max_capital` is used for the sub-ledger).

## Running tests

```bash
python tasks.py test-decision
```
