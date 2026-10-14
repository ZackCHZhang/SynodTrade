import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  List,
  ListItemButton,
  ListItemText,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import ScheduleIcon from '@mui/icons-material/Schedule';
import ReportProblemIcon from '@mui/icons-material/ReportProblem';
import StorageIcon from '@mui/icons-material/Storage';
import ReceiptLongIcon from '@mui/icons-material/ReceiptLong';
import { PieChart } from '@mui/x-charts';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { useConfigs } from '../api/hooks';
import { RunDialog } from '../components/RunDialog';
import { ModeChip, StatusChip } from '../components/StatusChip';
import { Empty, PageHeader, Section, StatCard } from '../components/common';
import { fmtDuration, fmtNum, fmtPct, fmtTime } from '../lib/format';
import { ActiveJobs, StageDots } from './RunsPage';
import { t } from '../i18n';

function KillSwitchCard({ active, reason }: { active: boolean; reason: string | null }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [why, setWhy] = useState('');
  const set = useMutation({
    mutationFn: (on: boolean) => api.setKillSwitch(on, on ? why || null : null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['overview'] });
      setOpen(false);
    },
  });
  return (
    <Card variant="outlined" sx={{ height: '100%', borderColor: active ? 'error.main' : undefined, bgcolor: active ? 'error.main' : undefined, color: active ? 'error.contrastText' : undefined }}>
      <CardContent>
        <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="body2" sx={{ opacity: 0.8 }}>
            {t('Global kill switch')}
          </Typography>
          <ReportProblemIcon />
        </Stack>
        <Stack direction="row" sx={{ alignItems: 'center', mt: 0.5 }}>
          <Typography variant="h5" sx={{ fontWeight: 600, flex: 1 }}>
            {active ? t('On') : t('Off')}
          </Typography>
          <Switch checked={active} color="default" onChange={(e) => (e.target.checked ? setOpen(true) : set.mutate(false))} />
        </Stack>
        <Typography variant="caption" component="div" sx={{ opacity: 0.8 }}>
          {active ? reason ?? t('No pipeline will place orders') : t("When on, every pipeline's orders become HOLD")}
        </Typography>
      </CardContent>
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>{t('Turn on the global kill switch')}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 2 }}>
            {t('Once on, no pipeline (including other processes and the scheduler) submits orders until it is turned off manually.')}
          </Typography>
          <TextField autoFocus fullWidth size="small" label={t('Reason (optional)')} value={why} onChange={(e) => setWhy(e.target.value)} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>{t('Cancel')}</Button>
          <Button color="error" variant="contained" onClick={() => set.mutate(true)}>
            {t('Turn on kill switch')}
          </Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}

export function Dashboard() {
  const navigate = useNavigate();
  const overview = useQuery({ queryKey: ['overview'], queryFn: api.overview, refetchInterval: 4000 });
  const portfolio = useQuery({ queryKey: ['portfolio'], queryFn: api.portfolio, refetchInterval: 30_000 });
  const { data: configs } = useConfigs();
  const [runFor, setRunFor] = useState<string | null>(null);
  const o = overview.data;
  if (overview.error) return <Alert severity="error">{t('Cannot reach the API: {error}. Start quant-web serve first.', { error: String((overview.error as Error).message) })}</Alert>;
  const byStatus = o?.runs_by_status ?? {};
  const total = Object.values(byStatus).reduce((a, b) => a + b, 0);
  const ledgers = Object.fromEntries((portfolio.data?.pipelines ?? []).map((p) => [p.name, p]));

  return (
    <Box>
      <PageHeader title={t('Overview')} subtitle={o ? t('Database {url}', { url: o.database.url }) : undefined} />
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <KillSwitchCard active={!!o?.kill_switch.active} reason={o?.kill_switch.reason ?? null} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <StatCard
            label={t('Scheduler')}
            icon={<ScheduleIcon />}
            value={o?.scheduler.running ? t('Running') : t('Not started')}
            color={o?.scheduler.running ? '#2e7d32' : undefined}
            hint={
              o?.scheduler.running && o.scheduler.jobs[0]
                ? t('Next: {pipeline} {time}', { pipeline: o.scheduler.jobs[0].pipeline, time: fmtTime(o.scheduler.jobs[0].next_run.utc) })
                : <RouterLink to="/scheduler">{t('Start it on the scheduler page')}</RouterLink>
            }
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <StatCard
            label={t('Run count')}
            icon={<StorageIcon />}
            value={total}
            hint={t('Succeeded {s} · Failed {f} · Running {r}', { s: byStatus.succeeded ?? 0, f: byStatus.failed ?? 0, r: byStatus.running ?? 0 })}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <StatCard label={t('Open orders')} icon={<ReceiptLongIcon />} value={o?.open_orders ?? '—'} hint={<RouterLink to="/portfolio">{t('View positions and orders')}</RouterLink>} />
        </Grid>
      </Grid>

      <ActiveJobs jobs={o?.jobs ?? []} />

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 8 }}>
          <Section
            title={t('Recent runs')}
            actions={
              <Button size="small" component={RouterLink} to="/runs">
                {t('All')}
              </Button>
            }
          >
            {o?.recent_runs.length ? (
              <List dense disablePadding>
                {o.recent_runs.map((r) => (
                  <ListItemButton key={r.run_id} onClick={() => navigate(`/runs/${r.run_id}`)} sx={{ borderRadius: 1 }}>
                    <Stack direction="row" spacing={2} sx={{ alignItems: 'center', width: '100%' }}>
                      <Box sx={{ width: 116, flexShrink: 0 }}>
                        <StatusChip status={r.status} />
                      </Box>
                      <ListItemText
                        primary={r.pipeline_name}
                        secondary={`${fmtTime(r.started_at, true)} · ${fmtDuration(r.started_at, r.ended_at)}`}
                        sx={{ flex: 1, minWidth: 0 }}
                      />
                      <ModeChip mode={r.mode} offline={r.offline} />
                      <Box sx={{ width: 110, display: { xs: 'none', sm: 'block' } }}>
                        <StageDots run={r} />
                      </Box>
                    </Stack>
                  </ListItemButton>
                ))}
              </List>
            ) : (
              <Empty>{t('No runs yet')}</Empty>
            )}
          </Section>
        </Grid>
        <Grid size={{ xs: 12, lg: 4 }}>
          <Section title={t('Run outcomes')}>
            {total ? (
              <PieChart
                height={200}
                series={[
                  {
                    data: [
                      { id: 's', value: byStatus.succeeded ?? 0, label: t('Succeeded'), color: '#43a047' },
                      { id: 'f', value: byStatus.failed ?? 0, label: t('Failed'), color: '#e53935' },
                      { id: 'r', value: byStatus.running ?? 0, label: t('Running'), color: '#1e88e5' },
                    ].filter((x) => x.value > 0),
                    innerRadius: 50,
                    paddingAngle: 2,
                    cornerRadius: 4,
                  },
                ]}
              />
            ) : (
              <Empty>{t('No data yet')}</Empty>
            )}
          </Section>
        </Grid>
      </Grid>

      <Section title={t('Pipelines')}>
        <Grid container spacing={2}>
          {(configs?.pipelines ?? []).map((p) => {
            const stats = o?.pipelines[p.name];
            const ledger = ledgers[p.name];
            return (
              <Grid key={p.name} size={{ xs: 12, md: 6, xl: 4 }}>
                <Card variant="outlined">
                  <CardContent>
                    <Stack direction="row" sx={{ alignItems: 'center', gap: 1, mb: 1 }}>
                      <Typography variant="subtitle1" sx={{ fontWeight: 600, flex: 1 }} component={RouterLink} to={`/configs/pipelines/${p.name}`} color="inherit">
                        {p.name}
                      </Typography>
                      <ModeChip mode={p.mode ?? 'dry_run'} />
                    </Stack>
                    <Typography variant="body2" color="text.secondary">
                      {stats ? t('{n|run|runs} · last {time}', { n: stats.runs, time: fmtTime(stats.last_started) }) : t('Never run')}
                    </Typography>
                    {ledger && !ledger.error && (
                      <Typography variant="body2" sx={{ mt: 0.5 }}>
                        {t('NAV')} <b>{fmtNum(ledger.nav)}</b> ({fmtPct(ledger.return_pct)}) · {t('{n|position|positions}', { n: ledger.positions.length })}
                      </Typography>
                    )}
                    <Button size="small" startIcon={<PlayArrowIcon />} sx={{ mt: 1 }} onClick={() => setRunFor(p.name)}>
                      {t('Run')}
                    </Button>
                  </CardContent>
                </Card>
              </Grid>
            );
          })}
        </Grid>
      </Section>
      <RunDialog open={!!runFor} pipeline={runFor ?? undefined} onClose={() => setRunFor(null)} />
    </Box>
  );
}
