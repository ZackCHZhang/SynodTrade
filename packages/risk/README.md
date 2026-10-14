# quant-risk

**English** | [简体中文](README.zh-CN.md)

Risk control has two layers: deterministic hard rules and risk agents (LLM, which can only reduce risk). Depends on `quant-core` and `quant-database`.

## Flow (`risk` stage)

1. **Load the portfolio state** (as of `as_of`):
   - Cash and positions in the pipeline's virtual sub-ledger, and cash reserved by open buy orders.
   - Each symbol's current price: a quote from the last `max_quote_age_minutes` if there is one, otherwise the last completed bar's close.
   - NAV.
   - Today's and this week's return, from the sub-ledger at the start of the day (or Monday) and the prices then.
   - Orders placed today, in total and per symbol.
   - The kill-switch database flag.
   - Whether the exchange is open (`exchange_calendars`, XNYS by default, holidays and half days included).
   - Spendable cash, also capped by the real account's available funds when the `account` service is configured.
2. **Layer 1: hard rules**, evaluated symbol by symbol, **sells before buys**, buys by signal strength. Each approved order's cash, exposure and trade count are deducted from the state, so several buys in one run cannot jointly break a limit.
3. **Layer 2: risk agents** review only symbols the rules passed and that are not HOLD; all calls run concurrently.
4. **Combine**: `most_conservative` (default) takes the most conservative result, `median` the conservative median.
5. **Write**: three kinds of records per symbol, all in `risk_assessments`:
   - `source="rules"`: the rules' verdict and every rule hit;
   - one per risk agent;
   - `source="final"`: the final verdict.

   `PipelineContext.risk_verdicts[symbol]` holds the final verdict; the trading stage acts on nothing else.

## Layer 1: hard rules (`configs/risk/<name>.yaml`)

All ratios are relative to **this pipeline's NAV** (its virtual sub-ledger), not the whole IBKR account.

**Gates** (independent of order size):

| Rule | Effect |
|---|---|
| `kill_switch` (config) or the database flag `kill_switch` | everything becomes HOLD (buys and sells rejected) |
| Whitelist (`whitelist`, empty = no limit), blacklist (`blacklist`) | everything becomes HOLD |
| Trading hours (`trading_hours.enabled`, outside regular hours) | everything becomes HOLD |
| No price | everything becomes HOLD |
| Trades today ≥ `max_trades_per_day` | everything becomes HOLD |
| `one_order_per_symbol_per_day`: the symbol already traded today | everything becomes HOLD |
| Loss today ≥ `max_daily_loss_pct` or this week ≥ `max_weekly_loss_pct` | **buys blocked only**, sells still pass |
| Liquidity: spread > `max_spread_bps`; 20-day average volume < `min_avg_volume`; no quote while `require_quote` | **buys blocked only** |

**Size rules** check the actual quantity and value computed by core's sizing. If a tier fails, the next tier toward HOLD is tried: STRONG_BUY → BUY → HOLD.

| Rule | Applies to |
|---|---|
| Order value > `max_order_notional` | buys and sells |
| Symbol weight after the buy > `max_position_pct` | buys |
| Gross exposure after the buy > `max_gross_exposure_pct` | buys |
| Cash after the buy < `min_cash_pct` | buys |

**Defaults in code** (`RiskRulesConfig`): `max_position_pct` 0.20, `max_gross_exposure_pct` 0.90, `min_cash_pct` 0.10, `max_daily_loss_pct` 0.03, `max_weekly_loss_pct` 0.06, `max_trades_per_day` 4, `max_order_notional` unlimited, `one_order_per_symbol_per_day` true, `max_spread_bps` 50, `min_avg_volume` 100000, `require_quote` false, `trading_hours` on (XNYS). The bundled `default.yaml` additionally sets `max_order_notional` to 2000; `etf.yaml` allows larger positions and exposure and adds a whitelist.

**Edge cases**:
- Exactly at a limit passes.
- A loss exactly at its threshold triggers the circuit breaker.
- Sale proceeds are not credited to spendable cash within the run, since a sell may fill after the buys.
- An order that sizes to less than one share only records a note, not a violation; the trading stage skips it.

The hard rules have **no** volatility-based sizing, transaction-cost check, sector / correlation concentration limit or earnings blackout.

## Layer 2: risk agents

- What they see:
  - the original decision and the action after the rules;
  - the proposed order (side, quantity, value) and portfolio state (cash, exposure, today's / this week's return...);
  - 6 market indicators (computed by `quant_core.indicators`): last close, 1-day return, 20-day return, 20-day volatility, distance from the 52-week high, RSI 14;
  - each decision agent's action, confidence and reasoning, sentiment summaries and the rule hits.
- **"Reduce only" is enforced in code**: every call is validated against an output model bound to the proposed action (`bounded_output`). An action more aggressive than proposed, or in the opposite direction, fails validation: the error is fed back for a retry, and if it still fails the failure policy applies. `RiskVerdict` validates once more afterwards.
- Failure policy `on_agent_failure`: `reject` by default (no trade when the LLM is unavailable — fail-safe); `approve` lets through whatever the hard rules passed.
- The model is chosen at instantiation: `model` in the pipeline's agent reference, or `RiskAgent(..., model=...)` in code.
- The repository ships 21 risk agent configs (`role: risk`), e.g. `conservative_risk_officer`, `volatility_position_sizer`, `earnings_event_risk`, `gap_risk_monitor`, all using the template `configs/agents/prompts/risk_v1.j2`. Some of their `instructions` ask for ATR, earnings dates, historical gaps or correlations, but risk agents only see the data listed above; the model can only infer from it.

## Configuration

```yaml
- type: risk
  rules: default               # configs/risk/default.yaml
  agents:
    - { agent: conservative_risk_officer, count: 1, model: { provider: anthropic, name: claude-opus-5 } }
  combine: most_conservative   # most_conservative | median
  on_agent_failure: reject     # reject | approve
  max_quote_age_minutes: 30
  timeframe: 1d                # bar timeframe to read, default 1d
```

Services needed by the stage factory `build_risk_stage(config, services)`:
- Required: `repos`, `config_store`, `llm`, `pipeline` (`PipelineConfig`, for budget and sizing).
- Optional: `account` (`AccountConfig`, caps spendable cash by the real account's available funds), `market_clock` (`MarketClock`; default `ExchangeCalendarClock` with the calendar from the rules config; tests or offline runs can use `AlwaysOpenClock`).

## Running tests

```bash
python tasks.py test-risk
```
