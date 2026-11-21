# Paper-trading benchmark

**English** | [简体中文](README.zh-CN.md)

> [!IMPORTANT]
> These are **paper-trading** results from IBKR paper accounts, not real money. Fills are real paper fills, but paper trading ignores market impact and can fill orders a live account would not. Past results say nothing about future ones. Not investment advice.

<sub>Updated 2026-11-21 · data through 2026-11-20</sub>

<p align="center"><img src="equity.svg" alt="Cumulative paper-trading return of each pipeline against its benchmark" width="880"></p>

## Summary

| Pipeline | Model | Since | Return | Benchmark | Excess | Max drawdown | Sharpe | LLM cost |
|:--|:--|--:|--:|--:|--:|--:|--:|--:|
| **arena_claude** | claude-haiku-5.5 | 2026-10-16 | -6.49% | SPY -9.10% | +2.61% | -6.76% | -5.18 | $2.99 |
| **arena_deepseek** | deepseek-v4.1-flash | 2026-10-16 | -6.10% | SPY -9.10% | +3.00% | -6.70% | -5.18 | $4.89 |
| **arena_glm** | glm-5.3-flashx | 2026-10-16 | -5.75% | SPY -9.10% | +3.35% | -6.04% | -5.20 | $13.61 |
| **arena_gpt** | gpt-6-luna | 2026-10-16 | -3.40% | SPY -9.10% | +5.70% | -4.15% | -3.55 | — |
| **arena_qwen** | qwen3.8-omni-flash | 2026-10-16 | -4.44% | SPY -9.10% | +4.66% | -4.65% | -4.39 | $6.30 |
| **arena_solo_claude** | claude-haiku-5.5 | 2026-10-16 | -5.37% | SPY -9.10% | +3.73% | -6.71% | -3.98 | $0.83 |
| **arena_solo_deepseek** | deepseek-v4.1-flash | 2026-10-16 | -3.96% | SPY -9.10% | +5.14% | -4.95% | -3.32 | $1.21 |
| **arena_solo_glm** | glm-5.3-flashx | 2026-10-16 | -4.37% | SPY -9.10% | +4.73% | -6.52% | -3.07 | $4.41 |
| **arena_solo_gpt** | gpt-6-luna | 2026-10-16 | -2.26% | SPY -9.10% | +6.84% | -3.38% | -3.53 | — |
| **arena_solo_qwen** | qwen3.8-omni-flash | 2026-10-16 | -0.30% | SPY -9.10% | +8.80% | -1.16% | -1.06 | $0.90 |
| **demo_all_modules** | deepseek-chat | 2026-10-07 | -9.25% | SPY -10.73% | +1.48% | -9.83% | -7.09 | — |

## Pipelines

### arena_claude

| | |
|:--|--:|
| Models | `anthropic/claude-haiku-5.5` |
| Mode | paper |
| Sessions | 25 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 15:10 UTC |
| Net asset value | 93,514.26 (-6.49%) |
| Fills (buys / sells) | 26 (10 / 16) |
| Sells at a profit | 0.00% |
| Realised P&L | -5,193.95 |
| Commissions | 26.27 |
| Open positions | 3 |
| Invested | 24.58% |
| Volatility (annualised) | 12.87% |
| CAGR | — |
| Benchmark max drawdown | -10.26% |
| LLM calls | 3218 |
| LLM tokens (in / out / cache read) | 17.49M / 2.49M / 0 |
| LLM cost (total / last 7 days) | $2.99 / $0.49 |

### arena_deepseek

| | |
|:--|--:|
| Models | `deepseek/deepseek-v4.1-flash` |
| Mode | paper |
| Sessions | 25 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 13:50 UTC |
| Net asset value | 93,900.02 (-6.10%) |
| Fills (buys / sells) | 68 (30 / 38) |
| Sells at a profit | 10.53% |
| Realised P&L | -4,854.51 |
| Commissions | 69.50 |
| Open positions | 4 |
| Invested | 42.85% |
| Volatility (annualised) | 12.09% |
| CAGR | — |
| Benchmark max drawdown | -10.26% |
| LLM calls | 4085 |
| LLM tokens (in / out / cache read) | 16.36M / 4.16M / 431.5k |
| LLM cost (total / last 7 days) | $4.89 / $0.81 |

### arena_glm

| | |
|:--|--:|
| Models | `z-ai/glm-5.3-flashx` |
| Mode | paper |
| Sessions | 25 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:30 UTC |
| Net asset value | 94,246.52 (-5.75%) |
| Fills (buys / sells) | 64 (29 / 35) |
| Sells at a profit | 0.00% |
| Realised P&L | -5,435.16 |
| Commissions | 65.61 |
| Open positions | 8 |
| Invested | 78.54% |
| Volatility (annualised) | 11.35% |
| CAGR | — |
| Benchmark max drawdown | -10.26% |
| LLM calls | 3894 |
| LLM tokens (in / out / cache read) | 16.28M / 6.51M / 1.97M |
| LLM cost (total / last 7 days) | $13.61 / $3.45 |

### arena_gpt

| | |
|:--|--:|
| Models | `openai/gpt-6-luna` |
| Mode | paper |
| Sessions | 25 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:50 UTC |
| Net asset value | 96,597.09 (-3.40%) |
| Fills (buys / sells) | 27 (8 / 19) |
| Sells at a profit | 10.53% |
| Realised P&L | -3,438.49 |
| Commissions | 27.12 |
| Open positions | 1 |
| Invested | 11.05% |
| Volatility (annualised) | 9.70% |
| CAGR | — |
| Benchmark max drawdown | -10.26% |
| LLM calls | 3469 |
| LLM tokens (in / out / cache read) | 12.55M / 1.48M / 17.2k |
| LLM cost (total / last 7 days) | — / $0.32 |

### arena_qwen

| | |
|:--|--:|
| Models | `qwen/qwen3.8-omni-flash` |
| Mode | paper |
| Sessions | 25 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:10 UTC |
| Net asset value | 95,560.66 (-4.44%) |
| Fills (buys / sells) | 34 (9 / 25) |
| Sells at a profit | 8.00% |
| Realised P&L | -4,439.34 |
| Commissions | 35.54 |
| Open positions | 0 |
| Invested | 0.00% |
| Volatility (annualised) | 10.31% |
| CAGR | — |
| Benchmark max drawdown | -10.26% |
| LLM calls | 3570 |
| LLM tokens (in / out / cache read) | 15.97M / 8.46M / 553.7k |
| LLM cost (total / last 7 days) | $6.30 / $0.80 |

### arena_solo_claude

| | |
|:--|--:|
| Models | `anthropic/claude-haiku-5.5` |
| Mode | paper |
| Sessions | 25 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 15:20 UTC |
| Net asset value | 94,627.65 (-5.37%) |
| Fills (buys / sells) | 40 (27 / 13) |
| Sells at a profit | 0.00% |
| Realised P&L | -3,779.47 |
| Commissions | 40.70 |
| Open positions | 7 |
| Invested | 89.05% |
| Volatility (annualised) | 13.75% |
| CAGR | — |
| Benchmark max drawdown | -10.26% |
| LLM calls | 1071 |
| LLM tokens (in / out / cache read) | 4.44M / 767.6k / 0 |
| LLM cost (total / last 7 days) | $0.83 / $0.18 |

### arena_solo_deepseek

| | |
|:--|--:|
| Models | `deepseek/deepseek-v4.1-flash` |
| Mode | paper |
| Sessions | 25 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:00 UTC |
| Net asset value | 96,042.14 (-3.96%) |
| Fills (buys / sells) | 38 (18 / 20) |
| Sells at a profit | 15.00% |
| Realised P&L | -4,110.49 |
| Commissions | 37.17 |
| Open positions | 5 |
| Invested | 49.45% |
| Volatility (annualised) | 12.05% |
| CAGR | — |
| Benchmark max drawdown | -10.26% |
| LLM calls | 1116 |
| LLM tokens (in / out / cache read) | 3.42M / 1.19M / 109.7k |
| LLM cost (total / last 7 days) | $1.21 / $0.28 |

### arena_solo_glm

| | |
|:--|--:|
| Models | `z-ai/glm-5.3-flashx` |
| Mode | paper |
| Sessions | 25 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:40 UTC |
| Net asset value | 95,630.75 (-4.37%) |
| Fills (buys / sells) | 58 (36 / 22) |
| Sells at a profit | 0.00% |
| Realised P&L | -4,338.98 |
| Commissions | 54.59 |
| Open positions | 10 |
| Invested | 88.31% |
| Volatility (annualised) | 14.34% |
| CAGR | — |
| Benchmark max drawdown | -10.26% |
| LLM calls | 1506 |
| LLM tokens (in / out / cache read) | 4.71M / 2.26M / 563.3k |
| LLM cost (total / last 7 days) | $4.41 / $1.04 |

### arena_solo_gpt

| | |
|:--|--:|
| Models | `openai/gpt-6-luna` |
| Mode | paper |
| Sessions | 25 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 15:00 UTC |
| Net asset value | 97,743.12 (-2.26%) |
| Fills (buys / sells) | 17 (6 / 11) |
| Sells at a profit | 0.00% |
| Realised P&L | -923.33 |
| Commissions | 17.29 |
| Open positions | 5 |
| Invested | 51.39% |
| Volatility (annualised) | 6.47% |
| CAGR | — |
| Benchmark max drawdown | -10.26% |
| LLM calls | 1202 |
| LLM tokens (in / out / cache read) | 3.48M / 473.9k / 0 |
| LLM cost (total / last 7 days) | — / $0.09 |

### arena_solo_qwen

| | |
|:--|--:|
| Models | `qwen/qwen3.8-omni-flash` |
| Mode | paper |
| Sessions | 25 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:20 UTC |
| Net asset value | 99,697.59 (-0.30%) |
| Fills (buys / sells) | 6 (4 / 2) |
| Sells at a profit | 0.00% |
| Realised P&L | -112.48 |
| Commissions | 6.14 |
| Open positions | 4 |
| Invested | 41.09% |
| Volatility (annualised) | 2.85% |
| CAGR | — |
| Benchmark max drawdown | -10.26% |
| LLM calls | 625 |
| LLM tokens (in / out / cache read) | 2.22M / 1.23M / 44.8k |
| LLM cost (total / last 7 days) | $0.90 / $0.29 |

### demo_all_modules

| | |
|:--|--:|
| Models | `deepseek-chat` |
| Mode | paper |
| Sessions | 32 |
| Starting capital | 10,000.00 |
| First paper/live run | 2026-10-08 13:40 UTC |
| Net asset value | 9,074.84 (-9.25%) |
| Fills (buys / sells) | 49 (20 / 29) |
| Sells at a profit | 0.00% |
| Realised P&L | -884.99 |
| Commissions | 45.54 |
| Open positions | 4 |
| Invested | 44.69% |
| Volatility (annualised) | 10.69% |
| CAGR | — |
| Benchmark max drawdown | -10.89% |
| LLM calls | 6652 |
| LLM tokens (in / out / cache read) | 25.79M / 2.09M / 1.65M |
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
