# Paper-trading benchmark

**English** | [简体中文](README.zh-CN.md)

> [!IMPORTANT]
> These are **paper-trading** results from IBKR paper accounts, not real money. Fills are real paper fills, but paper trading ignores market impact and can fill orders a live account would not. Past results say nothing about future ones. Not investment advice.

<sub>Updated 2026-10-23 · data through 2026-10-23</sub>

<p align="center"><img src="equity.svg" alt="Cumulative paper-trading return of each pipeline against its benchmark" width="880"></p>

## Summary

| Pipeline | Model | Since | Return | Benchmark | Excess | Max drawdown | Sharpe | LLM cost |
|:--|:--|--:|--:|--:|--:|--:|--:|--:|
| **arena_claude** | claude-haiku-5.5 | 2026-10-16 | -0.24% | SPY -0.39% | +0.15% | -0.90% | — | $0.46 |
| **arena_deepseek** | deepseek-v4.1-flash | 2026-10-16 | -0.03% | SPY -0.39% | +0.36% | -0.74% | — | $0.96 |
| **arena_glm** | glm-5.3-flashx | 2026-10-16 | -1.13% | SPY -0.39% | -0.74% | -1.13% | — | $2.33 |
| **arena_gpt** | gpt-6-luna | 2026-10-16 | +0.46% | SPY -0.39% | +0.85% | -0.13% | — | — |
| **arena_qwen** | qwen3.8-omni-flash | 2026-10-16 | +0.05% | SPY -0.39% | +0.44% | -0.45% | — | $0.88 |
| **arena_solo_claude** | claude-haiku-5.5 | 2026-10-16 | +0.12% | SPY -0.39% | +0.50% | -0.31% | — | $0.14 |
| **arena_solo_deepseek** | deepseek-v4.1-flash | 2026-10-16 | +0.13% | SPY -0.39% | +0.52% | -0.49% | — | $0.17 |
| **arena_solo_glm** | glm-5.3-flashx | 2026-10-16 | +0.41% | SPY -0.39% | +0.80% | -0.30% | — | $0.75 |
| **arena_solo_gpt** | gpt-6-luna | 2026-10-16 | +0.60% | SPY -0.39% | +0.99% | -0.00% | — | — |
| **arena_solo_qwen** | qwen3.8-omni-flash | 2026-10-16 | +0.00% | SPY -0.39% | +0.39% | +0.00% | — | $0.06 |
| **demo_all_modules** | deepseek-chat | 2026-10-07 | -4.10% | SPY -2.18% | -1.92% | -4.72% | — | — |

## Pipelines

### arena_claude

| | |
|:--|--:|
| Models | `anthropic/claude-haiku-5.5` |
| Mode | paper |
| Sessions | 5 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 15:10 UTC |
| Net asset value | 99,762.19 (-0.24%) |
| Fills (buys / sells) | 5 (5 / 0) |
| Sells at a profit | — |
| Realised P&L | 0.00 |
| Commissions | 5.00 |
| Open positions | 4 |
| Invested | 54.56% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -1.66% |
| LLM calls | 491 |
| LLM tokens (in / out / cache read) | 2.66M / 381.9k / 0 |
| LLM cost (total / last 7 days) | $0.46 / $0.46 |

### arena_deepseek

| | |
|:--|--:|
| Models | `deepseek/deepseek-v4.1-flash` |
| Mode | paper |
| Sessions | 5 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 13:50 UTC |
| Net asset value | 99,971.58 (-0.03%) |
| Fills (buys / sells) | 17 (15 / 2) |
| Sells at a profit | 0.00% |
| Realised P&L | -75.35 |
| Commissions | 17.03 |
| Open positions | 10 |
| Invested | 88.51% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -1.66% |
| LLM calls | 829 |
| LLM tokens (in / out / cache read) | 3.22M / 822.2k / 105.6k |
| LLM cost (total / last 7 days) | $0.96 / $0.96 |

### arena_glm

| | |
|:--|--:|
| Models | `z-ai/glm-5.3-flashx` |
| Mode | paper |
| Sessions | 5 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:30 UTC |
| Net asset value | 98,873.55 (-1.13%) |
| Fills (buys / sells) | 16 (10 / 6) |
| Sells at a profit | 0.00% |
| Realised P&L | -435.73 |
| Commissions | 16.16 |
| Open positions | 7 |
| Invested | 72.10% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -1.66% |
| LLM calls | 671 |
| LLM tokens (in / out / cache read) | 2.73M / 1.10M / 224.8k |
| LLM cost (total / last 7 days) | $2.33 / $2.33 |

### arena_gpt

| | |
|:--|--:|
| Models | `openai/gpt-6-luna` |
| Mode | paper |
| Sessions | 5 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:50 UTC |
| Net asset value | 100,463.18 (+0.46%) |
| Fills (buys / sells) | 6 (6 / 0) |
| Sells at a profit | — |
| Realised P&L | 0.00 |
| Commissions | 5.00 |
| Open positions | 5 |
| Invested | 55.32% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -1.66% |
| LLM calls | 710 |
| LLM tokens (in / out / cache read) | 1.83M / 237.8k / 0 |
| LLM cost (total / last 7 days) | — / — |

### arena_qwen

| | |
|:--|--:|
| Models | `qwen/qwen3.8-omni-flash` |
| Mode | paper |
| Sessions | 5 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:10 UTC |
| Net asset value | 100,053.49 (+0.05%) |
| Fills (buys / sells) | 6 (5 / 1) |
| Sells at a profit | 0.00% |
| Realised P&L | -12.96 |
| Commissions | 6.02 |
| Open positions | 5 |
| Invested | 53.71% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -1.66% |
| LLM calls | 516 |
| LLM tokens (in / out / cache read) | 2.21M / 1.18M / 9.0k |
| LLM cost (total / last 7 days) | $0.88 / $0.88 |

### arena_solo_claude

| | |
|:--|--:|
| Models | `anthropic/claude-haiku-5.5` |
| Mode | paper |
| Sessions | 5 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 15:20 UTC |
| Net asset value | 100,115.46 (+0.12%) |
| Fills (buys / sells) | 5 (5 / 0) |
| Sells at a profit | — |
| Realised P&L | 0.00 |
| Commissions | 5.00 |
| Open positions | 5 |
| Invested | 54.38% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -1.66% |
| LLM calls | 183 |
| LLM tokens (in / out / cache read) | 739.5k / 133.7k / 0 |
| LLM cost (total / last 7 days) | $0.14 / $0.14 |

### arena_solo_deepseek

| | |
|:--|--:|
| Models | `deepseek/deepseek-v4.1-flash` |
| Mode | paper |
| Sessions | 5 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:00 UTC |
| Net asset value | 100,126.63 (+0.13%) |
| Fills (buys / sells) | 5 (5 / 0) |
| Sells at a profit | — |
| Realised P&L | 0.00 |
| Commissions | 5.00 |
| Open positions | 5 |
| Invested | 54.53% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -1.66% |
| LLM calls | 161 |
| LLM tokens (in / out / cache read) | 493.1k / 168.7k / 9.9k |
| LLM cost (total / last 7 days) | $0.17 / $0.17 |

### arena_solo_glm

| | |
|:--|--:|
| Models | `z-ai/glm-5.3-flashx` |
| Mode | paper |
| Sessions | 5 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:40 UTC |
| Net asset value | 100,407.00 (+0.41%) |
| Fills (buys / sells) | 9 (9 / 0) |
| Sells at a profit | — |
| Realised P&L | 0.00 |
| Commissions | 7.48 |
| Open positions | 7 |
| Invested | 67.57% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -1.66% |
| LLM calls | 263 |
| LLM tokens (in / out / cache read) | 764.9k / 388.7k / 57.5k |
| LLM cost (total / last 7 days) | $0.75 / $0.75 |

### arena_solo_gpt

| | |
|:--|--:|
| Models | `openai/gpt-6-luna` |
| Mode | paper |
| Sessions | 5 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 15:00 UTC |
| Net asset value | 100,597.78 (+0.60%) |
| Fills (buys / sells) | 1 (1 / 0) |
| Sells at a profit | — |
| Realised P&L | 0.00 |
| Commissions | 1.00 |
| Open positions | 1 |
| Invested | 15.32% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -1.66% |
| LLM calls | 243 |
| LLM tokens (in / out / cache read) | 679.8k / 97.5k / 0 |
| LLM cost (total / last 7 days) | — / — |

### arena_solo_qwen

| | |
|:--|--:|
| Models | `qwen/qwen3.8-omni-flash` |
| Mode | paper |
| Sessions | 5 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:20 UTC |
| Net asset value | 100,000.00 (+0.00%) |
| Fills (buys / sells) | 0 (0 / 0) |
| Sells at a profit | — |
| Realised P&L | 0.00 |
| Commissions | 0.00 |
| Open positions | 0 |
| Invested | 0.00% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -1.66% |
| LLM calls | 35 |
| LLM tokens (in / out / cache read) | 118.0k / 83.6k / 0 |
| LLM cost (total / last 7 days) | $0.06 / $0.06 |

### demo_all_modules

| | |
|:--|--:|
| Models | `deepseek-chat` |
| Mode | paper |
| Sessions | 12 |
| Starting capital | 10,000.00 |
| First paper/live run | 2026-10-08 13:40 UTC |
| Net asset value | 9,589.78 (-4.10%) |
| Fills (buys / sells) | 30 (15 / 15) |
| Sells at a profit | 0.00% |
| Realised P&L | -260.09 |
| Commissions | 27.90 |
| Open positions | 6 |
| Invested | 61.30% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -2.35% |
| LLM calls | 3068 |
| LLM tokens (in / out / cache read) | 11.64M / 1.01M / 751.9k |
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
