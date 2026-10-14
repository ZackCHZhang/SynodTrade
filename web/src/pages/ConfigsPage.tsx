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
import { AgentAvatar } from '../components/AgentAvatar';
import { RunDialog } from '../components/RunDialog';
import { PageHeader } from '../components/common';
import { AgentForm } from '../editors/AgentForm';
import { AccountForm, AccountSyncForm, ProvidersForm, RiskForm, SchedulesForm } from '../editors/OtherForms';
import { PipelineForm } from '../editors/PipelineForm';
import { fmtTime } from '../lib/format';
import { STAGE_INFO, roleLabel, stageLabel } from '../lib/labels';
import { applyJson, parseYaml } from '../lib/yamlDoc';
import { t } from '../i18n';

const FORMS: Record<string, React.ComponentType<any>> = {
  pipelines: PipelineForm,
  agents: AgentForm,
  accounts: AccountForm,
  risk: RiskForm,
  llm_providers: ProvidersForm,
  schedules: SchedulesForm,
  account_sync: AccountSyncForm,
};

const DESCRIPTIONS: Record<string, string> = {
  pipelines: 'A pipeline = account + capital + universe + ordered stages (selection → market data → sentiment → decision → risk → trading); each stage can instantiate several agents.',
  agents: 'Agent = role + persona + prompt template + strategy instructions. The model is chosen when a pipeline instantiates it.',
  prompts: 'Jinja2 prompt templates (configs/agents/prompts/), referenced by agents through prompt_template.',
  accounts: 'IBKR connection settings. Write account numbers and secrets as ${ENV} references and keep the real values in .env.',
  risk: 'Hard risk rules: deterministic code that runs before any risk agent; the LLM cannot override them.',
};

function template(kind: string, name: string, firstAccount?: string): string {
  switch (kind) {
    case 'pipelines':
      return `# Created in the web console
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
      return `# Created in the web console
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
      return `# Created in the web console; pipelines that run at the same time need different client_ids
name: ${name}
broker: ibkr
account_id: \${IBKR_ACCOUNT}
host: \${IBKR_HOST:-127.0.0.1}
port: \${IBKR_PORT:-4002}
client_id: 37
base_currency: USD
`;
    case 'risk':
      return `# Created in the web console
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
  if (e.broken) return <Chip size="small" color="error" label={t('Cannot parse')} />;
  if (kind === 'pipelines')
    return (
      <Stack spacing={1}>
        <Stack direction="row" sx={{ gap: 0.5, flexWrap: 'wrap' }}>
          <Chip size="small" variant="outlined" color={e.mode === 'live' ? 'error' : e.mode === 'paper' ? 'info' : 'default'} label={e.mode} />
          <Chip size="small" variant="outlined" label={e.account} />
          <Chip size="small" variant="outlined" label={t('{n|symbol|symbols}', { n: e.universe_size })} />
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
        <Chip size="small" color="primary" variant="outlined" label={roleLabel(e.role)} />
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
        title={info ? t(info.label) : kind}
        subtitle={DESCRIPTIONS[kind] && t(DESCRIPTIONS[kind])}
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
            {t('New')}
          </Button>
        }
      />
      <Grid container spacing={2}>
        {entries.map((e) => (
          <Grid key={e.name} size={{ xs: 12, sm: 6, lg: 4 }}>
            <Card variant="outlined" sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
              <CardActionArea onClick={() => navigate(`/configs/${kind}/${e.name}`)} sx={{ flex: 1, alignItems: 'flex-start', display: 'flex' }}>
                <CardContent sx={{ width: '100%' }}>
                  <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center' }}>
                    {kind === 'agents' && <AgentAvatar agentId={e.name} size={40} />}
                    <Typography variant="subtitle1" sx={{ fontWeight: 600, fontFamily: 'monospace' }}>
                      {e.name}
                    </Typography>
                  </Stack>
                  <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1.5 }}>
                    {e.path} · {t('modified {time}', { time: fmtTime(e.modified) })}
                  </Typography>
                  <EntrySummary kind={kind} e={e} />
                </CardContent>
              </CardActionArea>
              {kind === 'pipelines' && (
                <Box sx={{ px: 2, pb: 1.5 }}>
                  <Button size="small" startIcon={<PlayArrowIcon />} onClick={() => setRunFor(e.name)}>
                    {t('Run')}
                  </Button>
                </Box>
              )}
            </Card>
          </Grid>
        ))}
      </Grid>
      {!entries.length && (
        <Alert severity="info" sx={{ mt: 2 }}>
          {t('Nothing here yet: {kind}.', { kind: info ? t(info.label) : kind })}
        </Alert>
      )}

      <Dialog open={creating} onClose={() => setCreating(false)} maxWidth="xs" fullWidth>
        <DialogTitle>{t('Create in {kind}', { kind: info ? t(info.label) : kind })}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              autoFocus
              size="small"
              label={t('Name (also the file name)')}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              error={!!newName && !valid}
              helperText={info ? t('Format {pattern}', { pattern: info.name_pattern }) : undefined}
            />
            <TextField select size="small" label={t('Based on')} value={base} onChange={(e) => setBase(e.target.value)} slotProps={{ inputLabel: { shrink: true } }}>
              <MenuItem value="">
                <em>{t('Blank template')}</em>
              </MenuItem>
              {entries.map((e) => (
                <MenuItem key={e.name} value={e.name}>
                  {t('Copy of {name}', { name: e.name })}
                </MenuItem>
              ))}
            </TextField>
            {create.error && <Alert severity="error">{String((create.error as Error).message)}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreating(false)}>{t('Cancel')}</Button>
          <Button variant="contained" disabled={!valid || create.isPending} onClick={() => create.mutate()}>
            {t('Create')}
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
                <Button size="small" variant="outlined" startIcon={<PlayArrowIcon />} onClick={() => setRunning(true)} disabled={dirty} title={dirty ? t('Save before running') : undefined}>
                  {t('Run')}
                </Button>
              )
            : undefined
        }
      />
      {kind === 'pipelines' && <RunDialog open={running} pipeline={name} onClose={() => setRunning(false)} />}
    </>
  );
}
