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
            全局熔断（kill switch）
          </Typography>
          <ReportProblemIcon />
        </Stack>
        <Stack direction="row" sx={{ alignItems: 'center', mt: 0.5 }}>
          <Typography variant="h5" sx={{ fontWeight: 600, flex: 1 }}>
            {active ? '已开启' : '关闭'}
          </Typography>
          <Switch checked={active} color="default" onChange={(e) => (e.target.checked ? setOpen(true) : set.mutate(false))} />
        </Stack>
        <Typography variant="caption" component="div" sx={{ opacity: 0.8 }}>
          {active ? reason ?? '所有流水线都不会下单' : '开启后所有流水线的订单都变为 HOLD'}
        </Typography>
      </CardContent>
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>开启全局熔断</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 2 }}>
            开启后，任何流水线（包括其他进程和调度器）都不会再提交订单，直到手动关闭。
          </Typography>
          <TextField autoFocus fullWidth size="small" label="原因（可选）" value={why} onChange={(e) => setWhy(e.target.value)} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>取消</Button>
          <Button color="error" variant="contained" onClick={() => set.mutate(true)}>
            开启熔断
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
  if (overview.error) return <Alert severity="error">无法连接 API：{String((overview.error as Error).message)}。请先启动 quant-web serve。</Alert>;
  const byStatus = o?.runs_by_status ?? {};
  const total = Object.values(byStatus).reduce((a, b) => a + b, 0);
  const ledgers = Object.fromEntries((portfolio.data?.pipelines ?? []).map((p) => [p.name, p]));

  return (
    <Box>
      <PageHeader title="总览" subtitle={o ? `数据库 ${o.database.url}` : undefined} />
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <KillSwitchCard active={!!o?.kill_switch.active} reason={o?.kill_switch.reason ?? null} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <StatCard
            label="调度器"
            icon={<ScheduleIcon />}
            value={o?.scheduler.running ? '运行中' : '未启动'}
            color={o?.scheduler.running ? '#2e7d32' : undefined}
            hint={
              o?.scheduler.running && o.scheduler.jobs[0]
                ? `下次：${o.scheduler.jobs[0].pipeline} ${fmtTime(o.scheduler.jobs[0].next_run.utc)}`
                : <RouterLink to="/scheduler">去调度器页面启动</RouterLink>
            }
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <StatCard
            label="运行次数"
            icon={<StorageIcon />}
            value={total}
            hint={`成功 ${byStatus.succeeded ?? 0} · 失败 ${byStatus.failed ?? 0} · 运行中 ${byStatus.running ?? 0}`}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <StatCard label="未完成订单" icon={<ReceiptLongIcon />} value={o?.open_orders ?? '—'} hint={<RouterLink to="/portfolio">查看持仓与订单</RouterLink>} />
        </Grid>
      </Grid>

      <ActiveJobs jobs={o?.jobs ?? []} />

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 8 }}>
          <Section
            title="最近运行"
            actions={
              <Button size="small" component={RouterLink} to="/runs">
                全部
              </Button>
            }
          >
            {o?.recent_runs.length ? (
              <List dense disablePadding>
                {o.recent_runs.map((r) => (
                  <ListItemButton key={r.run_id} onClick={() => navigate(`/runs/${r.run_id}`)} sx={{ borderRadius: 1 }}>
                    <Stack direction="row" spacing={2} sx={{ alignItems: 'center', width: '100%' }}>
                      <Box sx={{ width: 96 }}>
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
              <Empty>还没有运行记录</Empty>
            )}
          </Section>
        </Grid>
        <Grid size={{ xs: 12, lg: 4 }}>
          <Section title="运行结果分布">
            {total ? (
              <PieChart
                height={200}
                series={[
                  {
                    data: [
                      { id: 's', value: byStatus.succeeded ?? 0, label: '成功', color: '#43a047' },
                      { id: 'f', value: byStatus.failed ?? 0, label: '失败', color: '#e53935' },
                      { id: 'r', value: byStatus.running ?? 0, label: '运行中', color: '#1e88e5' },
                    ].filter((x) => x.value > 0),
                    innerRadius: 50,
                    paddingAngle: 2,
                    cornerRadius: 4,
                  },
                ]}
              />
            ) : (
              <Empty>暂无数据</Empty>
            )}
          </Section>
        </Grid>
      </Grid>

      <Section title="流水线">
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
                      {stats ? `运行 ${stats.runs} 次 · 最近 ${fmtTime(stats.last_started)}` : '从未运行'}
                    </Typography>
                    {ledger && !ledger.error && (
                      <Typography variant="body2" sx={{ mt: 0.5 }}>
                        净值 <b>{fmtNum(ledger.nav)}</b>（{fmtPct(ledger.return_pct)}）· 持仓 {ledger.positions.length} 只
                      </Typography>
                    )}
                    <Button size="small" startIcon={<PlayArrowIcon />} sx={{ mt: 1 }} onClick={() => setRunFor(p.name)}>
                      运行
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
