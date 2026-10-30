# Paper-trading benchmark

**English** | [简体中文](README.zh-CN.md)

> [!IMPORTANT]
> These are **paper-trading** results from IBKR paper accounts, not real money. Fills are real paper fills, but paper trading ignores market impact and can fill orders a live account would not. Past results say nothing about future ones. Not investment advice.

<sub>Updated 2026-10-30 · data through 2026-10-30</sub>

<p align="center"><img src="equity.svg" alt="Cumulative paper-trading return of each pipeline against its benchmark" width="880"></p>

## Summary

| Pipeline | Model | Since | Return | Benchmark | Excess | Max drawdown | Sharpe | LLM cost |
|:--|:--|--:|--:|--:|--:|--:|--:|--:|
| **arena_claude** | claude-haiku-5.5 | 2026-10-16 | -0.79% | SPY -1.31% | +0.53% | -2.62% | — | $1.17 |
| **arena_deepseek** | deepseek-v4.1-flash | 2026-10-16 | +0.45% | SPY -1.31% | +1.76% | -1.77% | — | $2.15 |
| **arena_glm** | glm-5.3-flashx | 2026-10-16 | +0.19% | SPY -1.31% | +1.50% | -2.04% | — | $4.49 |
| **arena_gpt** | gpt-6-luna | 2026-10-16 | +0.57% | SPY -1.31% | +1.88% | -1.72% | — | — |
| **arena_qwen** | qwen3.8-omni-flash | 2026-10-16 | -0.08% | SPY -1.31% | +1.24% | -1.85% | — | $2.31 |
| **arena_solo_claude** | claude-haiku-5.5 | 2026-10-16 | +1.07% | SPY -1.31% | +2.39% | -1.68% | — | $0.31 |
| **arena_solo_deepseek** | deepseek-v4.1-flash | 2026-10-16 | +0.82% | SPY -1.31% | +2.14% | -1.17% | — | $0.39 |
| **arena_solo_glm** | glm-5.3-flashx | 2026-10-16 | +1.68% | SPY -1.31% | +2.99% | -1.60% | — | $1.52 |
| **arena_solo_gpt** | gpt-6-luna | 2026-10-16 | +1.12% | SPY -1.31% | +2.43% | -0.26% | — | — |
| **arena_solo_qwen** | qwen3.8-omni-flash | 2026-10-16 | +0.00% | SPY -1.31% | +1.31% | +0.00% | — | $0.07 |
| **demo_all_modules** | deepseek-chat | 2026-10-07 | -5.81% | SPY -3.09% | -2.72% | -6.51% | — | — |

## Pipelines

### arena_claude

| | |
|:--|--:|
| Models | `anthropic/claude-haiku-5.5` |
| Mode | paper |
| Sessions | 10 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 15:10 UTC |
| Net asset value | 99,213.09 (-0.79%) |
| Fills (buys / sells) | 11 (6 / 5) |
| Sells at a profit | 0.00% |
| Realised P&L | -761.83 |
| Commissions | 11.18 |
| Open positions | 5 |
| Invested | 52.34% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -2.57% |
| LLM calls | 1284 |
| LLM tokens (in / out / cache read) | 6.78M / 974.0k / 0 |
| LLM cost (total / last 7 days) | $1.17 / $0.71 |

### arena_deepseek

| | |
|:--|--:|
| Models | `deepseek/deepseek-v4.1-flash` |
| Mode | paper |
| Sessions | 10 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 13:50 UTC |
| Net asset value | 100,445.58 (+0.45%) |
| Fills (buys / sells) | 35 (20 / 15) |
| Sells at a profit | 6.67% |
| Realised P&L | -793.11 |
| Commissions | 35.24 |
| Open positions | 11 |
| Invested | 86.96% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -2.57% |
| LLM calls | 1888 |
| LLM tokens (in / out / cache read) | 7.29M / 1.83M / 254.5k |
| LLM cost (total / last 7 days) | $2.15 / $1.19 |

### arena_glm

| | |
|:--|--:|
| Models | `z-ai/glm-5.3-flashx` |
| Mode | paper |
| Sessions | 10 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:30 UTC |
| Net asset value | 100,191.39 (+0.19%) |
| Fills (buys / sells) | 31 (16 / 15) |
| Sells at a profit | 0.00% |
| Realised P&L | -1,169.28 |
| Commissions | 31.36 |
| Open positions | 8 |
| Invested | 81.84% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -2.57% |
| LLM calls | 1302 |
| LLM tokens (in / out / cache read) | 5.27M / 2.13M / 467.5k |
| LLM cost (total / last 7 days) | $4.49 / $2.16 |

### arena_gpt

| | |
|:--|--:|
| Models | `openai/gpt-6-luna` |
| Mode | paper |
| Sessions | 10 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:50 UTC |
| Net asset value | 100,571.61 (+0.57%) |
| Fills (buys / sells) | 14 (8 / 6) |
| Sells at a profit | 0.00% |
| Realised P&L | -462.86 |
| Commissions | 13.13 |
| Open positions | 7 |
| Invested | 62.13% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -2.57% |
| LLM calls | 1511 |
| LLM tokens (in / out / cache read) | 4.84M / 600.4k / 0 |
| LLM cost (total / last 7 days) | — / $0.48 |

### arena_qwen

| | |
|:--|--:|
| Models | `qwen/qwen3.8-omni-flash` |
| Mode | paper |
| Sessions | 10 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:10 UTC |
| Net asset value | 99,924.97 (-0.08%) |
| Fills (buys / sells) | 18 (8 / 10) |
| Sells at a profit | 0.00% |
| Realised P&L | -531.72 |
| Commissions | 18.21 |
| Open positions | 8 |
| Invested | 63.82% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -2.57% |
| LLM calls | 1308 |
| LLM tokens (in / out / cache read) | 5.62M / 3.13M / 26.9k |
| LLM cost (total / last 7 days) | $2.31 / $1.43 |

### arena_solo_claude

| | |
|:--|--:|
| Models | `anthropic/claude-haiku-5.5` |
| Mode | paper |
| Sessions | 10 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 15:20 UTC |
| Net asset value | 101,073.14 (+1.07%) |
| Fills (buys / sells) | 11 (10 / 1) |
| Sells at a profit | 0.00% |
| Realised P&L | -72.34 |
| Commissions | 11.02 |
| Open positions | 7 |
| Invested | 78.56% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -2.57% |
| LLM calls | 399 |
| LLM tokens (in / out / cache read) | 1.62M / 289.6k / 0 |
| LLM cost (total / last 7 days) | $0.31 / $0.17 |

### arena_solo_deepseek

| | |
|:--|--:|
| Models | `deepseek/deepseek-v4.1-flash` |
| Mode | paper |
| Sessions | 10 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:00 UTC |
| Net asset value | 100,823.70 (+0.82%) |
| Fills (buys / sells) | 8 (8 / 0) |
| Sells at a profit | — |
| Realised P&L | 0.00 |
| Commissions | 8.00 |
| Open positions | 7 |
| Invested | 71.83% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -2.57% |
| LLM calls | 363 |
| LLM tokens (in / out / cache read) | 1.13M / 374.7k / 42.2k |
| LLM cost (total / last 7 days) | $0.39 / $0.21 |

### arena_solo_glm

| | |
|:--|--:|
| Models | `z-ai/glm-5.3-flashx` |
| Mode | paper |
| Sessions | 10 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 14:40 UTC |
| Net asset value | 101,676.34 (+1.68%) |
| Fills (buys / sells) | 15 (13 / 2) |
| Sells at a profit | 0.00% |
| Realised P&L | -273.13 |
| Commissions | 12.54 |
| Open positions | 9 |
| Invested | 77.26% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -2.57% |
| LLM calls | 528 |
| LLM tokens (in / out / cache read) | 1.58M / 778.9k / 141.7k |
| LLM cost (total / last 7 days) | $1.52 / $0.76 |

### arena_solo_gpt

| | |
|:--|--:|
| Models | `openai/gpt-6-luna` |
| Mode | paper |
| Sessions | 10 |
| Starting capital | 100,000.00 |
| First paper/live run | 2026-10-19 15:00 UTC |
| Net asset value | 101,116.70 (+1.12%) |
| Fills (buys / sells) | 2 (2 / 0) |
| Sells at a profit | — |
| Realised P&L | 0.00 |
| Commissions | 2.00 |
| Open positions | 2 |
| Invested | 27.96% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -2.57% |
| LLM calls | 507 |
| LLM tokens (in / out / cache read) | 1.43M / 201.4k / 0 |
| LLM cost (total / last 7 days) | — / $0.13 |

### arena_solo_qwen

| | |
|:--|--:|
| Models | `qwen/qwen3.8-omni-flash` |
| Mode | paper |
| Sessions | 10 |
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
| Benchmark max drawdown | -2.57% |
| LLM calls | 45 |
| LLM tokens (in / out / cache read) | 154.8k / 108.1k / 0 |
| LLM cost (total / last 7 days) | $0.07 / $0.02 |

### demo_all_modules

| | |
|:--|--:|
| Models | `deepseek-chat` |
| Mode | paper |
| Sessions | 17 |
| Starting capital | 10,000.00 |
| First paper/live run | 2026-10-08 13:40 UTC |
| Net asset value | 9,419.30 (-5.81%) |
| Fills (buys / sells) | 33 (16 / 17) |
| Sells at a profit | 0.00% |
| Realised P&L | -287.62 |
| Commissions | 30.50 |
| Open positions | 6 |
| Invested | 62.08% |
| Volatility (annualised) | — |
| CAGR | — |
| Benchmark max drawdown | -3.25% |
| LLM calls | 4108 |
| LLM tokens (in / out / cache read) | 15.61M / 1.32M / 1.01M |
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
