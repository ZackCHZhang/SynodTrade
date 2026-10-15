# Paper-trading benchmark

**English** | [简体中文](README.zh-CN.md)

> [!IMPORTANT]
> These are **paper-trading** results from IBKR paper accounts, not real money. Fills are real paper fills, but paper trading ignores market impact and can fill orders a live account would not. Past results say nothing about future ones. Not investment advice.

<sub>Updated 2026-10-14 · data through 2026-10-14</sub>

<p align="center"><img src="equity.svg" alt="Cumulative paper-trading return of each pipeline against its benchmark" width="880"></p>

## Summary

| Pipeline | Model | Since | Return | Benchmark | Excess | Max drawdown | Sharpe | LLM cost |
|:--|:--|--:|--:|--:|--:|--:|--:|--:|
| **demo_all_modules** | deepseek-chat | 2026-10-07 | -0.53% | SPY -1.02% | +0.50% | -1.16% | — | — |

## Pipelines

### demo_all_modules

| | |
|:--|--:|
| Models | `deepseek-chat` |
| Mode | paper |
| Sessions | 5 |
| Starting capital | 10,000.00 |
| First paper/live run | 2026-10-08 13:40 UTC |
| Net asset value | 9,947.44 (-0.53%) |
| Fills (buys / sells) | 14 (12 / 2) |
| Sells at a profit | 0.00% |
| Realised P&L | -12.18 |
| Commissions | 13.64 |
| Open positions | 8 |
| Invested | 73.30% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -1.20% |
| LLM calls | — |
| LLM tokens (in / out / cache read) | — |
| LLM cost (total / last 7 days) | — / — |

## Methodology

- Each pipeline trades a virtual sub-account that starts at its `budget.max_capital` on the day of its first paper or live run; the base day (0%) is the last session before it.
- Every session, the pipeline's fills up to that day are booked with the same arithmetic as the trading ledger (commissions included) and open positions are valued at that day's close (the last known close when a symbol has no bar).
- The benchmark is the pipeline's `benchmark` symbol (SPY by default), indexed to the same base day. Excess = return − benchmark return.
- Sharpe and volatility are annualised from daily returns (252 sessions, risk-free rate 0) and need at least 20 sessions; CAGR needs at least 60. A dash means not enough data.
- LLM cost is the pipeline's recorded token usage (every attempt, including retries) priced at the list prices in `configs/llm_providers.yaml`; a dash means a model has no price. It is an estimate: providers may bill differently (routing, discounts, time of day).
- Dry-run and offline runs are never included.

## Reproduce

Generated from the trading database with the command below. The daily series of every pipeline is in [`data.json`](data.json).

```bash
poetry run quant benchmark
```
