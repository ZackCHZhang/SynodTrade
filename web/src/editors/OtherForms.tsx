import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Grid,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlined';
import { useContext, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { useConfigs, useMeta } from '../api/hooks';
import type { FormProps } from '../components/ConfigEditor';
import { ErrorsContext, FieldEditor, SchemaFields, pathKey } from '../components/SchemaForm';
import { withKey } from '../lib/labels';
import { normalize, objectFields } from '../lib/schema';
import { setIn } from '../lib/yamlDoc';
import { t } from '../i18n';

function KeyField({ keyName, value, name }: { keyName: string; value: any; name: string }) {
  return (
    <TextField
      fullWidth
      size="small"
      label={`${keyName}`}
      value={value ?? ''}
      disabled
      error={value !== name}
      helperText={value !== name ? t('Must equal the file name {name}', { name }) : t('Equals the file name')}
    />
  );
}

/** Env references like ${IBKR_ACCOUNT} with whether the server has them set. */
function EnvRefs({ data }: { data: any }) {
  const { data: meta } = useMeta();
  const refs = new Set<string>();
  const walk = (v: any) => {
    if (typeof v === 'string') for (const m of v.matchAll(/\$\{([A-Za-z_][A-Za-z0-9_]*)(:-[^}]*)?\}/g)) refs.add(m[1]);
    else if (v && typeof v === 'object') Object.values(v).forEach(walk);
  };
  walk(data);
  if (!refs.size) return null;
  return (
    <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap', alignItems: 'center', mt: 2 }}>
      <Typography variant="caption" color="text.secondary">
        {t('Referenced environment variables (.env):')}
      </Typography>
      {[...refs].map((r) => {
        const set = meta?.env[r];
        return (
          <Chip
            key={r}
            size="small"
            variant="outlined"
            color={set === undefined ? 'default' : set ? 'success' : 'warning'}
            icon={set ? <CheckCircleIcon /> : <ErrorOutlineIcon />}
            label={`${r}${set === undefined ? '' : ' ' + (set ? t('set') : t('not set'))}`}
          />
        );
      })}
    </Stack>
  );
}

export function AccountForm({ data, onChange, name }: FormProps) {
  const { data: meta } = useMeta();
  if (!meta) return null;
  const field = objectFields(meta.schemas.account, ['name']);
  return (
    <Card variant="outlined">
      <CardContent>
        <Grid container spacing={2} sx={{ mb: 2 }}>
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <KeyField keyName={withKey('Name', 'name')} value={data.name} name={name} />
          </Grid>
        </Grid>
        <SchemaFields field={field} value={data} path={[]} onChange={(v) => onChange({ name: data.name, ...(v ?? {}) })} />
        <Alert severity="info" sx={{ mt: 2 }}>
          {t('Numeric fields can also hold environment variable references such as')} <code>{'${IBKR_PORT:-4002}'}</code>.{' '}
          {t('Paper ports: IB Gateway 4002, TWS 7497; live 4001 / 7496. Each pipeline needs its own client_id (market data = client_id, trading +1, news +2, scanner +3).')}
        </Alert>
        <EnvRefs data={data} />
      </CardContent>
    </Card>
  );
}

export function RiskForm({ data, onChange, name }: FormProps) {
  const { data: meta } = useMeta();
  if (!meta) return null;
  const field = objectFields(meta.schemas.risk, ['name']);
  const groups: [string, string[]][] = [
    [t('Switches'), ['kill_switch', 'one_order_per_symbol_per_day']],
    [t("Positions and cash (share of the strategy's NAV)"), ['max_position_pct', 'max_gross_exposure_pct', 'min_cash_pct']],
    [t('Losses and trading frequency'), ['max_daily_loss_pct', 'max_weekly_loss_pct', 'max_trades_per_day', 'max_order_notional']],
    [t('Symbol scope'), ['whitelist', 'blacklist']],
    [t('Liquidity and trading hours'), ['liquidity', 'trading_hours']],
  ];
  return (
    <Stack spacing={2}>
      <Card variant="outlined">
        <CardContent>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, sm: 6, md: 4 }}>
              <KeyField keyName={withKey('Name', 'name')} value={data.name} name={name} />
            </Grid>
          </Grid>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            {t("Hard rules are deterministic code that runs before any risk agent; the LLM cannot override them. Ratios are shares of this pipeline's virtual sub-account NAV.")}
          </Typography>
        </CardContent>
      </Card>
      {groups.map(([title, keys]) => (
        <Card key={title} variant="outlined">
          <CardContent>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 2 }}>
              {title}
            </Typography>
            <SchemaFields field={field} only={keys} value={data} path={[]} columns={3} onChange={(v) => onChange({ name: data.name, ...(v ?? {}) })} />
          </CardContent>
        </Card>
      ))}
    </Stack>
  );
}

export function ProvidersForm({ data, onChange }: FormProps) {
  const { data: meta } = useMeta();
  const errors = useContext(ErrorsContext);
  const [newName, setNewName] = useState('');
  if (!meta) return null;
  const field = normalize(meta.schemas.llm_provider);
  const providers: Record<string, any> = data.providers && typeof data.providers === 'object' ? data.providers : {};
  const set = (next: Record<string, any>) => onChange({ ...data, providers: next });
  return (
    <Stack spacing={2}>
      {Object.entries(providers).map(([pname, cfg]) => {
        const keyEnv = cfg?.api_key_env;
        const keySet = keyEnv ? meta.env[keyEnv] : undefined;
        return (
          <Card key={pname} variant="outlined">
            <CardContent>
              <Stack direction="row" sx={{ alignItems: 'center', mb: 2, gap: 1 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 600, fontFamily: 'monospace' }}>
                  {pname}
                </Typography>
                <Chip size="small" label={cfg?.kind ?? '?'} variant="outlined" />
                {keyEnv && (
                  <Chip
                    size="small"
                    color={keySet ? 'success' : 'warning'}
                    icon={keySet ? <CheckCircleIcon /> : <ErrorOutlineIcon />}
                    label={`${keyEnv} ${keySet ? t('set') : t('not set')}`}
                  />
                )}
                <Box sx={{ flex: 1 }} />
                <Tooltip title={t('Delete provider')}>
                  <IconButton
                    size="small"
                    onClick={() => {
                      const next = { ...providers };
                      delete next[pname];
                      set(next);
                    }}
                  >
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Stack>
              {errors[pathKey(['providers', pname])] && <Alert severity="error">{errors[pathKey(['providers', pname])]}</Alert>}
              <SchemaFields field={field} value={cfg} path={['providers', pname]} columns={3} onChange={(v) => set({ ...providers, [pname]: v ?? {} })} />
            </CardContent>
          </Card>
        );
      })}
      <Card variant="outlined">
        <CardContent>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
            <TextField size="small" label={t('New provider name')} placeholder={t('e.g. openai, qwen, local_ollama')} value={newName} onChange={(e) => setNewName(e.target.value)} />
            <Button
              startIcon={<AddIcon />}
              disabled={!/^[a-z][a-z0-9_]*$/.test(newName) || newName in providers}
              onClick={() => {
                set({ ...providers, [newName]: { kind: 'openai_compatible', api_key_env: `${newName.toUpperCase()}_API_KEY`, structured_output: 'json_object' } });
                setNewName('');
              }}
            >
              {t('Add')}
            </Button>
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
            {t('API keys never go into config files: api_key_env holds only the variable name, the key lives in .env, and the service must restart after .env changes.')}
          </Typography>
        </CardContent>
      </Card>
    </Stack>
  );
}

export function SchedulesForm({ data, onChange }: FormProps) {
  const { data: meta } = useMeta();
  const { data: configs } = useConfigs();
  const errors = useContext(ErrorsContext);
  if (!meta) return null;
  const schema = normalize(meta.schemas.schedules);
  const jobField = normalize(meta.schemas.job);
  const jobs: any[] = Array.isArray(data.jobs) ? data.jobs : [];
  const pipelines = (configs?.pipelines ?? []).map((p) => p.name);
  const set = (path: (string | number)[], v: any) => onChange(setIn(data, path, v));
  const setJob = (i: number, key: string, v: any) => {
    const job = { ...jobs[i] };
    if (v === undefined) delete job[key];
    else job[key] = v;
    set(['jobs', i], job);
  };
  return (
    <Stack spacing={2}>
      <Card variant="outlined">
        <CardContent>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, sm: 6 }}>
              <FieldEditor name="calendar" field={schema.properties!.calendar} value={data.calendar} path={['calendar']} options={['XNYS', 'XNAS', 'XLON', 'XETR', 'XHKG', 'XSHG']} onChange={(v) => set(['calendar'], v)} />
            </Grid>
            <Grid size={{ xs: 12, sm: 6 }}>
              <FieldEditor name="timezone" field={schema.properties!.timezone} value={data.timezone} path={['timezone']} options={['America/New_York', 'Europe/London', 'Europe/Berlin', 'Asia/Hong_Kong', 'Asia/Shanghai']} onChange={(v) => set(['timezone'], v)} />
            </Grid>
          </Grid>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            {t('All times are in the exchange time zone; non-trading days are skipped using the real trading calendar (holidays, early closes, daylight saving).')}
          </Typography>
        </CardContent>
      </Card>
      {jobs.map((job, i) => {
        const path = ['jobs', i];
        const err = (k: string) => errors[pathKey([...path, k])];
        const marketRelative = job?.trigger !== 'cron';
        return (
          <Card key={i} variant="outlined" sx={{ opacity: job?.enabled === false ? 0.6 : 1 }}>
            <CardContent>
              <Stack direction="row" sx={{ alignItems: 'center', mb: 2 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                  {t('Job {n}', { n: i + 1 })}
                  {job?.pipeline && (
                    <Typography component="span" sx={{ ml: 1, fontFamily: 'monospace' }} color="text.secondary">
                      {job.pipeline}#{jobs.slice(0, i).filter((j) => j?.pipeline === job.pipeline).length}
                    </Typography>
                  )}
                </Typography>
                <Box sx={{ flex: 1 }} />
                <IconButton size="small" onClick={() => set(['jobs'], jobs.filter((_, j) => j !== i))}>
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              </Stack>
              {errors[pathKey(path)] && (
                <Alert severity="error" sx={{ mb: 2 }}>
                  {errors[pathKey(path)]}
                </Alert>
              )}
              <Grid container spacing={2}>
                <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                  <TextField select fullWidth size="small" label={withKey('Pipeline', 'pipeline')} value={job?.pipeline ?? ''} onChange={(e) => setJob(i, 'pipeline', e.target.value)} error={!!err('pipeline')} helperText={err('pipeline')} slotProps={{ inputLabel: { shrink: true } }}>
                    {pipelines.map((p) => (
                      <MenuItem key={p} value={p}>
                        {p}
                      </MenuItem>
                    ))}
                  </TextField>
                </Grid>
                <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                  <TextField
                    select
                    fullWidth
                    size="small"
                    label={withKey('Trigger', 'trigger')}
                    value={job?.trigger ?? 'market_relative'}
                    onChange={(e) => {
                      const t = e.target.value;
                      const next = { ...job, trigger: t };
                      if (t === 'cron') {
                        delete next.anchor;
                        delete next.offset_minutes;
                        next.cron = next.cron ?? '0 10 * * MON-FRI';
                      } else {
                        delete next.cron;
                        delete next.skip_non_trading_days;
                        next.anchor = next.anchor ?? 'open';
                      }
                      set(['jobs', i], next);
                    }}
                    slotProps={{ inputLabel: { shrink: true } }}
                  >
                    <MenuItem value="market_relative">{t('Relative to open / close')}</MenuItem>
                    <MenuItem value="cron">{t('cron expression')}</MenuItem>
                  </TextField>
                </Grid>
                {marketRelative ? (
                  <>
                    <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                      <TextField select fullWidth size="small" label={withKey('Anchor', 'anchor')} value={job?.anchor ?? 'open'} onChange={(e) => setJob(i, 'anchor', e.target.value)} slotProps={{ inputLabel: { shrink: true } }}>
                        <MenuItem value="open">{t('Open')} open</MenuItem>
                        <MenuItem value="close">{t('Close (market)')} close</MenuItem>
                      </TextField>
                    </Grid>
                    <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                      <FieldEditor name="offset_minutes" field={jobField.properties!.offset_minutes} value={job?.offset_minutes} path={[...path, 'offset_minutes']} onChange={(v) => setJob(i, 'offset_minutes', v)} />
                    </Grid>
                  </>
                ) : (
                  <>
                    <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                      <FieldEditor name="cron" field={{ kind: 'string', nullable: false, hasDefault: false }} value={job?.cron} path={[...path, 'cron']} options={['30 9 * * MON-FRI', '0 10 * * MON-FRI', '45 15 * * MON-FRI', '0 11 * * MON']} onChange={(v) => setJob(i, 'cron', v)} />
                    </Grid>
                    <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                      <FieldEditor name="skip_non_trading_days" field={jobField.properties!.skip_non_trading_days} value={job?.skip_non_trading_days} path={[...path, 'skip_non_trading_days']} onChange={(v) => setJob(i, 'skip_non_trading_days', v)} />
                    </Grid>
                  </>
                )}
                <Grid size={{ xs: 12, sm: 4 }}>
                  <FieldEditor name="enabled" field={jobField.properties!.enabled} value={job?.enabled} path={[...path, 'enabled']} onChange={(v) => setJob(i, 'enabled', v)} />
                </Grid>
                <Grid size={{ xs: 12, sm: 4 }}>
                  <FieldEditor name="dry_run" field={jobField.properties!.dry_run} value={job?.dry_run} path={[...path, 'dry_run']} onChange={(v) => setJob(i, 'dry_run', v)} />
                </Grid>
                <Grid size={{ xs: 12, sm: 4 }}>
                  <FieldEditor name="misfire_grace_minutes" field={jobField.properties!.misfire_grace_minutes} value={job?.misfire_grace_minutes} path={[...path, 'misfire_grace_minutes']} onChange={(v) => setJob(i, 'misfire_grace_minutes', v)} />
                </Grid>
              </Grid>
            </CardContent>
          </Card>
        );
      })}
      <Box>
        <Button startIcon={<AddIcon />} variant="outlined" onClick={() => set(['jobs'], [...jobs, { pipeline: pipelines[0] ?? '', trigger: 'market_relative', anchor: 'open', offset_minutes: 30 }])}>
          {t('Add job')}
        </Button>
      </Box>
    </Stack>
  );
}

export function AccountSyncForm({ data, onChange }: FormProps) {
  const { data: meta } = useMeta();
  const { data: configs } = useConfigs();
  if (!meta) return null;
  const field = objectFields(meta.schemas.account_sync, ['accounts']);
  const accounts: string[] = Array.isArray(data.accounts) ? data.accounts : [];
  const known = (configs?.accounts ?? []).map((a) => a.name);
  return (
    <Card variant="outlined">
      <CardContent>
        <SchemaFields field={field} value={data} path={[]} onChange={(v) => onChange({ ...(v ?? {}), accounts: data.accounts ?? [] })} />
        <TextField
          select
          fullWidth
          size="small"
          sx={{ mt: 2 }}
          label={withKey('Only sync these account configs', 'accounts')}
          value={accounts}
          onChange={(e) => {
            const v = e.target.value as unknown as string[] | string;
            onChange({ ...data, accounts: typeof v === 'string' ? v.split(',') : v });
          }}
          helperText={t('Empty = every account a pipeline uses. Configs sharing one IBKR account are merged into one sync.')}
          slotProps={{ select: { multiple: true, renderValue: (v) => ((v as string[]).length ? (v as string[]).join(', ') : t('All')) } }}
        >
          {known.map((n) => (
            <MenuItem key={n} value={n}>
              {n}
            </MenuItem>
          ))}
        </TextField>
        <Alert severity="info" sx={{ mt: 2 }}>
          {t('Sync uses its own API connection (account client_id + 4), so it never conflicts with running pipelines. Settings take effect at the next check (about 15 s) without a restart.')}{' '}
          {t('Results and history are on the')} <RouterLink to="/account-sync">{t('Account sync')}</RouterLink> {t('page.')}
        </Alert>
      </CardContent>
    </Card>
  );
}
