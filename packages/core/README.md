# quant-core

[中文](#中文) | [English](#english)

---

## 中文

共享基础：数据模型、五档仓位计算、技术指标、接口协议、LLM 客户端、配置加载、注册表、服务容器、日志、实盘保护。
依赖图的根，不依赖任何其他 `quant-*` 包。

### 公开接口

| 模块 | 内容 |
|---|---|
| `quant_core.models` | `Action`（五档，含 `weight` / `direction` / `nearest()` / `is_reduction_of()`）、`Verdict`、`RunMode`、`OrderSide`、`OrderType`、`OrderStatus`、`Timeframe`；行情与账户：`Instrument`、`Bar`、`Quote`、`Position`、`AccountSnapshot`；分析结果：`Candidate`、`SelectionPick`、`SelectionResult`、`StockSelection`、`SentimentItem`、`SentimentResult`、`Decision`、`Vote`、`AggregatedDecision`、`RuleHit`、`RiskVerdict`；订单：`OrderIntent`、`OrderResult`、`Fill`；`PipelineContext`、`StageError` |
| `quant_core.sizing` | `size_order()`、`buy_base_amount()`、`spendable_cash()`、`floor_to_lot()`、`SizingConfig`、`BuyBase` |
| `quant_core.indicators` | `compute_indicators(bars) -> TechnicalSnapshot`：决策、风控、选股共用的技术指标（见下文） |
| `quant_core.interfaces` | 协议：`Stage`、`SentimentSource`、`CandidateSource`、`BarsRefresher` |
| `quant_core.agent` | `Agent[T]` 基类、`AgentResult` |
| `quant_core.agent_factory` | `instantiate_agents()`、`AgentSlot`：按流水线里的 agent 引用（`count`、`weight`、`model`）创建实例 |
| `quant_core.services` | `Services`：阶段工厂函数使用的服务容器（`get` / `optional` / `with_`） |
| `quant_core.llm` | `LLMClient` 协议、`BaseLLMClient`、`AnthropicLLMClient`、`OpenAICompatibleLLMClient`、`FakeLLMClient`、`LLMClientPool` / `create_llm_client()`、`complete_structured()`、`LLMCallRecorder` 协议（`InMemoryLLMCallRecorder`、`NullLLMCallRecorder`） |
| `quant_core.config` | `ConfigStore`、`PipelineConfig`、`StageConfig.options()`、`AgentConfig`、`AgentRef`、`AccountConfig`、`BudgetConfig`、`LLMModelConfig`、`resolve_model()`、`config_hash()`、`interpolate_env()`、`CANONICAL_STAGE_ORDER` |
| `quant_core.registry` | `Registry`，以及全局 `STAGES` / `AGENTS` / `SENTIMENT_SOURCES` / `CANDIDATE_SOURCES`（通过 entry points `quant.stages` / `quant.agents` / `quant.sentiment_sources` / `quant.candidate_sources` 自动发现） |
| `quant_core.logging` | `configure_logging()`、`get_logger()`、`bind_run()`；日志中的密钥字段会被替换成 `***` |
| `quant_core.safety` | `ensure_mode_allowed()`：`mode: live` 且 `QUANT_ALLOW_LIVE=1` 才放行 |
| `quant_core.timeutil` | `utcnow()`、`to_utc()`、`UtcDatetime`、`EXCHANGE_TZ`（纽约）、`DISPLAY_TZ`（柏林） |
| `quant_core.envfile` | `load_env_file()`：读取 `.env`，不覆盖已经存在的环境变量；`QUANT_NO_DOTENV=1` 时不读取 |

### 技术指标（`quant_core.indicators`）

全部由代码计算，LLM 不做任何计算。输入是按时间正序的日线，历史不够时对应字段为 `None`：

- 收益率：1、5、20、60、120、250 日
- 年化波动率：20 日、60 日（日对数收益）
- SMA 20/50/200，以及收盘价相对各均线的偏离
- RSI 14（Wilder 平滑）
- MACD(12,26,9)：MACD 线、信号线、柱
- 52 周高点、低点，以及当前价与它们的距离（需要至少 252 根 K 线）
- 近一年最大回撤
- 最后一根 K 线的成交量相对前 20 日均量的倍数

目前**没有** ATR、z 分数、ADX、OBV、VWAP、跳空统计等指标。

### 接入不同厂商的模型

两种客户端都在构造时传入 `api_key` 和 `base_url`：

```python
from quant_core.llm import AnthropicLLMClient, OpenAICompatibleLLMClient, StructuredOutputMode

claude = AnthropicLLMClient(api_key=key, name="anthropic")
deepseek = OpenAICompatibleLLMClient(
    api_key=key,
    base_url="https://api.deepseek.com",
    name="deepseek",
    structured_output=StructuredOutputMode.JSON_OBJECT,
)
```

- `AnthropicLLMClient`：Anthropic Messages API。换一个 `base_url` 就能接任何兼容 Anthropic 协议的服务，例如 DeepSeek 的 `https://api.deepseek.com/anthropic`。
- `OpenAICompatibleLLMClient`：OpenAI Chat Completions API，适用于 DeepSeek、OpenAI、通义千问、Kimi、vLLM、Ollama 等。不同厂商对 JSON 输出的支持不同，用 `structured_output` 选择：
  - `json_schema`：OpenAI 等支持 JSON schema 的服务
  - `json_object`：只支持 JSON 模式的服务，例如 DeepSeek；schema 会写进 system prompt
  - `prompt`：连 JSON 模式都不支持的服务，只靠 prompt 约束

  无论哪种模式，返回结果最终都由 Pydantic 校验。

平时通过配置使用：在 `configs/llm_providers.yaml` 里给每个厂商起个名字，agent 引用里用 `model.provider: deepseek` 指定。`LLMClientPool` 为每个厂商创建一个共享的客户端，所以该厂商的并发上限对所有 agent 一起生效：

```python
pool = LLMClientPool(store.llm_providers())
pool.check(["anthropic", "deepseek"])  # 启动时检查：厂商存在，且 API key 已设置
client = pool.get(agent_cfg.model.provider)
pool.set("deepseek", FakeLLMClient(...))  # 测试或 dry-run 时替换成假客户端
```

**模型在实例化时决定。** agent 配置（`configs/agents/*.yaml`）只描述人格和提示词，`model` 可以省略。用哪个厂商、哪个模型，在实例化 agent 的地方指定：

- 在流水线配置里，给每条 agent 引用写上 `model`，比如 `{ agent: retail_mood, count: 2, model: { provider: deepseek, name: deepseek-chat } }`。同一个 agent 写两条引用，就能分别用不同的模型。
- 在代码里，通过 `SomeAgent(config, client, model=LLMModelConfig(...), prompt_root=...)` 传入。

合并规则由 `resolve_model(agent_config, override)` 实现：以 agent 配置里的默认模型为基础（如果有），只覆盖引用中写了的字段。最终没有 `provider` 和 `name` 时，启动校验就会报错。

**API key 不写进配置文件。** `api_key_env` 写的是环境变量的名字（例如 `DEEPSEEK_API_KEY`，在 `.env` 中设置），工厂函数读取该变量后传给构造函数。客户端的 `repr` 和审计记录都不包含 key。审计记录里的 `provider` 字段是配置中的名字，例如 `deepseek`。

### 关键约定

- **金额与数量一律用 `Decimal`**；模型都是 frozen 的，不接受未知字段。
- **时间一律带时区**：模型字段拒绝不带时区的 datetime，并统一转成 UTC。ruff 的 `DTZ` 规则在 lint 阶段就会拦截不带时区的写法。
- **五档仓位**（`Action` 的权重：`strong_buy` 0.30、`buy` 0.15、`hold` 0、`sell` −0.15、`strong_sell` −0.30）：
  - 买入档 = 买入基数 × 15% / 30%。买入基数取流水线子账本的现金或 NAV（由 `sizing.buy_base` 决定，默认 `available_cash`），且不超过可动用现金。
  - 卖出档 = 子账本持仓 × 15% / 30%，向下取整到交易单位（`lot_size`，默认 1）；没有持仓时降为 HOLD（不做空）。
  - `min_one_lot_on_sell: true` 时，向下取整为 0 的卖出改为卖出 1 手。否则小仓位永远卖不掉，例如 3 股 × 15% 向下取整就是 0。
- **风控只能降低风险**：`RiskVerdict` 在模型校验层面强制，只允许同方向减小或改为 HOLD。
- **失败即 HOLD**：LLM 输出按 Pydantic 校验，不合格时把错误信息反馈给模型重试（最多 `max_validation_attempts` 次，默认 3）；仍失败或 LLM 不可用时，由 `Agent.fallback_output()` 给出安全输出（决策 agent 为 HOLD），并记录错误。每一次调用都会通过 `LLMCallRecorder` 留下审计记录。
- **LLM 重试策略只有一处**：`BaseLLMClient` 负责并发上限（Semaphore）、单次超时和 tenacity 退避重试（限流、5xx、网络错误、超时）；Anthropic SDK 自带的重试已关闭。
- **Anthropic 结构化输出**：用 `output_config.format`（JSON schema），`effort` 也通过 `output_config` 发送。数值上下限等 API 不支持的约束会从 schema 中移除，改写进字段描述，最终由 Pydantic 在本地校验。
- **采样参数**：`temperature` 默认不设置（代码注释说明当前 Claude 模型会拒绝它）；设置后通过 `extra_body` 发送，只适用于仍接受该参数的模型。

### 配置项

`configs/` 下各文件的 schema：

- `accounts/<name>.yaml` → `AccountConfig`
- `llm_providers.yaml` → `LLMProvidersConfig`（见上文）
- `agents/<agent_id>.yaml` → `AgentConfig`：`prompt_template` 路径相对 `configs/agents/`，模板用 Jinja2 沙箱渲染，缺少变量会报错；`impl` 可指定注册表中的其他实现，默认按 `role` 选择
- `pipelines/<name>.yaml` → `PipelineConfig`，校验内容包括：
  - 阶段顺序：（选股 →）数据 → 舆情 → 决策 → 风控 → 交易（`CANONICAL_STAGE_ORDER`），同一类型的阶段只能出现一次
  - 启用交易时，前面必须有启用的风控阶段，且风控阶段不能设 `on_error: skip`
  - universe 不能有重复；没有选股阶段时至少要有 1 只股票
  - `mode` 默认为 `dry_run`
- 风控规则和调度的 schema 分别在 `quant-risk` 和 `quant-scheduler` 中

字符串里可用 `${VAR}`、`${VAR:-默认值}` 引用环境变量，`$$` 表示字面的 `$`。缺少的环境变量会一次性全部列出。

### 运行测试

```bash
python tasks.py test-core
```

---

## English

Shared foundation: data models, five-tier position sizing, technical indicators, interface protocols, LLM clients, config loading, registries, service container, logging and the live-trading guard.
It is the root of the dependency graph and depends on no other `quant-*` package.

### Public API

| Module | Contents |
|---|---|
| `quant_core.models` | `Action` (five tiers, with `weight` / `direction` / `nearest()` / `is_reduction_of()`), `Verdict`, `RunMode`, `OrderSide`, `OrderType`, `OrderStatus`, `Timeframe`; market and account: `Instrument`, `Bar`, `Quote`, `Position`, `AccountSnapshot`; analysis results: `Candidate`, `SelectionPick`, `SelectionResult`, `StockSelection`, `SentimentItem`, `SentimentResult`, `Decision`, `Vote`, `AggregatedDecision`, `RuleHit`, `RiskVerdict`; orders: `OrderIntent`, `OrderResult`, `Fill`; `PipelineContext`, `StageError` |
| `quant_core.sizing` | `size_order()`, `buy_base_amount()`, `spendable_cash()`, `floor_to_lot()`, `SizingConfig`, `BuyBase` |
| `quant_core.indicators` | `compute_indicators(bars) -> TechnicalSnapshot`: the technical indicators shared by decision, risk and selection (see below) |
| `quant_core.interfaces` | Protocols: `Stage`, `SentimentSource`, `CandidateSource`, `BarsRefresher` |
| `quant_core.agent` | `Agent[T]` base class, `AgentResult` |
| `quant_core.agent_factory` | `instantiate_agents()`, `AgentSlot`: create instances from the pipeline's agent references (`count`, `weight`, `model`) |
| `quant_core.services` | `Services`: the service container passed to stage factories (`get` / `optional` / `with_`) |
| `quant_core.llm` | `LLMClient` protocol, `BaseLLMClient`, `AnthropicLLMClient`, `OpenAICompatibleLLMClient`, `FakeLLMClient`, `LLMClientPool` / `create_llm_client()`, `complete_structured()`, `LLMCallRecorder` protocol (`InMemoryLLMCallRecorder`, `NullLLMCallRecorder`) |
| `quant_core.config` | `ConfigStore`, `PipelineConfig`, `StageConfig.options()`, `AgentConfig`, `AgentRef`, `AccountConfig`, `BudgetConfig`, `LLMModelConfig`, `resolve_model()`, `config_hash()`, `interpolate_env()`, `CANONICAL_STAGE_ORDER` |
| `quant_core.registry` | `Registry` and the global `STAGES` / `AGENTS` / `SENTIMENT_SOURCES` / `CANDIDATE_SOURCES` (discovered via the entry points `quant.stages` / `quant.agents` / `quant.sentiment_sources` / `quant.candidate_sources`) |
| `quant_core.logging` | `configure_logging()`, `get_logger()`, `bind_run()`; secret-looking fields are replaced by `***` in logs |
| `quant_core.safety` | `ensure_mode_allowed()`: `mode: live` passes only with `QUANT_ALLOW_LIVE=1` |
| `quant_core.timeutil` | `utcnow()`, `to_utc()`, `UtcDatetime`, `EXCHANGE_TZ` (New York), `DISPLAY_TZ` (Berlin) |
| `quant_core.envfile` | `load_env_file()`: loads `.env` without overriding variables that are already set; skipped when `QUANT_NO_DOTENV=1` |

### Technical indicators (`quant_core.indicators`)

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

### Using models from different vendors

Both clients take `api_key` and `base_url` in their constructor:

```python
from quant_core.llm import AnthropicLLMClient, OpenAICompatibleLLMClient, StructuredOutputMode

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

### Key conventions

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

### Configuration

Schemas of the files under `configs/`:

- `accounts/<name>.yaml` → `AccountConfig`
- `llm_providers.yaml` → `LLMProvidersConfig` (see above)
- `agents/<agent_id>.yaml` → `AgentConfig`: `prompt_template` is relative to `configs/agents/` and rendered in a Jinja2 sandbox (missing variables are errors); `impl` selects another registered implementation, otherwise the `role` decides
- `pipelines/<name>.yaml` → `PipelineConfig`, which checks:
  - stage order: (selection →) data → sentiment → decision → risk → trading (`CANONICAL_STAGE_ORDER`); each stage type at most once
  - an enabled trading stage needs an enabled risk stage before it, and that risk stage may not use `on_error: skip`
  - no duplicate symbols in the universe; at least one symbol unless there is a selection stage
  - `mode` defaults to `dry_run`
- The schemas of risk rules and schedules live in `quant-risk` and `quant-scheduler`

Strings may reference environment variables as `${VAR}` or `${VAR:-default}`; `$$` is a literal `$`. All missing variables are reported at once.

### Running tests

```bash
python tasks.py test-core
```
