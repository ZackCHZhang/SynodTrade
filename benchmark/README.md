# Paper-trading benchmark

**English** | [简体中文](README.zh-CN.md)

> [!IMPORTANT]
> These are **paper-trading** results from IBKR paper accounts, not real money. Fills are real paper fills, but paper trading ignores market impact and can fill orders a live account would not. Past results say nothing about future ones. Not investment advice.

<sub>Updated 2026-11-14 · data through 2026-11-13</sub>

<p align="center"><img src="equity.svg" alt="Cumulative paper-trading return of each pipeline against its benchmark" width="880"></p>

## Summary

| Pipeline | Model | Since | Return | Benchmark | Excess | Max drawdown | Sharpe | LLM cost |
|:--|:--|--:|--:|--:|--:|--:|--:|--:|
| **arena_claude** | claude-haiku-5.5 | 2026-10-16 | -5.14% | SPY -1.28% | -3.86% | -5.49% | -4.57 | $2.50 |
| **arena_deepseek** | deepseek-v4.1-flash | 2026-10-16 | -3.32% | SPY -1.28% | -2.04% | -4.79% | -3.24 | $4.08 |
| **arena_glm** | glm-5.3-flashx | 2026-10-16 | -2.49% | SPY -1.28% | -1.21% | -3.83% | -2.75 | $10.16 |
| **arena_gpt** | gpt-6-luna | 2026-10-16 | -3.02% | SPY -1.28% | -1.74% | -4.15% | -3.49 | — |
| **arena_qwen** | qwen3.8-omni-flash | 2026-10-16 | -4.44% | SPY -1.28% | -3.16% | -4.65% | -4.93 | $5.50 |
| **arena_solo_claude** | claude-haiku-5.5 | 2026-10-16 | -1.40% | SPY -1.28% | -0.12% | -4.36% | -1.25 | $0.65 |
| **arena_solo_deepseek** | deepseek-v4.1-flash | 2026-10-16 | -0.46% | SPY -1.28% | +0.82% | -3.38% | -0.47 | $0.93 |
| **arena_solo_glm** | glm-5.3-flashx | 2026-10-16 | -1.25% | SPY -1.28% | +0.03% | -4.82% | -1.03 | $3.37 |
| **arena_solo_gpt** | gpt-6-luna | 2026-10-16 | +0.00% | SPY -1.28% | +1.28% | -2.30% | 0.03 | — |
| **arena_solo_qwen** | qwen3.8-omni-flash | 2026-10-16 | +0.86% | SPY -1.28% | +2.14% | -0.17% | 5.03 | $0.61 |
| **demo_all_modules** | deepseek-chat | 2026-10-07 | -6.76% | SPY -3.05% | -3.70% | -8.25% | -5.66 | — |

## Pipelines

### arena_claude

| | |
|:--|--:|
| Models | `anthropic/claude-haiku-5.5` |
| Mode | paper |
| Sessions | 20 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 15:10 UTC |
| Net asset value | 94,861.11 (-5.14%) |
| Fills (buys / sells) | 26 (10 / 16) |
| Sells at a profit | 0.00% |
| Realised P&L | -5,193.95 |
| Commissions | 26.27 |
| Open positions | 3 |
| Invested | 25.65% |
| Volatility (annualised) | 14.31% |
| CAGR | — |
| Benchmark max drawdown | -5.19% |
| LLM calls | 2721 |
| LLM tokens (in / out / cache read) | 14.55M / 2.09M / 0 |
| LLM cost (total / last 7 days) | $2.50 / $0.49 |

### arena_deepseek

| | |
|:--|--:|
| Models | `deepseek/deepseek-v4.1-flash` |
| Mode | paper |
| Sessions | 20 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 13:50 UTC |
| Net asset value | 96,679.28 (-3.32%) |
| Fills (buys / sells) | 65 (28 / 37) |
| Sells at a profit | 10.81% |
| Realised P&L | -4,139.54 |
| Commissions | 66.12 |
| Open positions | 4 |
| Invested | 49.50% |
| Volatility (annualised) | 12.89% |
| CAGR | — |
| Benchmark max drawdown | -5.19% |
| LLM calls | 3467 |
| LLM tokens (in / out / cache read) | 13.68M / 3.48M / 405.4k |
| LLM cost (total / last 7 days) | $4.08 / $0.54 |

### arena_glm

| | |
|:--|--:|
| Models | `z-ai/glm-5.3-flashx` |
| Mode | paper |
| Sessions | 20 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:30 UTC |
| Net asset value | 97,511.10 (-2.49%) |
| Fills (buys / sells) | 59 (25 / 34) |
| Sells at a profit | 0.00% |
| Realised P&L | -5,290.89 |
| Commissions | 60.51 |
| Open positions | 6 |
| Invested | 66.98% |
| Volatility (annualised) | 11.30% |
| CAGR | — |
| Benchmark max drawdown | -5.19% |
| LLM calls | 2901 |
| LLM tokens (in / out / cache read) | 12.08M / 4.86M / 1.37M |
| LLM cost (total / last 7 days) | $10.16 / $2.30 |

### arena_gpt

| | |
|:--|--:|
| Models | `openai/gpt-6-luna` |
| Mode | paper |
| Sessions | 20 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:50 UTC |
| Net asset value | 96,984.90 (-3.02%) |
| Fills (buys / sells) | 27 (8 / 19) |
| Sells at a profit | 10.53% |
| Realised P&L | -3,438.49 |
| Commissions | 27.12 |
| Open positions | 1 |
| Invested | 11.41% |
| Volatility (annualised) | 10.88% |
| CAGR | — |
| Benchmark max drawdown | -5.19% |
| LLM calls | 2974 |
| LLM tokens (in / out / cache read) | 10.47M / 1.25M / 0 |
| LLM cost (total / last 7 days) | — / $0.34 |

### arena_qwen

| | |
|:--|--:|
| Models | `qwen/qwen3.8-omni-flash` |
| Mode | paper |
| Sessions | 20 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:10 UTC |
| Net asset value | 95,560.66 (-4.44%) |
| Fills (buys / sells) | 34 (9 / 25) |
| Sells at a profit | 8.00% |
| Realised P&L | -4,439.34 |
| Commissions | 35.54 |
| Open positions | 0 |
| Invested | 0.00% |
| Volatility (annualised) | 11.47% |
| CAGR | — |
| Benchmark max drawdown | -5.19% |
| LLM calls | 3108 |
| LLM tokens (in / out / cache read) | 13.61M / 7.49M / 455.2k |
| LLM cost (total / last 7 days) | $5.50 / $1.12 |

### arena_solo_claude

| | |
|:--|--:|
| Models | `anthropic/claude-haiku-5.5` |
| Mode | paper |
| Sessions | 20 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 15:20 UTC |
| Net asset value | 98,598.31 (-1.40%) |
| Fills (buys / sells) | 34 (21 / 13) |
| Sells at a profit | 0.00% |
| Realised P&L | -3,779.47 |
| Commissions | 34.70 |
| Open positions | 7 |
| Invested | 78.12% |
| Volatility (annualised) | 13.50% |
| CAGR | — |
| Benchmark max drawdown | -5.19% |
| LLM calls | 837 |
| LLM tokens (in / out / cache read) | 3.44M / 603.9k / 0 |
| LLM cost (total / last 7 days) | $0.65 / $0.13 |

### arena_solo_deepseek

| | |
|:--|--:|
| Models | `deepseek/deepseek-v4.1-flash` |
| Mode | paper |
| Sessions | 20 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:00 UTC |
| Net asset value | 99,544.88 (-0.46%) |
| Fills (buys / sells) | 28 (16 / 12) |
| Sells at a profit | 8.33% |
| Realised P&L | -2,694.51 |
| Commissions | 28.68 |
| Open positions | 7 |
| Invested | 74.49% |
| Volatility (annualised) | 11.05% |
| CAGR | — |
| Benchmark max drawdown | -5.19% |
| LLM calls | 858 |
| LLM tokens (in / out / cache read) | 2.61M / 911.6k / 86.9k |
| LLM cost (total / last 7 days) | $0.93 / $0.26 |

### arena_solo_glm

| | |
|:--|--:|
| Models | `z-ai/glm-5.3-flashx` |
| Mode | paper |
| Sessions | 20 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:40 UTC |
| Net asset value | 98,754.44 (-1.25%) |
| Fills (buys / sells) | 50 (30 / 20) |
| Sells at a profit | 0.00% |
| Realised P&L | -4,030.02 |
| Commissions | 46.49 |
| Open positions | 9 |
| Invested | 82.67% |
| Volatility (annualised) | 14.32% |
| CAGR | — |
| Benchmark max drawdown | -5.19% |
| LLM calls | 1153 |
| LLM tokens (in / out / cache read) | 3.58M / 1.73M / 397.8k |
| LLM cost (total / last 7 days) | $3.37 / $0.88 |

### arena_solo_gpt

| | |
|:--|--:|
| Models | `openai/gpt-6-luna` |
| Mode | paper |
| Sessions | 20 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 15:00 UTC |
| Net asset value | 100,000.66 (+0.00%) |
| Fills (buys / sells) | 15 (5 / 10) |
| Sells at a profit | 0.00% |
| Realised P&L | -913.99 |
| Commissions | 15.28 |
| Open positions | 5 |
| Invested | 44.80% |
| Volatility (annualised) | 6.30% |
| CAGR | — |
| Benchmark max drawdown | -5.19% |
| LLM calls | 1036 |
| LLM tokens (in / out / cache read) | 2.95M / 405.4k / 0 |
| LLM cost (total / last 7 days) | — / $0.14 |

### arena_solo_qwen

| | |
|:--|--:|
| Models | `qwen/qwen3.8-omni-flash` |
| Mode | paper |
| Sessions | 20 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:20 UTC |
| Net asset value | 100,863.27 (+0.86%) |
| Fills (buys / sells) | 4 (3 / 1) |
| Sells at a profit | 0.00% |
| Realised P&L | -17.92 |
| Commissions | 4.09 |
| Open positions | 3 |
| Invested | 34.82% |
| Volatility (annualised) | 2.16% |
| CAGR | — |
| Benchmark max drawdown | -5.19% |
| LLM calls | 422 |
| LLM tokens (in / out / cache read) | 1.46M / 851.2k / 44.8k |
| LLM cost (total / last 7 days) | $0.61 / $0.36 |

### demo_all_modules

| | |
|:--|--:|
| Models | `deepseek-chat` |
| Mode | paper |
| Sessions | 27 |
| Starting capital | 10,000.00 |
| First paper/live run | 2026-10-08 13:40 UTC |
| Net asset value | 9,324.19 (-6.76%) |
| Fills (buys / sells) | 46 (19 / 27) |
| Sells at a profit | 0.00% |
| Realised P&L | -790.13 |
| Commissions | 42.52 |
| Open positions | 5 |
| Invested | 49.94% |
| Volatility (annualised) | 11.40% |
| CAGR | — |
| Benchmark max drawdown | -5.85% |
| LLM calls | 5775 |
| LLM tokens (in / out / cache read) | 22.26M / 1.83M / 1.43M |
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
poetry run synodtrade benchmark
```
