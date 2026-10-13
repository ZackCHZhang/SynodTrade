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

const SYNC_STATUS: Record<string, { label: string; color: 'success' | 'warning' | 'error' }> = {
  ok: { label: '成功', color: 'success' },
  partial: { label: '部分成功', color: 'warning' },
  failed: { label: '失败', color: 'error' },
};

const TRIGGER: Record<string, string> = { pipeline: '流水线运行前', auto: '定时', manual: '手动', cli: '命令行' };

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
  return <Chip size="small" color={s.color} icon={icon} label={s.label} />;
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
      if (!file.data) throw new Error('配置文件未加载');
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
            同步设置
          </Typography>
          <Button size="small" startIcon={<SettingsIcon />} component={RouterLink} to="/configs/account_sync/account_sync">
            全部设置
          </Button>
        </Stack>
        {missing ? (
          <Alert severity="info">configs/account_sync.yaml 不存在，正在使用默认值（每 20 分钟自动同步，运行前同步）。</Alert>
        ) : (
          <Stack spacing={1.5}>
            <FormControlLabel control={<Switch checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />} label="定时自动同步" />
            <TextField
              size="small"
              type="number"
              label="同步间隔"
              value={interval}
              disabled={!enabled}
              onChange={(e) => setIntervalText(e.target.value)}
              error={invalid}
              helperText={invalid ? '1 – 1440 分钟' : 'Web 控制台运行期间，按此间隔同步所有账户'}
              slotProps={{ input: { endAdornment: <InputAdornment position="end">分钟</InputAdornment> }, htmlInput: { min: 1, max: 1440 } }}
            />
            <FormControlLabel
              control={<Switch checked={before} onChange={(e) => setBefore(e.target.checked)} />}
              label="每次 paper/live 运行前先同步（流水线第 1 步）"
            />
            {save.error && <Alert severity="error">{(save.error as Error).message}</Alert>}
            <Box>
              <Button variant="contained" disabled={!dirty || invalid || save.isPending} onClick={() => save.mutate()}>
                {save.isPending ? '保存中…' : '保存'}
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
          <TableCell>股票</TableCell>
          <TableCell>方向</TableCell>
          <TableCell>流水线</TableCell>
          <TableCell>状态变化</TableCell>
          <TableCell align="right">数量</TableCell>
          <TableCell align="right">已成交</TableCell>
          <TableCell align="right">成交均价</TableCell>
          <TableCell align="right">新成交笔数</TableCell>
          <TableCell>运行</TableCell>
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
            {fmtTime(sync.finished_at, true)} · {TRIGGER[sync.trigger] ?? sync.trigger}
            {sync.pipeline_name ? ` · ${sync.pipeline_name}` : ''} · 用时 {fmtDuration(sync.started_at, sync.finished_at)}
          </Typography>
        </Stack>
      }
    >
      {sync.error && (
        <Alert severity={sync.status === 'failed' ? 'error' : 'warning'} sx={{ mb: 1.5, whiteSpace: 'pre-wrap' }}>
          {sync.error}
          {sync.status === 'failed' && <Box sx={{ mt: 0.5 }}>请确认 TWS / IB Gateway 已启动并允许 API 连接（端口与账户配置一致）。</Box>}
        </Alert>
      )}
      {(r.warnings ?? []).map((w, i) => (
        <Alert key={i} severity="warning" sx={{ mb: 1 }}>
          {w}
        </Alert>
      ))}
      <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap', mb: 2 }}>
        <Chip variant="outlined" label={`检查订单 ${sync.orders_checked}`} />
        <Chip variant="outlined" color={sync.orders_updated ? 'primary' : 'default'} label={`更新订单 ${sync.orders_updated}`} />
        <Chip variant="outlined" color={sync.fills_added ? 'primary' : 'default'} label={`新成交 ${sync.fills_added}`} />
        {!!waiting.length && <Chip variant="outlined" label={`等待确认 ${waiting.length}`} />}
        {!!r.skipped_running?.length && <Chip variant="outlined" label={`运行中流水线的订单 ${r.skipped_running.length}（由交易阶段跟踪）`} />}
        {(r.pipelines ?? []).map((p) => (
          <Chip key={p} size="small" label={p} component={RouterLink} to={`/configs/pipelines/${p}`} clickable />
        ))}
      </Stack>

      <Typography variant="subtitle2" gutterBottom>
        订单状态更新
      </Typography>
      {changes.length ? <ChangesTable rows={changes} /> : <Empty>没有需要更新的订单</Empty>}
      {!!late.length && (
        <Box sx={{ mt: 2 }}>
          <Typography variant="subtitle2" gutterBottom>
            迟到的成交（已关闭订单被更正）
          </Typography>
          <ChangesTable rows={late} />
        </Box>
      )}
      {!!waiting.length && (
        <Box sx={{ mt: 2 }}>
          <Typography variant="subtitle2" gutterBottom>
            IBKR 暂时查不到、等待确认的订单
          </Typography>
          <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap' }}>
            {waiting.map((w) => (
              <Chip key={w.client_order_id} variant="outlined" label={`${w.symbol} · ${w.pipeline} · ${w.status} · 自 ${fmtTime(w.since)}`} />
            ))}
          </Stack>
        </Box>
      )}

      <Grid container spacing={2} sx={{ mt: 1 }}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Typography variant="subtitle2" gutterBottom>
            持仓核对：IBKR vs 流水线账本
          </Typography>
          {positions.length ? (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>股票</TableCell>
                  <TableCell align="right">IBKR</TableCell>
                  <TableCell align="right">账本合计</TableCell>
                  <TableCell>各流水线</TableCell>
                  <TableCell>结果</TableCell>
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
                        <Chip size="small" color="success" label="一致" />
                      ) : p.state === 'broker_more' ? (
                        <Chip size="small" variant="outlined" label="IBKR 多（手工或其他来源）" />
                      ) : (
                        <Chip size="small" color="error" label="IBKR 少：卖出被阻止" />
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <Empty>{r.account ? '没有持仓' : '没有账户数据（同步失败或未读取账户）'}</Empty>
          )}
        </Grid>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Typography variant="subtitle2" gutterBottom>
            账户
          </Typography>
          {r.account ? (
            <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap' }}>
              <Chip label={`净值 ${fmtNum(r.account.nav)} ${r.account.currency}`} />
              <Chip label={`现金 ${fmtNum(r.account.cash)}`} />
              <Chip label={`购买力 ${fmtNum(r.account.buying_power)}`} />
              {r.account.available_funds !== null && <Chip label={`可用资金 ${fmtNum(r.account.available_funds)}`} />}
            </Stack>
          ) : (
            <Empty>—</Empty>
          )}
          <Typography variant="subtitle2" sx={{ mt: 2 }} gutterBottom>
            IBKR 上数据库不知道的挂单
          </Typography>
          {untracked.length ? (
            <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap' }}>
              {untracked.map((o, i) => (
                <Chip
                  key={`${o.perm_id ?? i}`}
                  color="warning"
                  variant="outlined"
                  label={`${o.symbol} ${o.side} ${o.quantity}${o.limit_price !== null ? ` @ ${o.limit_price}` : ''} · ${o.status}${o.ref ? '' : ' · 手工'}`}
                />
              ))}
            </Stack>
          ) : (
            <Empty>没有</Empty>
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
    { field: 'finished_at', headerName: '时间', width: 170, valueFormatter: (v) => fmtTime(v as string, true) },
    { field: 'account_id', headerName: '账户', width: 110 },
    { field: 'trigger', headerName: '触发', width: 120, valueFormatter: (v) => TRIGGER[v as string] ?? v },
    { field: 'pipeline_name', headerName: '流水线', width: 150 },
    { field: 'status', headerName: '结果', width: 120, renderCell: (p) => <SyncStatusChip status={p.value} /> },
    { field: 'orders_checked', headerName: '检查', width: 70, type: 'number' },
    { field: 'orders_updated', headerName: '更新', width: 70, type: 'number' },
    { field: 'fills_added', headerName: '新成交', width: 80, type: 'number' },
    { field: 'warnings', headerName: '警告', width: 70, type: 'number', valueGetter: (_, row) => row.report?.warnings?.length ?? 0 },
    { field: 'error', headerName: '错误', flex: 1, minWidth: 200 },
  ];
  return (
    <Box>
      <PageHeader
        title="账户同步"
        subtitle="从 IBKR 读取订单成交、持仓和账户状态，写回数据库：订单是否成交、成交明细、迟到的成交、持仓核对"
        actions={
          <Button
            variant="contained"
            startIcon={run.isPending || d?.syncing ? <CircularProgress size={16} color="inherit" /> : <SyncIcon />}
            disabled={run.isPending}
            onClick={() => run.mutate()}
          >
            立即同步
          </Button>
        }
      />
      {d?.config_error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          configs/account_sync.yaml 无效：{d.config_error}
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
                label="自动同步"
                icon={<ScheduleIcon />}
                value={!d ? '—' : !d.running ? '未运行' : d.config?.enabled ? `每 ${d.config.interval_minutes} 分钟` : '已关闭'}
                color={d?.running && d.config?.enabled ? 'success.main' : undefined}
                hint={!d?.running ? '用 quant-web serve 启动时自动运行（--no-account-sync 关闭）' : d.syncing ? '正在同步…' : undefined}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 4 }}>
              <StatCard
                label="上次同步"
                icon={<SyncIcon />}
                value={last ? fmtTime(last.finished_at) : '从未'}
                hint={last ? <SyncStatusChip status={last.status} /> : undefined}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 4 }}>
              <StatCard label="下次自动同步" icon={<ScheduleIcon />} value={d?.next_due ? fmtTime(d.next_due) : '—'} hint={d?.last_error ?? undefined} />
            </Grid>
            <Grid size={12}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="subtitle2" gutterBottom>
                    同步的账户
                  </Typography>
                  {(d?.accounts ?? []).length ? (
                    (d?.accounts ?? []).map((a) => (
                      <Stack key={a.account_id} direction="row" sx={{ gap: 1, alignItems: 'center', flexWrap: 'wrap', mb: 0.5 }}>
                        <Typography sx={{ fontWeight: 600, fontFamily: 'monospace' }}>{a.account_id}</Typography>
                        {a.account_names.map((n) => (
                          <Chip key={n} size="small" variant="outlined" label={n} component={RouterLink} to={`/configs/accounts/${n}`} clickable />
                        ))}
                        <Typography variant="body2" color="text.secondary">
                          {a.pipelines.join('、')}
                        </Typography>
                      </Stack>
                    ))
                  ) : (
                    <Empty>没有可同步的账户（没有有效的流水线，或 .env 缺少 IBKR_ACCOUNT）</Empty>
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
        <Alert severity="info" sx={{ mb: 2 }} action={<Button onClick={() => setSelected(null)}>回到最新</Button>}>
          正在查看历史记录 #{selected}
        </Alert>
      )}
      {shown.length ? shown.map((s) => <SyncDetail key={s.id} sync={s} />) : <Section title="最新结果">{status.isLoading ? <Empty>加载中…</Empty> : <Empty>还没有同步记录：点击右上角"立即同步"</Empty>}</Section>}

      <Section title="同步历史">
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
