import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Grid,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import RefreshIcon from '@mui/icons-material/Refresh';
import EditIcon from '@mui/icons-material/Edit';
import HealthAndSafetyIcon from '@mui/icons-material/HealthAndSafety';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { api, type Times } from '../api/client';
import { RunDialog } from '../components/RunDialog';
import { Empty, PageHeader, Section } from '../components/common';
import { fmtTime } from '../lib/format';
import { t } from '../i18n';

function TimeCell({ t: time }: { t: Times }) {
  if (!time.utc) return <>—</>;
  return (
    <Box>
      <Typography variant="body2">
        {fmtTime(time.utc)} ({t('local')})
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {t('New York')} {time.new_york?.replace('T', ' ').slice(0, 16)} · {t('Berlin')} {time.berlin?.replace('T', ' ').slice(0, 16)}
      </Typography>
    </Box>
  );
}

export function SchedulerPage() {
  const qc = useQueryClient();
  const [days, setDays] = useState(7);
  const [runFor, setRunFor] = useState<string | null>(null);
  const status = useQuery({ queryKey: ['scheduler', 'status'], queryFn: api.schedulerStatus, refetchInterval: 5000 });
  const plan = useQuery({ queryKey: ['scheduler', 'plan', days], queryFn: () => api.schedulerPlan(days) });
  const action = useMutation({
    mutationFn: api.schedulerAction,
    onSuccess: (s) => {
      qc.setQueryData(['scheduler', 'status'], s);
      qc.invalidateQueries({ queryKey: ['overview'] });
    },
  });
  const check = useMutation({ mutationFn: api.schedulerCheck });
  const running = status.data?.running;

  const timeline = (plan.data?.jobs ?? [])
    .flatMap((j) => j.upcoming.map((t) => ({ job: j, t })))
    .sort((a, b) => (a.t.utc ?? '').localeCompare(b.t.utc ?? ''));

  return (
    <Box>
      <PageHeader
        title={t('Scheduler')}
        subtitle={t('Wakes pipelines on the exchange calendar (configs/schedules.yaml)')}
        actions={
          <Button startIcon={<EditIcon />} component={RouterLink} to="/configs/schedules/schedules">
            {t('Edit schedules')}
          </Button>
        }
      />
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Card variant="outlined" sx={{ mb: 2, borderColor: running ? 'success.main' : undefined }}>
            <CardContent>
              <Stack direction="row" sx={{ alignItems: 'center', gap: 1, mb: 2 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 600, flex: 1 }}>
                  {t('Built-in scheduler')}
                </Typography>
                <Chip color={running ? 'success' : 'default'} label={running ? t('Running') : t('Stopped')} />
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                {t('Runs inside this web server process and keeps jobs in memory; scheduling stops when the server stops. In production you can use a standalone')}{' '}
                <code>synodtrade-scheduler run</code> {t('(or docker compose) instead. Never run both, or pipelines wake up twice.')}
              </Typography>
              {running && status.data?.started_at && (
                <Typography variant="body2" sx={{ mb: 2 }}>
                  {t('Started at {time}', { time: fmtTime(status.data.started_at, true) })}
                </Typography>
              )}
              <Stack direction="row" spacing={1}>
                {!running ? (
                  <Button variant="contained" color="success" startIcon={<PlayArrowIcon />} disabled={action.isPending} onClick={() => action.mutate('start')}>
                    {t('Start')}
                  </Button>
                ) : (
                  <>
                    <Button variant="outlined" color="error" startIcon={<StopIcon />} disabled={action.isPending} onClick={() => action.mutate('stop')}>
                      {t('Stop')}
                    </Button>
                    <Button startIcon={<RefreshIcon />} disabled={action.isPending} onClick={() => action.mutate('reload')}>
                      {t('Reload config')}
                    </Button>
                  </>
                )}
                <Button startIcon={<HealthAndSafetyIcon />} disabled={check.isPending} onClick={() => check.mutate()}>
                  {t('Health check')}
                </Button>
              </Stack>
              {action.error && (
                <Alert severity="error" sx={{ mt: 2, whiteSpace: 'pre-wrap' }}>
                  {String((action.error as Error).message)}
                </Alert>
              )}
              {check.data && (
                <Stack spacing={1} sx={{ mt: 2 }}>
                  {check.data.map((c) => (
                    <Alert key={c.pipeline} severity={c.ok ? 'success' : 'error'}>
                      <b>{c.pipeline}</b>: {c.ok ? t('Database and IB Gateway are both reachable') : c.problems.join('; ')}
                    </Alert>
                  ))}
                </Stack>
              )}
            </CardContent>
          </Card>
          {running && (
            <Section title={t('Scheduled jobs')}>
              {status.data?.jobs.length ? (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>{t('Job')}</TableCell>
                      <TableCell>{t('Next run')}</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {status.data.jobs.map((j) => (
                      <TableRow key={j.id}>
                        <TableCell>
                          <Typography variant="body2" sx={{ fontWeight: 600 }}>
                            {j.id}
                            {j.dry_run && <Chip size="small" label="dry_run" sx={{ ml: 1 }} />}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                            {j.trigger}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <TimeCell t={j.next_run} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <Empty>{t('No enabled jobs')}</Empty>
              )}
            </Section>
          )}
          <Section title={t('Jobs in config')}>
            {plan.error && <Alert severity="error">{String((plan.error as Error).message)}</Alert>}
            {(plan.data?.jobs ?? []).map((j) => (
              <Stack key={j.id} direction="row" sx={{ alignItems: 'center', py: 1, borderBottom: '1px solid', borderColor: 'divider', gap: 1 }}>
                <Box sx={{ flex: 1 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {j.id}
                    {!j.config.enabled && <Chip size="small" label={t('Disabled')} sx={{ ml: 1 }} />}
                    {j.config.dry_run && <Chip size="small" label="dry_run" sx={{ ml: 1 }} />}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                    {j.trigger}
                  </Typography>
                </Box>
                <Button size="small" startIcon={<PlayArrowIcon />} onClick={() => setRunFor(j.config.pipeline)}>
                  {t('Run now')}
                </Button>
              </Stack>
            ))}
          </Section>
        </Grid>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Section
            title={t('Run plan for the next {n|day|days}', { n: days })}
            actions={
              <TextField select size="small" value={days} onChange={(e) => setDays(Number(e.target.value))} sx={{ width: 120 }}>
                {[1, 3, 7, 14, 30].map((d) => (
                  <MenuItem key={d} value={d}>
                    {t('{n|day|days}', { n: d })}
                  </MenuItem>
                ))}
              </TextField>
            }
          >
            {timeline.length ? (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>{t('Time')}</TableCell>
                    <TableCell>{t('Pipeline')}</TableCell>
                    <TableCell>{t('Trigger')}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {timeline.map(({ job, t }, i) => (
                    <TableRow key={i}>
                      <TableCell>
                        <TimeCell t={t} />
                      </TableCell>
                      <TableCell>
                        <RouterLink to={`/configs/pipelines/${job.config.pipeline}`} style={{ color: 'inherit', fontWeight: 600 }}>
                          {job.config.pipeline}
                        </RouterLink>
                        {job.config.dry_run && <Chip size="small" label="dry_run" sx={{ ml: 1 }} />}
                      </TableCell>
                      <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>{job.trigger}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Empty>{plan.isLoading ? t('Calculating…') : t('No runs in this period')}</Empty>
            )}
          </Section>
        </Grid>
      </Grid>
      <RunDialog open={!!runFor} pipeline={runFor ?? undefined} onClose={() => setRunFor(null)} />
    </Box>
  );
}
