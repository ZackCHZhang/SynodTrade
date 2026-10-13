// Thin fetch wrapper + typed endpoints of the quant-web API (packages/webapi).

export class ApiError extends Error {
  status: number;
  body: any;
  constructor(status: number, message: string, body: any) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    let message = typeof data === 'object' && data?.detail ? data.detail : `${res.status} ${res.statusText}`;
    if (Array.isArray(message)) message = message.map((d: any) => `${(d.loc ?? []).join('.')}: ${d.msg}`).join('; ');
    throw new ApiError(res.status, String(message), data);
  }
  return data as T;
}

export const http = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body ?? {}),
  put: <T>(url: string, body?: unknown) => request<T>('PUT', url, body ?? {}),
  del: <T>(url: string) => request<T>('DELETE', url),
};

// ------------------------------------------------------------------ types

export interface KindInfo {
  name: string;
  label: string;
  single: boolean;
  ext: string;
  yaml: boolean;
  key: string | null;
  name_pattern: string;
}

export type JsonSchema = Record<string, any>;

export interface Meta {
  kinds: KindInfo[];
  stage_order: string[];
  stage_roles: Record<string, string>;
  agent_roles: string[];
  run_modes: string[];
  timeframes: string[];
  registry: { stages: string[]; agents: string[]; sentiment_sources: string[]; candidate_sources: string[] };
  schemas: {
    pipeline: JsonSchema;
    agent: JsonSchema;
    account: JsonSchema;
    risk: JsonSchema;
    llm_provider: JsonSchema;
    llm_model: JsonSchema;
    schedules: JsonSchema;
    job: JsonSchema;
    account_sync: JsonSchema;
    stages: Record<string, JsonSchema>;
    candidate_sources: Record<string, JsonSchema>;
    sentiment_sources: Record<string, JsonSchema>;
  };
  stage_common_keys: string[];
  env: Record<string, boolean>;
  configs_root: string;
  database: { dialect: string };
  offline_db: boolean;
}

export interface ConfigEntry {
  name: string;
  path: string;
  size: number;
  modified: string;
  role?: string;
  prompt_template?: string;
  avatar?: string | null;
  mode?: string;
  account?: string;
  stages?: string[];
  universe_size?: number;
  broken?: boolean;
}

export type ConfigList = Record<string, ConfigEntry[]>;

export interface ConfigFile {
  kind: string;
  name: string;
  path: string;
  text: string;
  etag: string;
  used_by: string[];
}

export interface Problem {
  message: string;
  loc: (string | number)[];
  line: number | null;
}

export interface Diagnostics {
  ok: boolean;
  errors: Problem[];
  warnings: Problem[];
  info: Record<string, any>;
}

export interface RunRequest {
  pipeline: string;
  mode: 'config' | 'dry_run' | 'paper';
  offline: boolean;
  offline_llm: 'neutral' | 'bullish';
  stages: string[] | null;
  as_of: string | null;
}

export interface Job {
  id: string;
  pipeline: string;
  request: RunRequest;
  status: 'starting' | 'running' | 'succeeded' | 'failed' | 'error' | 'cancelled';
  run_id: string | null;
  created_at: string;
  finished_at: string | null;
  error: string | null;
  summary: RunSummary | null;
  database: 'main' | 'offline';
}

export interface StageTiming {
  status: string;
  seconds?: number;
  started?: string;
}

export interface RunSummary {
  mode: string;
  as_of: string;
  stages: Record<string, StageTiming>;
  universe: string[];
  selection?: { method: string; candidates: number; selected: string[]; holdings: string[]; scores: Record<string, number> };
  sentiment_results: number;
  decisions: number;
  final_decisions: Record<string, string>;
  risk: Record<string, string>;
  orders: Record<string, string>;
  errors: { stage: string; error_type: string; message: string; skipped: boolean }[];
}

export interface RunLight {
  run_id: string;
  pipeline_name: string;
  mode: string;
  status: 'running' | 'succeeded' | 'failed';
  as_of: string;
  started_at: string;
  ended_at: string | null;
  error: string | null;
  summary: RunSummary | null;
  stages_run: string[];
  offline: boolean;
  config_hash: string;
  live?: boolean;
}

export interface RunDetail {
  run: RunLight & { config: any };
  agent_instances: any[];
  selection_results: any[];
  stock_selection: any | null;
  sentiment_results: any[];
  decisions: any[];
  aggregated_decisions: any[];
  risk_assessments: any[];
  orders: any[];
  llm_calls: any[];
  live: boolean;
  has_events: boolean;
  progress: Record<string, StageTiming>;
  database: 'main' | 'offline';
}

export interface RunEvent {
  seq: number;
  event: string;
  level: string;
  ts: string;
  ts_local?: string;
  stage?: string;
  [key: string]: any;
}

export interface ColumnInfo {
  name: string;
  kind: string;
  primary_key: boolean;
  foreign_key: string | null;
  nullable: boolean;
}

export interface TableInfo {
  name: string;
  rows: number;
  columns: ColumnInfo[];
}

export interface RowsPage {
  table: string;
  primary_key: string;
  columns: ColumnInfo[];
  total: number;
  rows: { cells: Record<string, any>; truncated: string[] }[];
}

export interface Filter {
  column: string;
  op: string;
  value?: string;
}

export interface Overview {
  database: { url: string; dialect: string };
  kill_switch: { active: boolean; reason: string | null };
  runs_by_status: Record<string, number>;
  pipelines: Record<string, { runs: number; last_started: string | null }>;
  open_orders: number;
  recent_runs: RunLight[];
  scheduler: SchedulerStatus;
  jobs: Job[];
  account_sync: AccountSyncLoop & { latest: AccountSyncRecord[] };
}

export interface Times {
  utc: string | null;
  new_york: string | null;
  berlin: string | null;
}

export interface SchedulerStatus {
  running: boolean;
  started_at: string | null;
  jobs: { id: string; pipeline: string; trigger: string; dry_run: boolean; next_run: Times }[];
}

export interface SchedulePlan {
  calendar: string;
  timezone: string;
  days: number;
  jobs: { id: string; config: any; trigger: string; upcoming: Times[] }[];
}

export interface AccountSyncConfig {
  enabled: boolean;
  interval_minutes: number;
  before_pipeline: boolean;
  required_before_pipeline: boolean;
  gone_after_minutes: number;
  recheck_days: number;
  snapshot: boolean;
  accounts: string[];
}

export interface OrderChange {
  client_order_id: string;
  pipeline: string;
  run_id: string;
  symbol: string;
  side: string;
  quantity: number;
  from_status: string;
  to_status: string;
  filled_qty: number;
  avg_fill_price: number | null;
  new_fills: number;
  message: string | null;
}

export interface AccountSyncReport {
  account_names?: string[];
  pipelines?: string[];
  orders?: OrderChange[];
  late_fills?: OrderChange[];
  waiting?: { client_order_id: string; pipeline: string; symbol: string; status: string; since: string }[];
  skipped_running?: string[];
  untracked_open_orders?: {
    ref: string | null;
    symbol: string;
    side: string;
    quantity: number;
    filled: number;
    limit_price: number | null;
    status: string;
    perm_id: number | null;
  }[];
  positions?: { symbol: string; broker_qty: number; ledger_qty: number; pipelines: Record<string, number>; state: 'ok' | 'broker_more' | 'broker_less' }[];
  account?: {
    ts: string;
    currency: string;
    nav: number;
    cash: number;
    buying_power: number;
    available_funds: number | null;
    positions: { symbol: string; qty: number; avg_cost: number; market_price: number | null }[];
  } | null;
  warnings?: string[];
  errors?: string[];
}

export interface AccountSyncRecord {
  id: number;
  account_id: string;
  trigger: 'pipeline' | 'auto' | 'manual' | 'cli' | string;
  pipeline_name: string | null;
  run_id: string | null;
  started_at: string;
  finished_at: string;
  status: 'ok' | 'partial' | 'failed';
  orders_checked: number;
  orders_updated: number;
  fills_added: number;
  error: string | null;
  report?: AccountSyncReport;
}

export interface AccountSyncLoop {
  running: boolean;
  syncing: boolean;
  last_started: string | null;
  last_finished: string | null;
  last_error: string | null;
  next_due: string | null;
  config: AccountSyncConfig | null;
  config_error: string | null;
}

export interface AccountSyncStatus extends AccountSyncLoop {
  accounts: { account_id: string; account_names: string[]; pipelines: string[] }[];
  latest: AccountSyncRecord[];
  history: AccountSyncRecord[];
}

export interface Bar {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Portfolio {
  pipelines: any[];
  accounts: any[];
  orders: any[];
}

// ------------------------------------------------------------------ endpoints

const q = (params: Record<string, string | number | boolean | undefined | null>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') s.set(k, String(v));
  const text = s.toString();
  return text ? `?${text}` : '';
};

export type WatchlistEntry = {
  pipeline_name: string;
  symbol: string;
  added_at: string;
  last_selected_at: string | null;
  times_selected: number;
  last_score: number | null;
  last_reason: string | null;
  pinned: boolean;
  note: string | null;
  removed_at: string | null;
  removed_reason: string | null;
  active: boolean;
};

export const api = {
  meta: () => http.get<Meta>('/api/meta'),
  configs: () => http.get<ConfigList>('/api/configs'),
  config: (kind: string, name: string) => http.get<ConfigFile>(`/api/configs/${kind}/${encodeURIComponent(name)}`),
  validate: (kind: string, name: string, text: string) =>
    http.post<Diagnostics>(`/api/configs/${kind}/${encodeURIComponent(name)}/validate`, { text }),
  save: (kind: string, name: string, text: string, etag: string | null, force = false) =>
    http.put<ConfigFile>(`/api/configs/${kind}/${encodeURIComponent(name)}`, { text, etag, force }),
  create: (kind: string, name: string, text: string, force = false) =>
    http.post<ConfigFile>(`/api/configs/${kind}`, { name, text, force }),
  remove: (kind: string, name: string) => http.del<{ deleted: string }>(`/api/configs/${kind}/${encodeURIComponent(name)}`),

  startJob: (req: RunRequest) => http.post<Job>('/api/jobs', req),
  jobs: () => http.get<Job[]>('/api/jobs'),
  cancelJob: (id: string) => http.post<Job>(`/api/jobs/${id}/cancel`),

  runs: (p: { pipeline?: string; status?: string; offset?: number; limit?: number; db?: string }) =>
    http.get<{ total: number; runs: RunLight[] }>(`/api/runs${q(p)}`),
  run: (id: string) => http.get<RunDetail>(`/api/runs/${id}`),
  llmCall: (id: string) => http.get<any>(`/api/llm_calls/${id}`),

  tables: (db = 'main') => http.get<TableInfo[]>(`/api/db/tables?db=${db}`),
  rows: (table: string, p: { offset: number; limit: number; sort?: string; desc?: boolean; filters?: Filter[]; db?: string }) =>
    http.get<RowsPage>(
      `/api/db/tables/${table}${q({
        offset: p.offset,
        limit: p.limit,
        sort: p.sort,
        desc: p.desc,
        filters: p.filters && p.filters.length ? JSON.stringify(p.filters) : undefined,
        db: p.db,
      })}`,
    ),
  row: (table: string, pk: string, db = 'main') =>
    http.get<Record<string, any>>(`/api/db/tables/${table}/rows/${encodeURIComponent(pk)}?db=${db}`),

  instruments: () => http.get<{ symbol: string; timeframes: Record<string, { bars: number; first: string; last: string }> }[]>('/api/market/instruments'),
  bars: (symbol: string, timeframe: string, limit: number) =>
    http.get<{ symbol: string; timeframe: string; bars: Bar[]; quotes: any[] }>(`/api/market/bars${q({ symbol, timeframe, limit })}`),
  portfolio: () => http.get<Portfolio>('/api/portfolio'),
  watchlists: () => http.get<{ pipeline: string; entries: WatchlistEntry[] }[]>('/api/watchlists'),
  watchlistAdd: (pipeline: string, body: { symbol: string; pinned: boolean; note: string | null }) =>
    http.post<WatchlistEntry>(`/api/watchlists/${encodeURIComponent(pipeline)}`, body),
  watchlistRemove: (pipeline: string, symbol: string) =>
    http.del<{ removed: string }>(`/api/watchlists/${encodeURIComponent(pipeline)}/${encodeURIComponent(symbol)}`),
  overview: () => http.get<Overview>('/api/overview'),

  killSwitch: () => http.get<{ active: boolean; reason: string | null }>('/api/system/kill-switch'),
  setKillSwitch: (active: boolean, reason: string | null) =>
    http.put<{ active: boolean; reason: string | null }>('/api/system/kill-switch', { active, reason }),

  accountSync: (history = 50) => http.get<AccountSyncStatus>(`/api/account-sync?history=${history}`),
  accountSyncRun: () => http.post<AccountSyncRecord[]>('/api/account-sync/run'),

  schedulerPlan: (days: number) => http.get<SchedulePlan>(`/api/scheduler/plan?days=${days}`),
  schedulerStatus: () => http.get<SchedulerStatus>('/api/scheduler/status'),
  schedulerAction: (action: 'start' | 'stop' | 'reload') => http.post<SchedulerStatus>(`/api/scheduler/${action}`),
  schedulerCheck: () => http.post<{ pipeline: string; ok: boolean; problems: string[] }[]>('/api/scheduler/check'),
};
