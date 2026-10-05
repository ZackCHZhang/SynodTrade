import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { api, type ConfigEntry } from '../api/client';
import { useConfigs, useMeta } from '../api/hooks';
import { ConfigEditor } from '../components/ConfigEditor';
import { RunDialog } from '../components/RunDialog';
import { PageHeader } from '../components/common';
import { AgentForm } from '../editors/AgentForm';
import { AccountForm, ProvidersForm, RiskForm, SchedulesForm } from '../editors/OtherForms';
import { PipelineForm } from '../editors/PipelineForm';
import { fmtTime } from '../lib/format';
import { ROLE_LABEL, STAGE_INFO, stageLabel } from '../lib/labels';
import { applyJson, parseYaml } from '../lib/yamlDoc';

const FORMS: Record<string, React.ComponentType<any>> = {
  pipelines: PipelineForm,
  agents: AgentForm,
  accounts: AccountForm,
  risk: RiskForm,
  llm_providers: ProvidersForm,
  schedules: SchedulesForm,
};

const DESCRIPTIONS: Record<string, string> = {
  pipelines: '一条流水线 = 账户 + 资金 + 股票池 + 有序阶段（选股 → 行情 → 舆情 → 决策 → 风控 → 交易），每个阶段可实例化多个 agent。',
  agents: 'Agent = 角色 + 人设 + 提示词模板 + 策略说明。模型在流水线中实例化时选择。',
  prompts: 'Jinja2 提示词模板（configs/agents/prompts/），agent 通过 prompt_template 引用。',
  accounts: 'IBKR 连接参数。账户号和密钥写成 ${ENV} 引用，真实值放在 .env。',
  risk: '硬风控规则：在任何风控 agent 之前由确定性代码执行，LLM 无法覆盖。',
};

function template(kind: string, name: string, firstAccount?: string): string {
  switch (kind) {
    case 'pipelines':
      return `# 在 Web 控制台创建
name: ${name}
mode: dry_run                 # dry_run | paper | live
account: ${firstAccount ?? 'ibkr_main'}
universe: [AAPL, MSFT]
budget:
  max_capital: 10000
stages:
  - type: data_update
    timeframes: [1d]
    lookback_days: 365
  - type: decision
    agents: []
    aggregation: { method: weighted_vote, min_confidence: 0.6 }
  - type: risk
    rules: default
    agents: []
  - type: trading
    order_type: limit
    limit_offset_bps: 5
    cancel_after_minutes: 30
`;
    case 'agents':
      return `# 在 Web 控制台创建
agent_id: ${name}
role: decision
prompt_version: v1
persona: |
  You are ...
prompt_template: prompts/decision_v1.j2
params:
  instructions: >-
    ...
`;
    case 'prompts':
      return `Symbol: {{ symbol }}
Time (UTC): {{ as_of }}

{% if instructions -%}
## Your approach
{{ instructions }}
{% endif -%}
`;
    case 'accounts':
      return `# 在 Web 控制台创建；每条同时运行的流水线需要不同的 client_id
name: ${name}
broker: ibkr
account_id: \${IBKR_ACCOUNT}
host: \${IBKR_HOST:-127.0.0.1}
port: \${IBKR_PORT:-4002}
client_id: 37
base_currency: USD
`;
    case 'risk':
      return `# 在 Web 控制台创建
name: ${name}
kill_switch: false
max_position_pct: 0.20
max_gross_exposure_pct: 0.90
min_cash_pct: 0.10
max_daily_loss_pct: 0.03
max_weekly_loss_pct: 0.06
max_trades_per_day: 4
max_order_notional: 2000
one_order_per_symbol_per_day: true
whitelist: []
blacklist: []
liquidity:
  max_spread_bps: 50
  min_avg_volume: 100000
  require_quote: false
trading_hours:
  enabled: true
  calendar: XNYS
`;
    default:
      return '';
  }
}

function EntrySummary({ kind, e }: { kind: string; e: ConfigEntry }) {
  if (e.broken) return <Chip size="small" color="error" label="无法解析" />;
  if (kind === 'pipelines')
    return (
      <Stack spacing={1}>
        <Stack direction="row" sx={{ gap: 0.5, flexWrap: 'wrap' }}>
          <Chip size="small" variant="outlined" color={e.mode === 'live' ? 'error' : e.mode === 'paper' ? 'info' : 'default'} label={e.mode} />
          <Chip size="small" variant="outlined" label={e.account} />
          <Chip size="small" variant="outlined" label={`${e.universe_size} 只股票`} />
        </Stack>
        <Stack direction="row" sx={{ gap: 0.5, flexWrap: 'wrap' }}>
          {(e.stages ?? []).map((s) => (
            <Chip key={s} size="small" label={stageLabel(s)} sx={{ bgcolor: STAGE_INFO[s]?.color, color: '#fff' }} />
          ))}
        </Stack>
      </Stack>
    );
  if (kind === 'agents')
    return (
      <Stack direction="row" sx={{ gap: 0.5, flexWrap: 'wrap' }}>
        <Chip size="small" color="primary" variant="outlined" label={ROLE_LABEL[e.role ?? ''] ?? e.role} />
        <Chip size="small" variant="outlined" label={e.prompt_template} />
      </Stack>
    );
  return null;
}

export function ConfigListPage() {
  const { kind = 'pipelines' } = useParams();
  const { data: meta } = useMeta();
  const { data: configs } = useConfigs();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const info = meta?.kinds.find((k) => k.name === kind);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [base, setBase] = useState('');
  const [runFor, setRunFor] = useState<string | null>(null);
  const entries = configs?.[kind] ?? [];

  const create = useMutation({
    mutationFn: async () => {
      let text = template(kind, newName, configs?.accounts?.[0]?.name);
      if (base) {
        const src = await api.config(kind, base);
        text = src.text;
        if (info?.key) {
          const parsed = parseYaml(text);
          if (parsed.data) text = applyJson(text, { ...parsed.data, [info.key]: newName });
        }
      }
      return api.create(kind, newName, text, true);
    },
    onSuccess: (f) => {
      qc.invalidateQueries({ queryKey: ['configs'] });
      setCreating(false);
      navigate(`/configs/${kind}/${f.name}`);
    },
  });

  if (info?.single) return <Navigate to={`/configs/${kind}/${kind}`} replace />;
  const valid = info ? new RegExp(info.name_pattern).test(newName) && !entries.some((e) => e.name === newName) : false;

  return (
    <Box>
      <PageHeader
        title={info?.label ?? kind}
        subtitle={DESCRIPTIONS[kind]}
        actions={
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => {
              setNewName('');
              setBase('');
              setCreating(true);
            }}
          >
            新建
          </Button>
        }
      />
      <Grid container spacing={2}>
        {entries.map((e) => (
          <Grid key={e.name} size={{ xs: 12, sm: 6, lg: 4 }}>
            <Card variant="outlined" sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
              <CardActionArea onClick={() => navigate(`/configs/${kind}/${e.name}`)} sx={{ flex: 1, alignItems: 'flex-start', display: 'flex' }}>
                <CardContent sx={{ width: '100%' }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 600, fontFamily: 'monospace' }}>
                    {e.name}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1.5 }}>
                    {e.path} · 修改于 {fmtTime(e.modified)}
                  </Typography>
                  <EntrySummary kind={kind} e={e} />
                </CardContent>
              </CardActionArea>
              {kind === 'pipelines' && (
                <Box sx={{ px: 2, pb: 1.5 }}>
                  <Button size="small" startIcon={<PlayArrowIcon />} onClick={() => setRunFor(e.name)}>
                    运行
                  </Button>
                </Box>
              )}
            </Card>
          </Grid>
        ))}
      </Grid>
      {!entries.length && (
        <Alert severity="info" sx={{ mt: 2 }}>
          还没有 {info?.label}。
        </Alert>
      )}

      <Dialog open={creating} onClose={() => setCreating(false)} maxWidth="xs" fullWidth>
        <DialogTitle>新建{info?.label}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              autoFocus
              size="small"
              label="名称（也是文件名）"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              error={!!newName && !valid}
              helperText={info ? `格式 ${info.name_pattern}` : undefined}
            />
            <TextField select size="small" label="基于" value={base} onChange={(e) => setBase(e.target.value)} slotProps={{ inputLabel: { shrink: true } }}>
              <MenuItem value="">
                <em>空白模板</em>
              </MenuItem>
              {entries.map((e) => (
                <MenuItem key={e.name} value={e.name}>
                  复制 {e.name}
                </MenuItem>
              ))}
            </TextField>
            {create.error && <Alert severity="error">{String((create.error as Error).message)}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreating(false)}>取消</Button>
          <Button variant="contained" disabled={!valid || create.isPending} onClick={() => create.mutate()}>
            创建
          </Button>
        </DialogActions>
      </Dialog>
      <RunDialog open={!!runFor} pipeline={runFor ?? undefined} onClose={() => setRunFor(null)} />
    </Box>
  );
}

export function ConfigEditPage() {
  const { kind = '', name = '' } = useParams();
  const [running, setRunning] = useState(false);
  return (
    <>
      <ConfigEditor
        key={`${kind}/${name}`}
        kind={kind}
        name={name}
        Form={FORMS[kind]}
        lang={kind === 'prompts' ? 'jinja' : 'yaml'}
        actions={
          kind === 'pipelines'
            ? ({ dirty }) => (
                <Button size="small" variant="outlined" startIcon={<PlayArrowIcon />} onClick={() => setRunning(true)} disabled={dirty} title={dirty ? '先保存再运行' : undefined}>
                  运行
                </Button>
              )
            : undefined
        }
      />
      {kind === 'pipelines' && <RunDialog open={running} pipeline={name} onClose={() => setRunning(false)} />}
    </>
  );
}
