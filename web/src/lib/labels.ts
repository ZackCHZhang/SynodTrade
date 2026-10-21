import { t } from '../i18n';

// Labels and help texts for config keys, in English; t() translates them. Unknown keys fall back to the key itself.

type Entry = [label: string, help?: string];

const L: Record<string, Entry> = {
  // pipeline
  name: ['Name'],
  mode: ['Run mode', 'dry_run only records; paper places orders on the paper account; live trades real money (also needs SYNODTRADE_ALLOW_LIVE=1)'],
  account: ['Account'],
  universe: ['Universe', 'Part of the candidate pool when there is a selection stage'],
  benchmark: ['Market benchmark', 'e.g. SPY: data_update refreshes its daily bars; later stages show market regime, beta and relative strength. Leave empty to disable'],
  budget: ['Budget'],
  max_capital: ['Capital cap', 'Capital of this pipeline\'s virtual sub-ledger'],
  currency: ['Currency'],
  sizing: ['Position sizing'],
  buy_base: ['Buy base', 'available_cash: 15%/30% of available cash; nav: of net asset value'],
  min_one_lot_on_sell: ['Sell at least one lot', 'Sell one lot when a sell tier rounds down to 0'],
  lot_size: ['Lot size'],
  stages: ['Stages'],
  // stage common
  type: ['Type'],
  enabled: ['Enabled'],
  on_error: ['On error', 'abort: stop the whole run; skip: record the error and continue'],
  agents: ['Agent instances'],
  // selection
  sources: ['Sources'],
  include_universe: ['Include universe', 'Use the pipeline universe as one candidate source'],
  keep_holdings: ['Keep holdings', 'Held stocks always stay in the universe so they can still be sold after dropping out'],
  max_raw_candidates: ['Max raw candidates', 'Limits how many symbols get bars fetched'],
  timeframe: ['Bar timeframe'],
  lookback_days: ['Lookback days'],
  bars_lookback: ['Bars to load', 'Used to compute indicators (SMA 200, 52-week range)'],
  refresh_bars: ['Refresh bars'],
  screen: ['Quant screen'],
  min_bars: ['Min bars'],
  min_price: ['Min price'],
  max_price: ['Max price'],
  min_avg_dollar_volume: ['Min avg dollar volume', 'Mean of close × volume over the last 20 bars'],
  max_volatility: ['Max volatility', '60-day annualized, e.g. 0.8'],
  max_candidates: ['Max candidates', 'Number of candidates shown to agents'],
  aggregation: ['Aggregation'],
  method: ['Method'],
  top_n: ['Picks'],
  min_score: ['Min score'],
  max_picks_per_agent: ['Max picks per agent'],
  fallback: ['Fallback', 'When every agent fails: previous reuses the last selection; holdings keeps only holdings; fail fails'],
  // scanner / static
  host: ['Host'],
  port: ['Port'],
  client_id: ['Client ID'],
  scan_code: ['Scan code', 'e.g. MOST_ACTIVE, TOP_PERC_GAIN, HOT_BY_VOLUME'],
  instrument: ['Instrument'],
  location: ['Location'],
  rows: ['Rows returned'],
  above_price: ['Price above'],
  below_price: ['Price below'],
  above_volume: ['Volume above'],
  market_cap_above: ['Market cap above (USD millions)'],
  market_cap_below: ['Market cap below (USD millions)'],
  stock_type: ['Stock type', 'ALL, CORP (common stock), ADR, ETF, REIT, CEF'],
  filters: ['Extra filter tags'],
  connect_timeout_s: ['Connect timeout (s)'],
  symbols: ['Symbols'],
  note: ['Note'],
  // data update
  timeframes: ['Bar timeframes'],
  quotes: ['Quote snapshots'],
  fail_on_error: ['Fail on any error', 'Fail the stage if any symbol fails to update'],
  fundamentals: ['Fundamentals', 'Fetch fundamentals from SEC EDGAR filings (needs SEC_EDGAR_USER_AGENT in .env); failures do not affect the stage'],
  fundamentals_max_age_hours: ['Fundamentals refresh (hours)', 'Refetch only when stored fundamentals are older than this'],
  stored_sentiment_hours: ['Stored sentiment (hours)', 'When this run has no sentiment results, use stored analyses from the last N hours; 0 disables'],
  // sentiment
  source_options: ['Source options'],
  lookback_hours: ['Lookback hours'],
  prefilter: ['Prefilter'],
  max_items_per_symbol: ['Max items per symbol', 'Token control: at most this many posts per symbol per agent'],
  max_chars_per_item: ['Max chars per item'],
  min_chars: ['Min chars'],
  bot_authors: ['Bot authors'],
  bot_name_pattern: ['Bot name regex'],
  half_life_hours: ['Half-life (hours)', 'How fast a post\'s ranking weight decays over time'],
  min_sources_ok: ['Min successful sources'],
  subreddits: ['Subreddits'],
  limit: ['Items per request'],
  min_upvotes: ['Min upvotes'],
  include_nsfw: ['Include NSFW'],
  aliases: ['Aliases', 'e.g. AAPL: [Apple]'],
  providers: ['Providers'],
  max_headlines: ['Max headlines'],
  fetch_bodies: ['Fetch article bodies', 'One extra request per article'],
  max_body_chars: ['Max body chars'],
  // decision
  min_confidence: ['Min confidence', 'Decisions below this confidence count as hold'],
  recent_bars_in_prompt: ['Bars in prompt'],
  history_limit: ['Decision history', 'This strategy\'s past final decisions shown to the agent (execution results and subsequent price moves)'],
  // risk stage
  rules: ['Risk rules', 'configs/risk/<name>.yaml; hard rules run before risk agents'],
  combine: ['Combine', 'most_conservative takes the most conservative; median takes the median'],
  on_agent_failure: ['On agent failure', 'reject rejects (safe); approve lets it through'],
  max_quote_age_minutes: ['Max quote age (minutes)', 'Older quotes are ignored in favor of the last close'],
  // trading
  order_type: ['Order type'],
  limit_offset_bps: ['Limit offset (bp)', 'Added to the ask for buys, subtracted from the bid for sells'],
  time_in_force: ['Time in force'],
  cancel_after_minutes: ['Cancel unfilled after (minutes)'],
  poll_interval_seconds: ['Poll interval (s)'],
  wait_for_fills: ['Wait for fills'],
  // agent
  agent_id: ['Agent ID'],
  role: ['Role'],
  impl: ['Implementation', 'Implementation name in the registry; defaults to the role'],
  prompt_version: ['Prompt version'],
  model: ['Model'],
  persona: ['Persona (system prompt)'],
  prompt_template: ['Prompt template'],
  params: ['Parameters'],
  instructions: ['Strategy instructions', 'Inserted into the instructions variable of the prompt template'],
  provider: ['LLM provider'],
  max_tokens: ['Max output tokens'],
  temperature: ['Temperature', 'The latest Claude models do not accept sampling parameters; leave empty'],
  effort: ['Reasoning effort'],
  max_validation_attempts: ['Structured output retries'],
  agent: ['Agent'],
  count: ['Instances', '>1 creates several independent instances'],
  weight: ['Weight'],
  // account
  broker: ['Broker'],
  account_id: ['Account number', 'Prefer ${IBKR_ACCOUNT} and keep the real account number in .env'],
  base_currency: ['Base currency'],
  // risk rules
  kill_switch: ['Kill switch', 'When on, every order becomes HOLD (same as the global switch in the database)'],
  max_position_pct: ['Max position size', 'Share of the strategy\'s NAV, 0.2 = 20%'],
  max_gross_exposure_pct: ['Max gross exposure', '0.9 = 90%'],
  min_cash_pct: ['Min cash ratio'],
  max_daily_loss_pct: ['Max daily loss', 'Once hit, only HOLD/SELL for the rest of the day'],
  max_weekly_loss_pct: ['Max weekly loss'],
  max_trades_per_day: ['Max trades per day'],
  max_order_notional: ['Max order notional', 'null means no limit'],
  one_order_per_symbol_per_day: ['One order per symbol per day'],
  whitelist: ['Whitelist', 'Empty allows the whole universe'],
  blacklist: ['Blacklist'],
  liquidity: ['Liquidity'],
  max_spread_bps: ['Max bid-ask spread (bp)'],
  min_avg_volume: ['Min 20-day avg volume (shares)'],
  require_quote: ['Require two-sided quote'],
  trading_hours: ['Trading hours'],
  calendar: ['Trading calendar'],
  watchlist: ['Watchlist', 'When on, picks join a watchlist and are tracked over time instead of replacing the universe on every run'],
  max_age_days: ['Max age (days)', 'Removed after this many days without being picked again (pinned and held symbols stay)'],
  max_size: ['Max symbols', 'When exceeded, the longest-unpicked symbols are removed'],
  scan_codes: ['Scan lists', 'Runs several IBKR scans in one connection, e.g. TOP_PERC_GAIN, HOT_BY_VOLUME, HIGH_VS_52W_HL; replaces scan_code when set'],
  hold_weight: ['HOLD vote weight', 'HOLD votes are weighted by this factor; 0.5 = half, so "I don\'t see my setup" does not fully cancel other agents\' buy votes'],
  position_check: ['Position check', 'When real broker holdings are less than the sum of strategy sub-ledgers, the symbol cannot be traded'],
  max_snapshot_age_minutes: ['Max account snapshot age (minutes)', 'Older snapshots are not checked'],
  // providers
  kind: ['API type', 'anthropic: Anthropic Messages API; openai_compatible: OpenAI Chat Completions compatible API'],
  base_url: ['Base URL', 'Leave empty to use the SDK default'],
  api_key_env: ['API key env var', 'Only the variable name; keep the key itself in .env'],
  max_concurrency: ['Max concurrency'],
  max_attempts: ['Max attempts'],
  timeout_s: ['Timeout (s)'],
  structured_output: ['Structured output mode'],
  max_tokens_param: ['max_tokens parameter name'],
  extra_headers: ['Extra headers'],
  extra_body: ['Extra body fields'],
  // schedules
  timezone: ['Time zone'],
  jobs: ['Jobs'],
  pipeline: ['Pipeline'],
  trigger: ['Trigger', 'market_relative: relative to the open/close; cron: crontab in the exchange time zone'],
  anchor: ['Anchor'],
  offset_minutes: ['Offset (minutes)', 'Positive is after, negative is before'],
  cron: ['Cron expression', '5 fields, e.g. 0 11 * * MON'],
  skip_non_trading_days: ['Skip non-trading days'],
  dry_run: ['Dry run'],
  misfire_grace_minutes: ['Misfire grace (minutes)'],
};

export function label(key: string | number): string {
  const e = L[String(key)];
  return e ? t(e[0]) : String(key);
}

/** A field label followed by its YAML key, unless the key only repeats the label ("Name" / name). */
export function withKey(text: string, key: string): string {
  const l = t(text);
  return l.toLowerCase().replace(/ /g, '_').endsWith(key) ? l : `${l} ${key}`;
}

export function help(key: string | number): string | undefined {
  const h = L[String(key)]?.[1];
  return h ? t(h) : undefined;
}

export const STAGE_INFO: Record<string, { label: string; color: string; desc: string }> = {
  account_sync: { label: 'Account sync', color: '#546e7a', desc: 'Sync order fills, positions and account state from IBKR before the run' },
  selection: { label: 'Selection', color: '#8e24aa', desc: 'Universe + scanners → quant screen → selection agents → aggregation' },
  data_update: { label: 'Market data', color: '#1e88e5', desc: 'IBKR historical bars, quote snapshots, account and position snapshots' },
  sentiment: { label: 'Sentiment', color: '#00897b', desc: 'Reddit / Stocktwits / IBKR news → sentiment agents' },
  decision: { label: 'Decision', color: '#f4511e', desc: 'Multi-instance decision agent votes → aggregated final action' },
  risk: { label: 'Risk', color: '#e53935', desc: 'Hard rules → risk agents (can only reduce risk)' },
  trading: { label: 'Trading', color: '#43a047', desc: 'Limit orders, idempotent placement, fill/cancel tracking' },
};

export function stageLabel(type: string): string {
  const info = STAGE_INFO[type];
  return info ? t(info.label) : type;
}

export function stageDesc(type: string): string {
  const info = STAGE_INFO[type];
  return info ? t(info.desc) : '';
}

const ROLE_LABEL: Record<string, string> = {
  selection: 'Selection',
  sentiment: 'Sentiment',
  decision: 'Decision',
  risk: 'Risk',
};

export function roleLabel(role: string | null | undefined): string {
  if (!role) return '';
  const l = ROLE_LABEL[role];
  return l ? t(l) : role;
}

export const ACTION_COLOR: Record<string, 'success' | 'error' | 'default' | 'warning' | 'info'> = {
  strong_buy: 'success',
  buy: 'success',
  hold: 'default',
  sell: 'error',
  strong_sell: 'error',
};
