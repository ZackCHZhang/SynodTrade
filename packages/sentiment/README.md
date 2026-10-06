# quant-sentiment

[中文](#中文) | [English](#english)

---

## 中文

舆情：从 Reddit、Stocktwits 和 IBKR 新闻采集帖子与新闻标题，交给多个舆情 agent 分析，结果写入数据库。依赖 `quant-core`、`quant-database`。

### 流程（`sentiment` 阶段）

1. **采集**：所有数据源并发拉取最近 `lookback_hours` 小时（默认 24）的内容。单个数据源失败只记录警告；成功的数据源少于 `min_sources_ok`（默认 1）时，阶段失败。
2. **存储**：原始内容写入 `sentiment_items`，按 `(source, external_id, symbol)` 去重。
3. **读取窗口**：从数据库取出窗口 `[as_of - lookback, as_of]` 内的全部内容。之前运行或其他流水线采集到的也会用上，`as_of` 之后发布的不会用到。
4. **预过滤**（确定性代码，不经过 LLM）：
   - 去掉机器人账号（`bot_authors` 列表和 `bot_name_pattern`）、过短（`min_chars`）或低分（`min_score`）的帖子、重复帖和复制粘贴的刷屏帖。
   - 在每个数据源内部按"互动量 + 时间衰减"（半衰期 `half_life_hours`，默认 12 小时）排序，再轮流从各数据源取，直到每个标的取满 `max_items_per_symbol` 条。新闻没有点赞数，这样才不会被高赞帖子挤掉。
   - 清洗文本：合并空白、链接替换成 `[link]`、把 `<` `>` 换成 `‹` `›`（防止帖子伪造 prompt 里的分隔标签）、截断到 `max_chars_per_item`。
5. **分析**：每个 agent 实例对每个有内容的标的调用一次 LLM，所有调用并发执行，并发上限由各 LLM 厂商的配置决定。没有内容的标的不调用 LLM。
6. **写库**：分析结果写入 `sentiment_results`，同时放进 `PipelineContext.sentiment_results`；agent 实例登记到 `agent_instances`；每次 LLM 调用的原始输入输出写入 `llm_calls`。

### Agent

`SentimentAgent`：输出 `sentiment`（-1 到 1）、`confidence`（0 到 1）、`summary`、`key_events`、`item_ids`。

- 模型返回的 `item_ids` 中，不属于本批内容的 id 会被丢弃并记录警告。
- LLM 失败或多次输出不合格时，结果为 `sentiment=0, confidence=0` 并带上 `error`，下游视为"没有信息"。
- 各 agent 的区别在人格（persona）和 `params.instructions`，共用同一个模板 `configs/agents/prompts/sentiment_v1.j2`。模板把帖子明确标为不可信的用户内容，要求模型只当作数据分析，忽略其中的指令。
- 仓库自带两个 agent：`retail_mood`（散户情绪）和 `event_extractor`（事件提取）。它们的配置里没有指定模型，**模型在流水线配置的 agent 引用中指定**（见下文）。

### 数据源（插件式）

| 名称 | 说明 | 凭据（环境变量） |
|---|---|---|
| `reddit` | 官方 API（asyncpraw，只读）。`mode: search` 按子版块逐个标的搜索、按时间倒序；`mode: new` 每个子版块拉一次最新列表，在本地筛选（请求更少）。置顶帖会被过滤，NSFW 帖默认过滤（`include_nsfw`）。 | `REDDIT_CLIENT_ID`、`REDDIT_CLIENT_SECRET`、`REDDIT_USER_AGENT` |
| `ibkr_news` | IBKR 新闻：通过 `ib_async` 建立自己的只读连接，client id 默认为 `IBKR_CLIENT_ID + 2`。按标的拉取历史新闻标题；`fetch_bodies: true` 时每篇文章再多发一个请求拿正文（截断到 `max_body_chars`）。默认使用账户能访问的全部新闻源，API 自带免费的 Briefing.com（BRFG、BRFUPDN）和 Dow Jones（DJNL）。标题前缀里 IBKR 自带的情绪分数会存入 metadata。IBKR 返回的时间不带时区，按 UTC 处理。 | 使用 `IBKR_HOST` / `IBKR_PORT` / `IBKR_CLIENT_ID`，也可以在 options 里写 `host` / `port` / `client_id` |
| `stocktwits` | 按标的拉取消息流。个别标的失败只记录警告，全部失败才报错。公开 API 有限流，而且对新用户越来越不稳定，只能算尽力而为。 | `STOCKTWITS_ACCESS_TOKEN`（可选） |

不写 `sources` 时，默认只用 `[reddit, stocktwits]`。

**判断帖子是否提到某个标的**：
- `$AAPL` 任何大小写都算。
- 不带 `$` 的 `AAPL` 只有大写时才算。
- 像 `ON`、`IT`、`ALL` 这类同时是常用词的代码，只认 `$` 前缀的写法。
- 在 `aliases` 里配置的公司名（如 `Apple`）按整词匹配。

**新增数据源**：
1. 写一个类，提供 `name` 和 `async fetch(symbols, since) -> list[SentimentItem]`，以及可选的 `aclose()`。
2. 在 `pyproject.toml` 的 `quant.sentiment_sources` entry point 中注册工厂函数 `factory(options: dict) -> source`。
3. 在流水线配置的 `sources` 中写上它的名字。

主流程不需要改动。

### 配置项

```yaml
- type: sentiment
  on_error: skip
  sources: [reddit, stocktwits, ibkr_news]
  source_options:
    ibkr_news: { max_headlines: 20, fetch_bodies: false, providers: null }
    reddit: { subreddits: [stocks, investing, wallstreetbets], mode: search, limit: 50,
              min_upvotes: 0, aliases: { AAPL: [Apple] } }
    stocktwits: { min_likes: 0 }
  lookback_hours: 24
  min_sources_ok: 1
  prefilter: { max_items_per_symbol: 20, max_chars_per_item: 800, min_chars: 15, min_score: 0 }
  agents:                              # 在这里为每个实例指定模型
    - { agent: retail_mood, count: 1, model: { provider: anthropic, name: claude-opus-5 } }
    - { agent: event_extractor, count: 1, model: { provider: deepseek, name: deepseek-chat } }
```

阶段工厂 `build_sentiment_stage(config, services)` 需要的服务：
- `repos`
- `config_store`（`ConfigStore`）
- `llm`（`LLMClientPool`）
- `sentiment_sources`（可选，`{name: source}`）：用于覆盖注册的数据源，例如测试或离线运行时换成假数据源。

阶段用完后调用 `aclose()`，关闭各数据源的网络连接。

### 运行测试

```bash
python tasks.py test-sentiment
```

---

## English

Sentiment: collects posts and news headlines from Reddit, Stocktwits and IBKR news, has several sentiment agents analyse them, and stores the results. Depends on `quant-core` and `quant-database`.

### Flow (`sentiment` stage)

1. **Collect**: all sources fetch the last `lookback_hours` (default 24) concurrently. A failing source only logs a warning; the stage fails when fewer than `min_sources_ok` (default 1) sources succeed.
2. **Store**: raw items go to `sentiment_items`, deduplicated by `(source, external_id, symbol)`.
3. **Read the window**: every item in `[as_of - lookback, as_of]` is read from the database, including items collected by earlier runs or other pipelines; nothing published after `as_of` is used.
4. **Prefilter** (deterministic code, no LLM):
   - Drops bot accounts (`bot_authors` list and `bot_name_pattern`), posts that are too short (`min_chars`) or low-scored (`min_score`), duplicates and copy-paste spam.
   - Ranks items within each source by engagement with time decay (half-life `half_life_hours`, default 12), then takes items from the sources in turn until each symbol has `max_items_per_symbol`. News has no upvotes; this keeps it from being crowded out by popular posts.
   - Cleans text: collapses whitespace, replaces links with `[link]`, turns `<` `>` into `‹` `›` (so a post cannot forge the prompt's delimiter tags), truncates to `max_chars_per_item`.
5. **Analyse**: every agent instance calls the LLM once per symbol that has items; all calls run concurrently within each LLM vendor's concurrency limit. Symbols without items get no LLM call.
6. **Write**: results go to `sentiment_results` and `PipelineContext.sentiment_results`; agent instances are registered in `agent_instances`; every LLM call's raw input and output go to `llm_calls`.

### Agent

`SentimentAgent` outputs `sentiment` (-1 to 1), `confidence` (0 to 1), `summary`, `key_events` and `item_ids`.

- `item_ids` that do not belong to the batch are dropped with a warning.
- When the LLM fails or keeps producing invalid output, the result is `sentiment=0, confidence=0` with an `error`; downstream treats it as "no information".
- Agents differ only in persona and `params.instructions` and share the template `configs/agents/prompts/sentiment_v1.j2`, which marks posts as untrusted user content and tells the model to analyse them as data and ignore any instructions in them.
- The repository ships two agents: `retail_mood` (retail mood) and `event_extractor` (event extraction). Their configs set no model; **the model is chosen in the pipeline's agent reference** (see below).

### Sources (plug-ins)

| Name | Description | Credentials (environment) |
|---|---|---|
| `reddit` | Official API (asyncpraw, read-only). `mode: search` searches each subreddit per symbol, newest first; `mode: new` fetches each subreddit's newest list once and filters locally (fewer requests). Stickied posts are dropped; NSFW posts are dropped by default (`include_nsfw`). | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` |
| `ibkr_news` | IBKR news over its own read-only `ib_async` connection, client id `IBKR_CLIENT_ID + 2` by default. Fetches historical headlines per symbol; `fetch_bodies: true` adds one request per article for the body (truncated to `max_body_chars`). Uses every news provider the account can access by default; the API includes Briefing.com (BRFG, BRFUPDN) and Dow Jones (DJNL) for free. IBKR's own sentiment score in the headline prefix is kept in metadata. IBKR returns naive timestamps, which are treated as UTC. | Uses `IBKR_HOST` / `IBKR_PORT` / `IBKR_CLIENT_ID`, or `host` / `port` / `client_id` in the options |
| `stocktwits` | Message stream per symbol. A failing symbol only logs a warning; the source fails only if all fail. The public API is rate-limited and increasingly unreliable for new users — best effort only. | `STOCKTWITS_ACCESS_TOKEN` (optional) |

Without `sources`, the default is `[reddit, stocktwits]`.

**When does a post mention a symbol?**
- `$AAPL` in any case.
- `AAPL` without `$` only in upper case.
- Tickers that are common words (`ON`, `IT`, `ALL`...) only with the `$` prefix.
- Company names configured in `aliases` (e.g. `Apple`) as whole words.

**Adding a source**:
1. Write a class with `name` and `async fetch(symbols, since) -> list[SentimentItem]`, plus an optional `aclose()`.
2. Register a factory `factory(options: dict) -> source` under the `quant.sentiment_sources` entry point in `pyproject.toml`.
3. Add its name to `sources` in the pipeline config.

The main flow needs no change.

### Configuration

```yaml
- type: sentiment
  on_error: skip
  sources: [reddit, stocktwits, ibkr_news]
  source_options:
    ibkr_news: { max_headlines: 20, fetch_bodies: false, providers: null }
    reddit: { subreddits: [stocks, investing, wallstreetbets], mode: search, limit: 50,
              min_upvotes: 0, aliases: { AAPL: [Apple] } }
    stocktwits: { min_likes: 0 }
  lookback_hours: 24
  min_sources_ok: 1
  prefilter: { max_items_per_symbol: 20, max_chars_per_item: 800, min_chars: 15, min_score: 0 }
  agents:                              # each instance's model is chosen here
    - { agent: retail_mood, count: 1, model: { provider: anthropic, name: claude-opus-5 } }
    - { agent: event_extractor, count: 1, model: { provider: deepseek, name: deepseek-chat } }
```

Services needed by the stage factory `build_sentiment_stage(config, services)`:
- `repos`
- `config_store` (`ConfigStore`)
- `llm` (`LLMClientPool`)
- `sentiment_sources` (optional, `{name: source}`): overrides the registered sources, e.g. with fakes in tests or offline runs.

The stage's `aclose()` closes every source's network connections when done.

### Running tests

```bash
python tasks.py test-sentiment
```
