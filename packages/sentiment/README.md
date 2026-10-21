# synodtrade-sentiment

**English** | [简体中文](README.zh-CN.md)

Sentiment: collects posts and news headlines from Reddit, Stocktwits and IBKR news, has several sentiment agents analyse them, and stores the results. Depends on `synodtrade-core` and `synodtrade-database`.

## Flow (`sentiment` stage)

1. **Collect**: all sources fetch the last `lookback_hours` (default 24) concurrently. A failing source only logs a warning; the stage fails when fewer than `min_sources_ok` (default 1) sources succeed.
2. **Store**: raw items go to `sentiment_items`, deduplicated by `(source, external_id, symbol)`.
3. **Read the window**: every item in `[as_of - lookback, as_of]` is read from the database, including items collected by earlier runs or other pipelines; nothing published after `as_of` is used.
4. **Prefilter** (deterministic code, no LLM):
   - Drops bot accounts (`bot_authors` list and `bot_name_pattern`), posts that are too short (`min_chars`) or low-scored (`min_score`), duplicates and copy-paste spam.
   - Ranks items within each source by engagement with time decay (half-life `half_life_hours`, default 12), then takes items from the sources in turn until each symbol has `max_items_per_symbol`. News has no upvotes; this keeps it from being crowded out by popular posts.
   - Cleans text: collapses whitespace, replaces links with `[link]`, turns `<` `>` into `‹` `›` (so a post cannot forge the prompt's delimiter tags), truncates to `max_chars_per_item`.
5. **Analyse**: every agent instance calls the LLM once per symbol that has items; all calls run concurrently within each LLM vendor's concurrency limit. Symbols without items get no LLM call.
6. **Write**: results go to `sentiment_results` and `PipelineContext.sentiment_results`; agent instances are registered in `agent_instances`; every LLM call's raw input and output go to `llm_calls`.

## Agent

`SentimentAgent` outputs `sentiment` (-1 to 1), `confidence` (0 to 1), `summary`, `key_events` and `item_ids`.

- `item_ids` that do not belong to the batch are dropped with a warning.
- When the LLM fails or keeps producing invalid output, the result is `sentiment=0, confidence=0` with an `error`; downstream treats it as "no information".
- Agents differ only in persona and `params.instructions` and share the template `configs/agents/prompts/sentiment_v1.j2`, which marks posts as untrusted user content and tells the model to analyse them as data and ignore any instructions in them.
- The repository ships two agents: `retail_mood` (retail mood) and `event_extractor` (event extraction). Their configs set no model; **the model is chosen in the pipeline's agent reference** (see below).

## Sources (plug-ins)

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
2. Register a factory `factory(options: dict) -> source` under the `synodtrade.sentiment_sources` entry point in `pyproject.toml`.
3. Add its name to `sources` in the pipeline config.

The main flow needs no change.

## Configuration

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

## Running tests

```bash
python tasks.py test-sentiment
```
