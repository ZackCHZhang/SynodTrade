# synodtrade-core

[English](README.md) | **简体中文**

共享基础：数据模型、五档仓位计算、技术指标、接口协议、LLM 客户端、配置加载、注册表、服务容器、日志、实盘保护。
依赖图的根，不依赖任何其他 `synodtrade-*` 包。

## 公开接口

| 模块 | 内容 |
|---|---|
| `synodtrade_core.models` | `Action`（五档，含 `weight` / `direction` / `nearest()` / `is_reduction_of()`）、`Verdict`、`RunMode`、`OrderSide`、`OrderType`、`OrderStatus`、`Timeframe`；行情与账户：`Instrument`、`Bar`、`Quote`、`Position`、`AccountSnapshot`；分析结果：`Candidate`、`SelectionPick`、`SelectionResult`、`StockSelection`、`SentimentItem`、`SentimentResult`、`Decision`、`Vote`、`AggregatedDecision`、`RuleHit`、`RiskVerdict`；订单：`OrderIntent`、`OrderResult`、`Fill`；`PipelineContext`、`StageError` |
| `synodtrade_core.sizing` | `size_order()`、`buy_base_amount()`、`spendable_cash()`、`floor_to_lot()`、`SizingConfig`、`BuyBase` |
| `synodtrade_core.indicators` | `compute_indicators(bars) -> TechnicalSnapshot`：决策、风控、选股共用的技术指标（见下文） |
| `synodtrade_core.interfaces` | 协议：`Stage`、`SentimentSource`、`CandidateSource`、`BarsRefresher` |
| `synodtrade_core.agent` | `Agent[T]` 基类、`AgentResult` |
| `synodtrade_core.agent_factory` | `instantiate_agents()`、`AgentSlot`：按流水线里的 agent 引用（`count`、`weight`、`model`）创建实例 |
| `synodtrade_core.services` | `Services`：阶段工厂函数使用的服务容器（`get` / `optional` / `with_`） |
| `synodtrade_core.llm` | `LLMClient` 协议、`BaseLLMClient`、`AnthropicLLMClient`、`OpenAICompatibleLLMClient`、`FakeLLMClient`、`LLMClientPool` / `create_llm_client()`、`complete_structured()`、`LLMCallRecorder` 协议（`InMemoryLLMCallRecorder`、`NullLLMCallRecorder`） |
| `synodtrade_core.config` | `ConfigStore`、`PipelineConfig`、`StageConfig.options()`、`AgentConfig`、`AgentRef`、`AccountConfig`、`BudgetConfig`、`LLMModelConfig`、`resolve_model()`、`config_hash()`、`interpolate_env()`、`CANONICAL_STAGE_ORDER` |
| `synodtrade_core.registry` | `Registry`，以及全局 `STAGES` / `AGENTS` / `SENTIMENT_SOURCES` / `CANDIDATE_SOURCES`（通过 entry points `synodtrade.stages` / `synodtrade.agents` / `synodtrade.sentiment_sources` / `synodtrade.candidate_sources` 自动发现） |
| `synodtrade_core.logging` | `configure_logging()`、`get_logger()`、`bind_run()`；日志中的密钥字段会被替换成 `***` |
| `synodtrade_core.safety` | `ensure_mode_allowed()`：`mode: live` 且 `SYNODTRADE_ALLOW_LIVE=1` 才放行 |
| `synodtrade_core.timeutil` | `utcnow()`、`to_utc()`、`UtcDatetime`、`EXCHANGE_TZ`（纽约）、`DISPLAY_TZ`（柏林） |
| `synodtrade_core.envfile` | `load_env_file()`：读取 `.env`，不覆盖已经存在的环境变量；`SYNODTRADE_NO_DOTENV=1` 时不读取 |

## 技术指标（`synodtrade_core.indicators`）

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

## 接入不同厂商的模型

两种客户端都在构造时传入 `api_key` 和 `base_url`：

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

## 关键约定

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

## 配置项

`configs/` 下各文件的 schema：

- `accounts/<name>.yaml` → `AccountConfig`
- `llm_providers.yaml` → `LLMProvidersConfig`（见上文）
- `agents/<agent_id>.yaml` → `AgentConfig`：`prompt_template` 路径相对 `configs/agents/`，模板用 Jinja2 沙箱渲染，缺少变量会报错；`impl` 可指定注册表中的其他实现，默认按 `role` 选择
- `pipelines/<name>.yaml` → `PipelineConfig`，校验内容包括：
  - 阶段顺序：（选股 →）数据 → 舆情 → 决策 → 风控 → 交易（`CANONICAL_STAGE_ORDER`），同一类型的阶段只能出现一次
  - 启用交易时，前面必须有启用的风控阶段，且风控阶段不能设 `on_error: skip`
  - universe 不能有重复；没有选股阶段时至少要有 1 只股票
  - `mode` 默认为 `dry_run`
- 风控规则和调度的 schema 分别在 `synodtrade-risk` 和 `synodtrade-scheduler` 中

字符串里可用 `${VAR}`、`${VAR:-默认值}` 引用环境变量，`$$` 表示字面的 `$`。缺少的环境变量会一次性全部列出。

## 运行测试

```bash
python tasks.py test-core
```
