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

function TimeCell({ t }: { t: Times }) {
  if (!t.utc) return <>—</>;
  return (
    <Box>
      <Typography variant="body2">{fmtTime(t.utc)}（本地）</Typography>
      <Typography variant="caption" color="text.secondary">
        纽约 {t.new_york?.replace('T', ' ').slice(0, 16)} · 柏林 {t.berlin?.replace('T', ' ').slice(0, 16)}
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
        title="调度器"
        subtitle="按交易所日历定时唤醒流水线（configs/schedules.yaml）"
        actions={
          <Button startIcon={<EditIcon />} component={RouterLink} to="/configs/schedules/schedules">
            编辑调度配置
          </Button>
        }
      />
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Card variant="outlined" sx={{ mb: 2, borderColor: running ? 'success.main' : undefined }}>
            <CardContent>
              <Stack direction="row" sx={{ alignItems: 'center', gap: 1, mb: 2 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 600, flex: 1 }}>
                  内置调度器
                </Typography>
                <Chip color={running ? 'success' : 'default'} label={running ? '运行中' : '已停止'} />
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                在本 Web 服务进程内运行，任务保存在内存中；服务停止调度也停止。生产环境可以改用独立的 <code>quant-scheduler run</code>
                （或 docker compose），不要两者同时运行，否则流水线会被唤醒两次。
              </Typography>
              {running && status.data?.started_at && (
                <Typography variant="body2" sx={{ mb: 2 }}>
                  启动于 {fmtTime(status.data.started_at, true)}
                </Typography>
              )}
              <Stack direction="row" spacing={1}>
                {!running ? (
                  <Button variant="contained" color="success" startIcon={<PlayArrowIcon />} disabled={action.isPending} onClick={() => action.mutate('start')}>
                    启动
                  </Button>
                ) : (
                  <>
                    <Button variant="outlined" color="error" startIcon={<StopIcon />} disabled={action.isPending} onClick={() => action.mutate('stop')}>
                      停止
                    </Button>
                    <Button startIcon={<RefreshIcon />} disabled={action.isPending} onClick={() => action.mutate('reload')}>
                      重新加载配置
                    </Button>
                  </>
                )}
                <Button startIcon={<HealthAndSafetyIcon />} disabled={check.isPending} onClick={() => check.mutate()}>
                  健康检查
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
                      <b>{c.pipeline}</b>：{c.ok ? '数据库和 IB Gateway 均可连接' : c.problems.join('；')}
                    </Alert>
                  ))}
                </Stack>
              )}
            </CardContent>
          </Card>
          {running && (
            <Section title="已排程的任务">
              {status.data?.jobs.length ? (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>任务</TableCell>
                      <TableCell>下次运行</TableCell>
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
                <Empty>没有启用的任务</Empty>
              )}
            </Section>
          )}
          <Section title="配置中的任务">
            {plan.error && <Alert severity="error">{String((plan.error as Error).message)}</Alert>}
            {(plan.data?.jobs ?? []).map((j) => (
              <Stack key={j.id} direction="row" sx={{ alignItems: 'center', py: 1, borderBottom: '1px solid', borderColor: 'divider', gap: 1 }}>
                <Box sx={{ flex: 1 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {j.id}
                    {!j.config.enabled && <Chip size="small" label="已禁用" sx={{ ml: 1 }} />}
                    {j.config.dry_run && <Chip size="small" label="dry_run" sx={{ ml: 1 }} />}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                    {j.trigger}
                  </Typography>
                </Box>
                <Button size="small" startIcon={<PlayArrowIcon />} onClick={() => setRunFor(j.config.pipeline)}>
                  立即运行
                </Button>
              </Stack>
            ))}
          </Section>
        </Grid>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Section
            title={`未来 ${days} 天的运行计划`}
            actions={
              <TextField select size="small" value={days} onChange={(e) => setDays(Number(e.target.value))} sx={{ width: 120 }}>
                {[1, 3, 7, 14, 30].map((d) => (
                  <MenuItem key={d} value={d}>
                    {d} 天
                  </MenuItem>
                ))}
              </TextField>
            }
          >
            {timeline.length ? (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>时间</TableCell>
                    <TableCell>流水线</TableCell>
                    <TableCell>触发</TableCell>
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
              <Empty>{plan.isLoading ? '计算中…' : '这段时间没有运行'}</Empty>
            )}
          </Section>
        </Grid>
      </Grid>
      <RunDialog open={!!runFor} pipeline={runFor ?? undefined} onClose={() => setRunFor(null)} />
    </Box>
  );
}
