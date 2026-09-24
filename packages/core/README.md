# quant-core

共享基础：数据模型、五档仓位计算、接口协议、LLM 客户端、配置加载、注册表、日志、实盘保护。
依赖图的根，不依赖任何其他 `quant-*` 包。

## 公开接口

| 模块 | 内容 |
|---|---|
| `quant_core.models` | `Action`（五档，含 `weight` / `direction` / `nearest()` / `is_reduction_of()`）、`Instrument`、`Bar`、`Quote`、`Position`、`AccountSnapshot`、`SentimentItem`、`SentimentResult`、`Decision`、`AggregatedDecision`、`RiskVerdict`、`OrderIntent`、`OrderResult`、`Fill`、`PipelineContext` |
| `quant_core.sizing` | `size_order()`、`buy_base_amount()`、`spendable_cash()`、`floor_to_lot()`、`SizingConfig` |
| `quant_core.interfaces` | `Stage`、`SentimentSource`（Protocol） |
| `quant_core.agent` | `Agent[T]` 基类、`AgentResult` |
| `quant_core.llm` | `LLMClient` 协议、`AnthropicLLMClient`、`OpenAICompatibleLLMClient`、`FakeLLMClient`、`LLMClientPool` / `create_llm_client()`、`complete_structured()`、`LLMCallRecorder` 协议 |
| `quant_core.config` | `ConfigStore`、`PipelineConfig`、`AgentConfig`、`AccountConfig`、`StageConfig.options()`、`config_hash()` |
| `quant_core.registry` | `Registry`，以及全局 `STAGES` / `AGENTS` / `SENTIMENT_SOURCES`（通过 entry points 自动发现） |
| `quant_core.logging` | `configure_logging()`、`get_logger()`、`bind_run()` |
| `quant_core.safety` | `ensure_mode_allowed()`：`mode: live` 且 `QUANT_ALLOW_LIVE=1` 才放行 |
| `quant_core.timeutil` | `utcnow()`、`UtcDatetime`、`EXCHANGE_TZ`、`DISPLAY_TZ` |

## 接入不同厂商的模型

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

平时通过配置使用：在 `configs/llm_providers.yaml` 里给每个厂商起个名字，agent 配置里用 `model.provider: deepseek` 引用它。`LLMClientPool` 为每个厂商创建一个共享的客户端，所以该厂商的并发上限对所有 agent 一起生效：

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
- **五档仓位**：
  - 买入档 = 买入基数 × 15%/30%。买入基数取流水线子账本的现金或 NAV（由 `sizing.buy_base` 决定），且不超过可动用现金。
  - 卖出档 = 子账本持仓 × 15%/30%，向下取整到交易单位（lot）；没有持仓时降为 HOLD（不做空）。
  - `min_one_lot_on_sell: true` 时，向下取整为 0 的卖出改为卖出 1 手。否则小仓位永远卖不掉，例如 3 股 × 15% 向下取整就是 0。
- **风控只能降低风险**：`RiskVerdict` 在模型校验层面强制，只允许同方向减小或改为 HOLD。
- **失败即 HOLD**：LLM 输出按 Pydantic 校验，不合格时把错误信息反馈给模型重试（最多 `max_validation_attempts` 次）；仍失败或 LLM 不可用时，由 `Agent.fallback_output()` 给出安全输出（决策 agent 为 HOLD），并记录错误。每一次调用都会通过 `LLMCallRecorder` 留下审计记录。
- **LLM 重试策略只有一处**：`BaseLLMClient` 负责并发上限（Semaphore）、单次超时和 tenacity 退避重试（限流、5xx、网络错误、超时）；Anthropic SDK 自带的重试已关闭。
- **Anthropic 结构化输出**：用 `output_config.format`（JSON schema）。数值上下限等 API 不支持的约束会从 schema 中移除，改写进字段描述，最终由 Pydantic 在本地校验。
- **采样参数**：当前 Claude 模型（Opus 5、Sonnet 5 等）会拒绝 `temperature`，配置里请不要设置；设置后会通过 `extra_body` 发送，只适用于仍接受该参数的旧模型（如 Haiku 4.5）。

## 配置项

`configs/` 下各文件的 schema：

- `accounts/<name>.yaml` → `AccountConfig`
- `llm_providers.yaml` → `LLMProvidersConfig`（见上文）
- `agents/<agent_id>.yaml` → `AgentConfig`：`prompt_template` 路径相对 `configs/agents/`，模板用 Jinja2 沙箱渲染，缺少变量会报错
- `pipelines/<name>.yaml` → `PipelineConfig`，校验内容包括：
  - 阶段顺序：数据 → 舆情 → 决策 → 风控 → 交易
  - 启用交易时，前面必须有启用且不可跳过的风控阶段
  - universe 不能重复
  - `mode` 默认为 `dry_run`

字符串里可用 `${VAR}`、`${VAR:-默认值}` 引用环境变量，`$$` 表示字面的 `$`。缺少的环境变量会一次性全部列出。

## 运行测试

```bash
python tasks.py test-core
```
