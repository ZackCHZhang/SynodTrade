# synodtrade-core

**English** | [简体中文](README.zh-CN.md)

Shared foundation: data models, five-tier position sizing, technical indicators, interface protocols, LLM clients, config loading, registries, service container, logging and the live-trading guard.
It is the root of the dependency graph and depends on no other `synodtrade-*` package.

## Public API

| Module | Contents |
|---|---|
| `synodtrade_core.models` | `Action` (five tiers, with `weight` / `direction` / `nearest()` / `is_reduction_of()`), `Verdict`, `RunMode`, `OrderSide`, `OrderType`, `OrderStatus`, `Timeframe`; market and account: `Instrument`, `Bar`, `Quote`, `Position`, `AccountSnapshot`; analysis results: `Candidate`, `SelectionPick`, `SelectionResult`, `StockSelection`, `SentimentItem`, `SentimentResult`, `Decision`, `Vote`, `AggregatedDecision`, `RuleHit`, `RiskVerdict`; orders: `OrderIntent`, `OrderResult`, `Fill`; `PipelineContext`, `StageError` |
| `synodtrade_core.sizing` | `size_order()`, `buy_base_amount()`, `spendable_cash()`, `floor_to_lot()`, `SizingConfig`, `BuyBase` |
| `synodtrade_core.indicators` | `compute_indicators(bars) -> TechnicalSnapshot`: the technical indicators shared by decision, risk and selection (see below) |
| `synodtrade_core.interfaces` | Protocols: `Stage`, `SentimentSource`, `CandidateSource`, `BarsRefresher` |
| `synodtrade_core.agent` | `Agent[T]` base class, `AgentResult` |
| `synodtrade_core.agent_factory` | `instantiate_agents()`, `AgentSlot`: create instances from the pipeline's agent references (`count`, `weight`, `model`) |
| `synodtrade_core.services` | `Services`: the service container passed to stage factories (`get` / `optional` / `with_`) |
| `synodtrade_core.llm` | `LLMClient` protocol, `BaseLLMClient`, `AnthropicLLMClient`, `OpenAICompatibleLLMClient`, `FakeLLMClient`, `LLMClientPool` / `create_llm_client()`, `complete_structured()`, `LLMCallRecorder` protocol (`InMemoryLLMCallRecorder`, `NullLLMCallRecorder`) |
| `synodtrade_core.config` | `ConfigStore`, `PipelineConfig`, `StageConfig.options()`, `AgentConfig`, `AgentRef`, `AccountConfig`, `BudgetConfig`, `LLMModelConfig`, `resolve_model()`, `config_hash()`, `interpolate_env()`, `CANONICAL_STAGE_ORDER` |
| `synodtrade_core.registry` | `Registry` and the global `STAGES` / `AGENTS` / `SENTIMENT_SOURCES` / `CANDIDATE_SOURCES` (discovered via the entry points `synodtrade.stages` / `synodtrade.agents` / `synodtrade.sentiment_sources` / `synodtrade.candidate_sources`) |
| `synodtrade_core.logging` | `configure_logging()`, `get_logger()`, `bind_run()`; secret-looking fields are replaced by `***` in logs |
| `synodtrade_core.safety` | `ensure_mode_allowed()`: `mode: live` passes only with `SYNODTRADE_ALLOW_LIVE=1` |
| `synodtrade_core.timeutil` | `utcnow()`, `to_utc()`, `UtcDatetime`, `EXCHANGE_TZ` (New York), `DISPLAY_TZ` (Berlin) |
| `synodtrade_core.envfile` | `load_env_file()`: loads `.env` without overriding variables that are already set; skipped when `SYNODTRADE_NO_DOTENV=1` |

## Technical indicators (`synodtrade_core.indicators`)

All computed in code; the LLM never does arithmetic. Input is daily bars, oldest first; a field is `None` when there is not enough history:

- Returns over 1, 5, 20, 60, 120 and 250 days
- Annualised volatility over 20 and 60 days (daily log returns)
- SMA 20/50/200 and the close's distance from each
- RSI 14 (Wilder smoothing)
- MACD(12,26,9): line, signal, histogram
- 52-week high and low and the distance from each (needs at least 252 bars)
- Maximum drawdown over one year
- Last bar's volume relative to the previous 20-day average

There is currently **no** ATR, z-score, ADX, OBV, VWAP or gap statistic.

## Using models from different vendors

Both clients take `api_key` and `base_url` in their constructor:

```python
from synodtrade_core.llm import AnthropicLLMClient, OpenAICompatibleLLMClient, StructuredOutputMode

claude = AnthropicLLMClient(api_key=key, name="anthropic")
deepseek = OpenAICompatibleLLMClient(
    api_key=key,
    base_url="https://api.deepseek.com",
    name="deepseek",
    structured_output=StructuredOutputMode.JSON_OBJECT,
)
```

- `AnthropicLLMClient`: Anthropic Messages API. Point `base_url` elsewhere to use any Anthropic-compatible service, e.g. DeepSeek's `https://api.deepseek.com/anthropic`.
- `OpenAICompatibleLLMClient`: OpenAI Chat Completions API, for DeepSeek, OpenAI, Qwen, Kimi, vLLM, Ollama and others. Vendors differ in JSON support; choose with `structured_output`:
  - `json_schema`: services that accept a JSON schema (e.g. OpenAI)
  - `json_object`: services with JSON mode only, e.g. DeepSeek; the schema goes into the system prompt
  - `prompt`: services without JSON mode; the prompt alone constrains the output

  In every mode the reply is finally validated by Pydantic.

Normally this is configured: give each vendor a name in `configs/llm_providers.yaml` and select it with `model.provider: deepseek` in an agent reference. `LLMClientPool` creates one shared client per vendor, so the vendor's concurrency limit applies to all agents together:

```python
pool = LLMClientPool(store.llm_providers())
pool.check(["anthropic", "deepseek"])  # startup check: vendor exists and its API key is set
client = pool.get(agent_cfg.model.provider)
pool.set("deepseek", FakeLLMClient(...))  # swap in a fake client for tests or dry runs
```

**The model is chosen at instantiation.** An agent config (`configs/agents/*.yaml`) describes persona and prompt only; `model` may be omitted. Vendor and model are given where the agent is instantiated:

- In a pipeline config, add `model` to each agent reference, e.g. `{ agent: retail_mood, count: 2, model: { provider: deepseek, name: deepseek-chat } }`. Reference the same agent twice to run it on two models.
- In code, pass it as `SomeAgent(config, client, model=LLMModelConfig(...), prompt_root=...)`.

`resolve_model(agent_config, override)` merges them: the agent config's default model (if any) is the base, and only the fields set in the reference override it. Startup validation fails if `provider` and `name` are still missing.

**API keys never go into config files.** `api_key_env` holds the *name* of an environment variable (e.g. `DEEPSEEK_API_KEY`, set in `.env`); the factory reads it and passes the value to the constructor. Neither the client's `repr` nor the audit records contain the key. The `provider` field of an audit record is the configured name, e.g. `deepseek`.

## Key conventions

- **Money and quantities are always `Decimal`**; models are frozen and reject unknown fields.
- **Times are always timezone-aware**: model fields reject naive datetimes and convert to UTC. Ruff's `DTZ` rules catch naive datetimes at lint time.
- **Five-tier sizing** (`Action` weights: `strong_buy` 0.30, `buy` 0.15, `hold` 0, `sell` −0.15, `strong_sell` −0.30):
  - Buy tiers = buy base × 15% / 30%. The buy base is the pipeline sub-ledger's cash or NAV (`sizing.buy_base`, default `available_cash`), capped by spendable cash.
  - Sell tiers = sub-ledger position × 15% / 30%, floored to the lot size (`lot_size`, default 1); without a position the action becomes HOLD (no shorting).
  - With `min_one_lot_on_sell: true` a sell that floors to 0 sells one lot instead; otherwise a small position may never be sellable (3 shares × 15% floors to 0).
- **Risk can only reduce risk**: `RiskVerdict` enforces at model-validation level that an adjustment keeps the direction with a smaller-or-equal size, or becomes HOLD.
- **Failure means HOLD**: LLM output is validated by Pydantic; on failure the error is fed back and the model retries (up to `max_validation_attempts`, default 3). If it still fails or the LLM is unavailable, `Agent.fallback_output()` supplies a safe output (HOLD for decision agents) and the error is recorded. Every call leaves an audit record through `LLMCallRecorder`.
- **One retry policy for LLM calls**: `BaseLLMClient` handles the concurrency limit (semaphore), per-call timeout and tenacity backoff (rate limits, 5xx, network errors, timeouts); the Anthropic SDK's own retries are disabled.
- **Anthropic structured output** uses `output_config.format` (JSON schema); `effort` is sent through `output_config` as well. Constraints the API does not support (numeric bounds and the like) are removed from the schema and written into the field descriptions; Pydantic still enforces them locally.
- **Sampling parameters**: `temperature` is unset by default (the code notes that current Claude models reject it); if set, it is sent through `extra_body` and only works with models that still accept it.

## Configuration

Schemas of the files under `configs/`:

- `accounts/<name>.yaml` → `AccountConfig`
- `llm_providers.yaml` → `LLMProvidersConfig` (see above)
- `agents/<agent_id>.yaml` → `AgentConfig`: `prompt_template` is relative to `configs/agents/` and rendered in a Jinja2 sandbox (missing variables are errors); `impl` selects another registered implementation, otherwise the `role` decides
- `pipelines/<name>.yaml` → `PipelineConfig`, which checks:
  - stage order: (selection →) data → sentiment → decision → risk → trading (`CANONICAL_STAGE_ORDER`); each stage type at most once
  - an enabled trading stage needs an enabled risk stage before it, and that risk stage may not use `on_error: skip`
  - no duplicate symbols in the universe; at least one symbol unless there is a selection stage
  - `mode` defaults to `dry_run`
- The schemas of risk rules and schedules live in `synodtrade-risk` and `synodtrade-scheduler`

Strings may reference environment variables as `${VAR}` or `${VAR:-default}`; `$$` is a literal `$`. All missing variables are reported at once.

## Running tests

```bash
python tasks.py test-core
```
