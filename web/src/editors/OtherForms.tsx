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
import { useConfigs, useMeta } from '../api/hooks';
import type { FormProps } from '../components/ConfigEditor';
import { ErrorsContext, FieldEditor, SchemaFields, pathKey } from '../components/SchemaForm';
import { normalize, objectFields } from '../lib/schema';
import { setIn } from '../lib/yamlDoc';

function KeyField({ keyName, value, name }: { keyName: string; value: any; name: string }) {
  return (
    <TextField
      fullWidth
      size="small"
      label={`${keyName}`}
      value={value ?? ''}
      disabled
      error={value !== name}
      helperText={value !== name ? `必须等于文件名 ${name}` : '等于文件名'}
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
        引用的环境变量（.env）：
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
            label={`${r}${set === undefined ? '' : set ? ' 已设置' : ' 未设置'}`}
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
            <KeyField keyName="名称 name" value={data.name} name={name} />
          </Grid>
        </Grid>
        <SchemaFields field={field} value={data} path={[]} onChange={(v) => onChange({ name: data.name, ...(v ?? {}) })} />
        <Alert severity="info" sx={{ mt: 2 }}>
          数字字段也可以写 <code>{'${IBKR_PORT:-4002}'}</code> 这样的环境变量引用。Paper 端口：IB Gateway 4002、TWS 7497；实盘 4001 / 7496。
          每条流水线需要独立的 client_id（行情 = client_id，交易 +1，新闻 +2，扫描器 +3）。
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
    ['开关', ['kill_switch', 'one_order_per_symbol_per_day']],
    ['仓位与现金（占策略净值的比例）', ['max_position_pct', 'max_gross_exposure_pct', 'min_cash_pct']],
    ['亏损与交易频率', ['max_daily_loss_pct', 'max_weekly_loss_pct', 'max_trades_per_day', 'max_order_notional']],
    ['股票范围', ['whitelist', 'blacklist']],
    ['流动性与交易时段', ['liquidity', 'trading_hours']],
  ];
  return (
    <Stack spacing={2}>
      <Card variant="outlined">
        <CardContent>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, sm: 6, md: 4 }}>
              <KeyField keyName="名称 name" value={data.name} name={name} />
            </Grid>
          </Grid>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            硬规则由确定性代码在任何风控 agent 之前执行，LLM 无法覆盖。比例是该流水线虚拟子账户净值的比例。
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
                    label={keySet ? `${keyEnv} 已设置` : `${keyEnv} 未设置`}
                  />
                )}
                <Box sx={{ flex: 1 }} />
                <Tooltip title="删除供应商">
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
            <TextField size="small" label="新供应商名称" placeholder="例如 openai、qwen、local_ollama" value={newName} onChange={(e) => setNewName(e.target.value)} />
            <Button
              startIcon={<AddIcon />}
              disabled={!/^[a-z][a-z0-9_]*$/.test(newName) || newName in providers}
              onClick={() => {
                set({ ...providers, [newName]: { kind: 'openai_compatible', api_key_env: `${newName.toUpperCase()}_API_KEY`, structured_output: 'json_object' } });
                setNewName('');
              }}
            >
              添加
            </Button>
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
            API key 永远不写进配置文件：api_key_env 只写环境变量名，key 放在 .env 中，修改 .env 后需重启服务。
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
            所有时间按交易所时区定义；非交易日按真实交易日历跳过（节假日、提前收盘、夏令时）。
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
                  任务 {i + 1}
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
                  <TextField select fullWidth size="small" label="流水线 pipeline" value={job?.pipeline ?? ''} onChange={(e) => setJob(i, 'pipeline', e.target.value)} error={!!err('pipeline')} helperText={err('pipeline')} slotProps={{ inputLabel: { shrink: true } }}>
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
                    label="触发方式 trigger"
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
                    <MenuItem value="market_relative">相对开盘 / 收盘</MenuItem>
                    <MenuItem value="cron">cron 表达式</MenuItem>
                  </TextField>
                </Grid>
                {marketRelative ? (
                  <>
                    <Grid size={{ xs: 12, sm: 6, md: 3 }}>
                      <TextField select fullWidth size="small" label="锚点 anchor" value={job?.anchor ?? 'open'} onChange={(e) => setJob(i, 'anchor', e.target.value)} slotProps={{ inputLabel: { shrink: true } }}>
                        <MenuItem value="open">开盘 open</MenuItem>
                        <MenuItem value="close">收盘 close</MenuItem>
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
          添加任务
        </Button>
      </Box>
    </Stack>
  );
}
