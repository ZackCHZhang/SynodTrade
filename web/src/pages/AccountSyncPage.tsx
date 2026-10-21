import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControlLabel,
  Grid,
  InputAdornment,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import SyncIcon from '@mui/icons-material/Sync';
import SettingsIcon from '@mui/icons-material/Settings';
import ScheduleIcon from '@mui/icons-material/Schedule';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import WarningIcon from '@mui/icons-material/Warning';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { ApiError, api, type AccountSyncRecord, type OrderChange } from '../api/client';
import { Empty, PageHeader, Section, StatCard } from '../components/common';
import { fmtDuration, fmtNum, fmtTime, shortId } from '../lib/format';
import { applyJson, parseYaml } from '../lib/yamlDoc';
import { t } from '../i18n';

const SYNC_STATUS: Record<string, { label: string; color: 'success' | 'warning' | 'error' }> = {
  ok: { label: 'Succeeded', color: 'success' },
  partial: { label: 'Partially succeeded', color: 'warning' },
  failed: { label: 'Failed', color: 'error' },
};

const TRIGGER: Record<string, string> = { pipeline: 'Before pipeline run', auto: 'Scheduled', manual: 'Manual', cli: 'Command line' };

const triggerLabel = (v: string) => (TRIGGER[v] ? t(TRIGGER[v]) : v);

const ORDER_STATUS_COLOR: Record<string, 'success' | 'error' | 'warning' | 'info' | 'default'> = {
  filled: 'success',
  partially_filled: 'info',
  submitted: 'default',
  pending_submit: 'default',
  cancelled: 'warning',
  rejected: 'error',
};

export function SyncStatusChip({ status }: { status: string }) {
  const s = SYNC_STATUS[status] ?? { label: status, color: 'warning' as const };
  const icon = status === 'ok' ? <CheckCircleIcon /> : status === 'failed' ? <ErrorIcon /> : <WarningIcon />;
  return <Chip size="small" color={s.color} icon={icon} label={SYNC_STATUS[status] ? t(s.label) : s.label} />;
}

function OrderStatusChip({ status }: { status: string }) {
  return <Chip size="small" variant="outlined" color={ORDER_STATUS_COLOR[status] ?? 'default'} label={status} />;
}

/** Quick settings: written into configs/account_sync.yaml (comments kept), applied on the next tick. */
function SettingsCard() {
  const qc = useQueryClient();
  const file = useQuery({ queryKey: ['config', 'account_sync', 'account_sync'], queryFn: () => api.config('account_sync', 'account_sync'), retry: false });
  const parsed = useMemo(() => (file.data ? parseYaml(file.data.text).data : null), [file.data]);
  const [enabled, setEnabled] = useState(true);
  const [interval, setIntervalText] = useState('20');
  const [before, setBefore] = useState(true);
  useEffect(() => {
    if (!parsed) return;
    setEnabled(parsed.enabled ?? true);
    setIntervalText(String(parsed.interval_minutes ?? 20));
    setBefore(parsed.before_pipeline ?? true);
  }, [parsed]);
  const minutes = Number(interval);
  const invalid = !Number.isInteger(minutes) || minutes < 1 || minutes > 1440;
  const dirty =
    !!parsed && (enabled !== (parsed.enabled ?? true) || minutes !== (parsed.interval_minutes ?? 20) || before !== (parsed.before_pipeline ?? true));
  const save = useMutation({
    mutationFn: async () => {
      if (!file.data) throw new Error(t('Config file not loaded'));
      const text = applyJson(file.data.text, { ...parsed, enabled, interval_minutes: minutes, before_pipeline: before });
      return api.save('account_sync', 'account_sync', text, file.data.etag);
    },
    onSuccess: (saved) => {
      qc.setQueryData(['config', 'account_sync', 'account_sync'], saved);
      qc.invalidateQueries({ queryKey: ['account-sync'] });
    },
  });
  const missing = file.error instanceof ApiError && file.error.status === 404;
  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent>
        <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {t('Sync settings')}
          </Typography>
          <Button size="small" startIcon={<SettingsIcon />} component={RouterLink} to="/configs/account_sync/account_sync">
            {t('All settings')}
          </Button>
        </Stack>
        {missing ? (
          <Alert severity="info">{t('configs/account_sync.yaml does not exist; using defaults (automatic sync every 20 minutes, sync before runs).')}</Alert>
        ) : (
          <Stack spacing={1.5}>
            <FormControlLabel control={<Switch checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />} label={t('Scheduled automatic sync')} />
            <TextField
              size="small"
              type="number"
              label={t('Sync interval')}
              value={interval}
              disabled={!enabled}
              onChange={(e) => setIntervalText(e.target.value)}
              error={invalid}
              helperText={invalid ? t('1 – 1440 minutes') : t('While the web console runs, all accounts sync at this interval')}
              slotProps={{ input: { endAdornment: <InputAdornment position="end">{t('minutes')}</InputAdornment> }, htmlInput: { min: 1, max: 1440 } }}
            />
            <FormControlLabel
              control={<Switch checked={before} onChange={(e) => setBefore(e.target.checked)} />}
              label={t('Sync before every paper/live run (pipeline step 1)')}
            />
            {save.error && <Alert severity="error">{(save.error as Error).message}</Alert>}
            <Box>
              <Button variant="contained" disabled={!dirty || invalid || save.isPending} onClick={() => save.mutate()}>
                {save.isPending ? t('Saving…') : t('Save')}
              </Button>
            </Box>
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}

function ChangesTable({ rows }: { rows: OrderChange[] }) {
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>{t('Symbol')}</TableCell>
          <TableCell>{t('Side')}</TableCell>
          <TableCell>{t('Pipeline')}</TableCell>
          <TableCell>{t('Status change')}</TableCell>
          <TableCell align="right">{t('Quantity')}</TableCell>
          <TableCell align="right">{t('Filled')}</TableCell>
          <TableCell align="right">{t('Avg fill price')}</TableCell>
          <TableCell align="right">{t('New fills')}</TableCell>
          <TableCell>{t('Run')}</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {rows.map((c) => (
          <TableRow key={c.client_order_id}>
            <TableCell sx={{ fontWeight: 600 }}>{c.symbol}</TableCell>
            <TableCell>{c.side}</TableCell>
            <TableCell>{c.pipeline}</TableCell>
            <TableCell>
              <Stack direction="row" sx={{ gap: 0.5, alignItems: 'center' }}>
                <OrderStatusChip status={c.from_status} />→<OrderStatusChip status={c.to_status} />
              </Stack>
            </TableCell>
            <TableCell align="right">{c.quantity}</TableCell>
            <TableCell align="right">{c.filled_qty}</TableCell>
            <TableCell align="right">{fmtNum(c.avg_fill_price)}</TableCell>
            <TableCell align="right">{c.new_fills}</TableCell>
            <TableCell>
              <RouterLink to={`/runs/${c.run_id}`} style={{ color: 'inherit' }}>
                {shortId(c.run_id)}
              </RouterLink>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function SyncDetail({ sync }: { sync: AccountSyncRecord }) {
  const r = sync.report ?? {};
  const changes = r.orders ?? [];
  const late = r.late_fills ?? [];
  const positions = r.positions ?? [];
  const untracked = r.untracked_open_orders ?? [];
  const waiting = r.waiting ?? [];
  return (
    <Section
      title={
        <Stack direction="row" sx={{ gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <span>{sync.account_id}</span>
          <SyncStatusChip status={sync.status} />
          <Typography variant="body2" color="text.secondary">
            {fmtTime(sync.finished_at, true)} · {triggerLabel(sync.trigger)}
            {sync.pipeline_name ? ` · ${sync.pipeline_name}` : ''} · {t('took {d}', { d: fmtDuration(sync.started_at, sync.finished_at) })}
          </Typography>
        </Stack>
      }
    >
      {sync.error && (
        <Alert severity={sync.status === 'failed' ? 'error' : 'warning'} sx={{ mb: 1.5, whiteSpace: 'pre-wrap' }}>
          {sync.error}
          {sync.status === 'failed' && <Box sx={{ mt: 0.5 }}>{t('Make sure TWS / IB Gateway is running and accepts API connections (port matching the account config).')}</Box>}
        </Alert>
      )}
      {(r.warnings ?? []).map((w, i) => (
        <Alert key={i} severity="warning" sx={{ mb: 1 }}>
          {w}
        </Alert>
      ))}
      <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap', mb: 2 }}>
        <Chip variant="outlined" label={`${t('Orders checked')} ${sync.orders_checked}`} />
        <Chip variant="outlined" color={sync.orders_updated ? 'primary' : 'default'} label={`${t('Orders updated')} ${sync.orders_updated}`} />
        <Chip variant="outlined" color={sync.fills_added ? 'primary' : 'default'} label={`${t('New fills')} ${sync.fills_added}`} />
        {!!waiting.length && <Chip variant="outlined" label={`${t('Awaiting confirmation')} ${waiting.length}`} />}
        {!!r.skipped_running?.length && <Chip variant="outlined" label={t('Orders of running pipelines {n} (tracked by the trading stage)', { n: r.skipped_running.length })} />}
        {(r.pipelines ?? []).map((p) => (
          <Chip key={p} size="small" label={p} component={RouterLink} to={`/configs/pipelines/${p}`} clickable />
        ))}
      </Stack>

      <Typography variant="subtitle2" gutterBottom>
        {t('Order status updates')}
      </Typography>
      {changes.length ? <ChangesTable rows={changes} /> : <Empty>{t('No orders needed updating')}</Empty>}
      {!!late.length && (
        <Box sx={{ mt: 2 }}>
          <Typography variant="subtitle2" gutterBottom>
            {t('Late fills (closed orders corrected)')}
          </Typography>
          <ChangesTable rows={late} />
        </Box>
      )}
      {!!waiting.length && (
        <Box sx={{ mt: 2 }}>
          <Typography variant="subtitle2" gutterBottom>
            {t('Orders IBKR cannot find yet, awaiting confirmation')}
          </Typography>
          <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap' }}>
            {waiting.map((w) => (
              <Chip key={w.client_order_id} variant="outlined" label={`${w.symbol} · ${w.pipeline} · ${w.status} · ${t('since {time}', { time: fmtTime(w.since) })}`} />
            ))}
          </Stack>
        </Box>
      )}

      <Grid container spacing={2} sx={{ mt: 1 }}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Typography variant="subtitle2" gutterBottom>
            {t('Position check: IBKR vs pipeline ledgers')}
          </Typography>
          {positions.length ? (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t('Symbol')}</TableCell>
                  <TableCell align="right">IBKR</TableCell>
                  <TableCell align="right">{t('Ledger total')}</TableCell>
                  <TableCell>{t('Per pipeline')}</TableCell>
                  <TableCell>{t('Result')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {positions.map((p) => (
                  <TableRow key={p.symbol}>
                    <TableCell sx={{ fontWeight: 600 }}>{p.symbol}</TableCell>
                    <TableCell align="right">{p.broker_qty}</TableCell>
                    <TableCell align="right">{p.ledger_qty}</TableCell>
                    <TableCell>
                      {Object.entries(p.pipelines)
                        .map(([k, v]) => `${k}: ${v}`)
                        .join(', ') || '—'}
                    </TableCell>
                    <TableCell>
                      {p.state === 'ok' ? (
                        <Chip size="small" color="success" label={t('Match')} />
                      ) : p.state === 'broker_more' ? (
                        <Chip size="small" variant="outlined" label={t('IBKR holds more (manual or other source)')} />
                      ) : (
                        <Chip size="small" color="error" label={t('IBKR holds less: sells blocked')} />
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <Empty>{r.account ? t('No positions') : t('No account data (sync failed or account not read)')}</Empty>
          )}
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Typography variant="subtitle2" gutterBottom>
            {t('Account')}
          </Typography>
          {r.account ? (
            <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap' }}>
              <Chip label={`${t('NAV')} ${fmtNum(r.account.nav)} ${r.account.currency}`} />
              <Chip label={`${t('Cash')} ${fmtNum(r.account.cash)}`} />
              <Chip label={`${t('Buying power')} ${fmtNum(r.account.buying_power)}`} />
              {r.account.available_funds !== null && <Chip label={`${t('Available funds')} ${fmtNum(r.account.available_funds)}`} />}
            </Stack>
          ) : (
            <Empty>—</Empty>
          )}
          <Typography variant="subtitle2" sx={{ mt: 2 }} gutterBottom>
            {t('Open orders on IBKR the database does not know about')}
          </Typography>
          {untracked.length ? (
            <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap' }}>
              {untracked.map((o, i) => (
                <Chip
                  key={`${o.perm_id ?? i}`}
                  color="warning"
                  variant="outlined"
                  label={`${o.symbol} ${o.side} ${o.quantity}${o.limit_price !== null ? ` @ ${o.limit_price}` : ''} · ${o.status}${o.ref ? '' : ` · ${t('manual')}`}`}
                />
              ))}
            </Stack>
          ) : (
            <Empty>{t('None')}</Empty>
          )}
        </Grid>
      </Grid>
    </Section>
  );
}

export function AccountSyncPage() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ['account-sync'], queryFn: () => api.accountSync(50), refetchInterval: 5000 });
  const [selected, setSelected] = useState<number | null>(null);
  const run = useMutation({
    mutationFn: api.accountSyncRun,
    onSuccess: () => {
      setSelected(null);
      qc.invalidateQueries({ queryKey: ['account-sync'] });
      qc.invalidateQueries({ queryKey: ['overview'] });
      qc.invalidateQueries({ queryKey: ['portfolio'] });
    },
  });
  const d = status.data;
  const history = d?.history ?? [];
  const shown = selected !== null ? history.filter((s) => s.id === selected) : d?.latest ?? [];
  const last = history[0];
  const cols: GridColDef<AccountSyncRecord>[] = [
    { field: 'finished_at', headerName: t('Time'), width: 170, valueFormatter: (v) => fmtTime(v as string, true) },
    { field: 'account_id', headerName: t('Account'), width: 110 },
    { field: 'trigger', headerName: t('Trigger'), width: 120, valueFormatter: (v) => triggerLabel(v as string) },
    { field: 'pipeline_name', headerName: t('Pipeline'), width: 150 },
    { field: 'status', headerName: t('Result'), width: 120, renderCell: (p) => <SyncStatusChip status={p.value} /> },
    { field: 'orders_checked', headerName: t('Checked'), width: 70, type: 'number' },
    { field: 'orders_updated', headerName: t('Updated'), width: 70, type: 'number' },
    { field: 'fills_added', headerName: t('New fills'), width: 80, type: 'number' },
    { field: 'warnings', headerName: t('Warnings'), width: 70, type: 'number', valueGetter: (_, row) => row.report?.warnings?.length ?? 0 },
    { field: 'error', headerName: t('Error'), flex: 1, minWidth: 200 },
  ];
  return (
    <Box>
      <PageHeader
        title={t('Account sync')}
        subtitle={t('Reads order fills, positions and account state from IBKR and writes them to the database: whether orders filled, fill details, late fills, position checks')}
        actions={
          <Button
            variant="contained"
            startIcon={run.isPending || d?.syncing ? <CircularProgress size={16} color="inherit" /> : <SyncIcon />}
            disabled={run.isPending}
            onClick={() => run.mutate()}
          >
            {t('Sync now')}
          </Button>
        }
      />
      {d?.config_error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {t('configs/account_sync.yaml is invalid: {error}', { error: d.config_error })}
        </Alert>
      )}
      {run.error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {(run.error as Error).message}
        </Alert>
      )}
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid size={{ xs: 12, md: 8 }}>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, sm: 4 }}>
              <StatCard
                label={t('Automatic sync')}
                icon={<ScheduleIcon />}
                value={!d ? '—' : !d.running ? t('Not running') : d.config?.enabled ? t('Every {n|minute|minutes}', { n: d.config.interval_minutes }) : t('Off')}
                color={d?.running && d.config?.enabled ? 'success.main' : undefined}
                hint={!d?.running ? t('Runs automatically when started with synodtrade-web serve (--no-account-sync turns it off)') : d.syncing ? t('Syncing…') : undefined}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 4 }}>
              <StatCard
                label={t('Last sync')}
                icon={<SyncIcon />}
                value={last ? fmtTime(last.finished_at) : t('Never')}
                hint={last ? <SyncStatusChip status={last.status} /> : undefined}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 4 }}>
              <StatCard label={t('Next automatic sync')} icon={<ScheduleIcon />} value={d?.next_due ? fmtTime(d.next_due) : '—'} hint={d?.last_error ?? undefined} />
            </Grid>
            <Grid size={12}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="subtitle2" gutterBottom>
                    {t('Synced accounts')}
                  </Typography>
                  {(d?.accounts ?? []).length ? (
                    (d?.accounts ?? []).map((a) => (
                      <Stack key={a.account_id} direction="row" sx={{ gap: 1, alignItems: 'center', flexWrap: 'wrap', mb: 0.5 }}>
                        <Typography sx={{ fontWeight: 600, fontFamily: 'monospace' }}>{a.account_id}</Typography>
                        {a.account_names.map((n) => (
                          <Chip key={n} size="small" variant="outlined" label={n} component={RouterLink} to={`/configs/accounts/${n}`} clickable />
                        ))}
                        <Typography variant="body2" color="text.secondary">
                          {a.pipelines.join(', ')}
                        </Typography>
                      </Stack>
                    ))
                  ) : (
                    <Empty>{t('No accounts to sync (no valid pipelines, or IBKR_ACCOUNT is missing from .env)')}</Empty>
                  )}
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <SettingsCard />
        </Grid>
      </Grid>

      {selected !== null && (
        <Alert severity="info" sx={{ mb: 2 }} action={<Button onClick={() => setSelected(null)}>{t('Back to latest')}</Button>}>
          {t('Viewing history entry #{id}', { id: selected })}
        </Alert>
      )}
      {shown.length ? shown.map((s) => <SyncDetail key={s.id} sync={s} />) : <Section title={t('Latest result')}>{status.isLoading ? <Empty>{t('Loading…')}</Empty> : <Empty>{t('No syncs yet: click "Sync now" at the top right')}</Empty>}</Section>}

      <Section title={t('Sync history')}>
        <Box sx={{ height: 420 }}>
          <DataGrid
            rows={history}
            columns={cols}
            density="compact"
            loading={status.isLoading}
            onRowClick={(p) => setSelected(Number(p.id))}
            sx={{ '& .MuiDataGrid-row': { cursor: 'pointer' } }}
          />
        </Box>
      </Section>
    </Box>
  );
}
