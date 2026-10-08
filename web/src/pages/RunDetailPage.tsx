import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Grid,
  IconButton,
  LinearProgress,
  MenuItem,
  Paper,
  Stack,
  Switch,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';
import StopIcon from '@mui/icons-material/Stop';
import ReplayIcon from '@mui/icons-material/Replay';
import { BarChart } from '@mui/x-charts';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { Link as RouterLink, useParams } from 'react-router-dom';
import { api, type RunDetail, type RunEvent, type StageTiming } from '../api/client';
import { useRunEvents } from '../api/events';
import { AgentAvatar, AgentLabel } from '../components/AgentAvatar';
import { RunDialog } from '../components/RunDialog';
import { ActionChip, ModeChip, StatusChip } from '../components/StatusChip';
import { Empty, JsonView, PageHeader, Section } from '../components/common';
import { fmtDuration, fmtNum, fmtSeconds, fmtTime, shortId } from '../lib/format';
import { STAGE_INFO, stageLabel } from '../lib/labels';

// ------------------------------------------------------------------ progress

function stageStatuses(detail: RunDetail, live: Record<string, StageTiming>): Record<string, StageTiming> {
  const out: Record<string, StageTiming> = {};
  const summary = detail.run.summary?.stages ?? {};
  const running = detail.run.status === 'running';
  for (const s of detail.run.stages_run) {
    out[s] = live[s] ?? detail.progress[s] ?? summary[s] ?? { status: running ? 'pending' : 'skipped' };
  }
  return out;
}

function StageProgress({ stages, statuses, runStatus }: { stages: string[]; statuses: Record<string, StageTiming>; runStatus: string }) {
  const done = stages.filter((s) => ['ok', 'failed', 'failed_skipped'].includes(statuses[s]?.status)).length;
  const pct = stages.length ? (done / stages.length) * 100 : 0;
  return (
    <Card variant="outlined" sx={{ mb: 2 }}>
      <CardContent>
        <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            进度
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {done} / {stages.length} 个阶段
          </Typography>
        </Stack>
        <LinearProgress
          variant={runStatus === 'running' && done < stages.length ? 'buffer' : 'determinate'}
          value={pct}
          valueBuffer={runStatus === 'running' ? Math.min(100, pct + 100 / Math.max(stages.length, 1)) : pct}
          color={runStatus === 'failed' ? 'error' : runStatus === 'succeeded' ? 'success' : 'primary'}
          sx={{ height: 6, borderRadius: 3, mb: 2 }}
        />
        <Stack direction="row" sx={{ gap: 1, overflowX: 'auto' }}>
          {stages.map((s, i) => {
            const st = statuses[s] ?? { status: 'pending' };
            const color = STAGE_INFO[s]?.color ?? '#757575';
            const active = st.status === 'running';
            return (
              <Stack key={s} direction="row" sx={{ alignItems: 'center', flex: 1, minWidth: 140 }}>
                <Paper
                  variant="outlined"
                  sx={{
                    p: 1.25,
                    flex: 1,
                    borderColor: st.status === 'pending' || st.status === 'skipped' ? 'divider' : color,
                    borderWidth: active ? 2 : 1,
                    bgcolor: active ? `${color}14` : undefined,
                  }}
                >
                  <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600, color }}>
                      {i + 1}. {stageLabel(s)}
                    </Typography>
                    {active && <CircularProgress size={14} />}
                    {st.status === 'ok' && <CheckIcon fontSize="small" color="success" />}
                    {st.status === 'failed' && <CloseIcon fontSize="small" color="error" />}
                  </Stack>
                  <Stack direction="row" sx={{ alignItems: 'center', gap: 1, mt: 0.5 }}>
                    <StatusChip status={st.status} />
                    <Typography variant="caption" color="text.secondary">
                      {st.seconds !== undefined ? fmtSeconds(st.seconds) : active && st.started ? fmtDuration(st.started, null) : ''}
                    </Typography>
                  </Stack>
                </Paper>
              </Stack>
            );
          })}
        </Stack>
      </CardContent>
    </Card>
  );
}

// ------------------------------------------------------------------ log

const HIDDEN_KEYS = new Set(['seq', 'event', 'level', 'ts', 'ts_local', 'run_id', 'pipeline', 'web_job']);
const LEVEL_COLOR: Record<string, string> = { error: '#e53935', critical: '#e53935', warning: '#fb8c00', info: '#1e88e5', debug: '#9e9e9e' };

function LogView({ events, state }: { events: RunEvent[]; state: string }) {
  const [filter, setFilter] = useState('');
  const [level, setLevel] = useState('');
  const [follow, setFollow] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  const shown = useMemo(
    () =>
      events.filter((e) => {
        if (level && e.level !== level) return false;
        if (!filter) return true;
        return JSON.stringify(e).toLowerCase().includes(filter.toLowerCase());
      }),
    [events, filter, level],
  );
  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [shown, follow]);
  return (
    <Box>
      <Stack direction="row" spacing={2} sx={{ mb: 1, alignItems: 'center', flexWrap: 'wrap' }}>
        <TextField size="small" placeholder="过滤…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <TextField select size="small" value={level} onChange={(e) => setLevel(e.target.value)} sx={{ width: 140 }} label="级别" slotProps={{ inputLabel: { shrink: true } }}>
          <MenuItem value="">全部</MenuItem>
          {['info', 'warning', 'error', 'debug'].map((l) => (
            <MenuItem key={l} value={l}>
              {l}
            </MenuItem>
          ))}
        </TextField>
        <FormControlLabel control={<Switch size="small" checked={follow} onChange={(e) => setFollow(e.target.checked)} />} label="自动滚动" />
        <Chip size="small" label={state === 'live' ? '实时连接' : state === 'ended' ? '已结束' : state === 'error' ? '连接断开' : '连接中'} color={state === 'live' ? 'success' : 'default'} variant="outlined" />
        <Typography variant="caption" color="text.secondary">
          {shown.length} / {events.length} 条
        </Typography>
      </Stack>
      <Box
        ref={box}
        sx={{
          height: 460,
          overflow: 'auto',
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
          fontSize: 12.5,
          bgcolor: 'action.hover',
          borderRadius: 1,
          p: 1,
        }}
      >
        {shown.map((e) => {
          const extra = Object.entries(e).filter(([k]) => !HIDDEN_KEYS.has(k));
          const time = (e.ts_local ?? e.ts ?? '').slice(11, 19);
          return (
            <Box key={e.seq} sx={{ py: 0.25, borderBottom: '1px dashed', borderColor: 'divider', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              <Box component="span" sx={{ color: 'text.secondary' }}>
                {time}{' '}
              </Box>
              <Box component="span" sx={{ color: LEVEL_COLOR[e.level] ?? 'inherit', fontWeight: 600 }}>
                {e.level?.toUpperCase().padEnd(7)}
              </Box>{' '}
              <Box component="span" sx={{ fontWeight: 600 }}>
                {e.event}
              </Box>{' '}
              {extra.map(([k, v]) => (
                <Box key={k} component="span">
                  <Box component="span" sx={{ color: 'text.secondary' }}>
                    {k}=
                  </Box>
                  {typeof v === 'object' ? JSON.stringify(v) : String(v)}{'  '}
                </Box>
              ))}
            </Box>
          );
        })}
        {!events.length && <Empty>{state === 'ended' ? '没有日志（该运行不是由本服务启动的，只能查看数据库中的结果）' : '等待事件…'}</Empty>}
      </Box>
    </Box>
  );
}

// ------------------------------------------------------------------ result tabs

function SymbolOverview({ d }: { d: RunDetail }) {
  const s = d.run.summary;
  const agg = Object.fromEntries(d.aggregated_decisions.map((a) => [a.symbol, a]));
  const risk = s?.risk ?? {};
  const orders = Object.fromEntries(d.orders.map((o) => [o.intent.symbol, o]));
  const symbols = [...new Set([...(s?.universe ?? []), ...Object.keys(agg)])];
  if (!symbols.length) return <Empty>还没有结果</Empty>;
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>股票</TableCell>
          <TableCell>决策</TableCell>
          <TableCell>得分</TableCell>
          <TableCell>风控后</TableCell>
          <TableCell>订单</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {symbols.map((sym) => {
          const o = orders[sym];
          return (
            <TableRow key={sym}>
              <TableCell sx={{ fontWeight: 600 }}>
                <RouterLink to={`/market?symbol=${sym}`} style={{ color: 'inherit' }}>
                  {sym}
                </RouterLink>
              </TableCell>
              <TableCell>{agg[sym] ? <ActionChip action={agg[sym].final_action} /> : '—'}</TableCell>
              <TableCell>{agg[sym] ? fmtNum(agg[sym].score, 3) : '—'}</TableCell>
              <TableCell>{risk[sym] ? <ActionChip action={risk[sym]} /> : '—'}</TableCell>
              <TableCell>
                {o ? (
                  <Typography variant="body2">
                    {o.intent.side} {o.intent.quantity} @ {o.intent.limit_price ?? 'MKT'} · <b>{o.status}</b>
                    {o.filled_qty ? ` · 成交 ${o.filled_qty} @ ${fmtNum(o.avg_fill_price)}` : ''}
                  </Typography>
                ) : (
                  '—'
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function SummaryTab({ d, statuses }: { d: RunDetail; statuses: Record<string, StageTiming> }) {
  const s = d.run.summary;
  const timed = d.run.stages_run.filter((x) => statuses[x]?.seconds !== undefined);
  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, lg: 7 }}>
        <Section title="每只股票的结果">
          <SymbolOverview d={d} />
        </Section>
        {!!s?.errors?.length && (
          <Section title="错误">
            {s.errors.map((e, i) => (
              <Alert key={i} severity={e.skipped ? 'warning' : 'error'} sx={{ mb: 1 }}>
                <b>{stageLabel(e.stage)}</b>（{e.error_type}{e.skipped ? '，已跳过' : ''}）：{e.message}
              </Alert>
            ))}
          </Section>
        )}
        {d.run.error && !s?.errors?.length && <Alert severity="error">{d.run.error}</Alert>}
      </Grid>
      <Grid size={{ xs: 12, lg: 5 }}>
        <Section title="阶段耗时">
          {timed.length ? (
            <BarChart
              height={220}
              layout="horizontal"
              yAxis={[{ scaleType: 'band', data: timed.map(stageLabel), width: 72 }]}
              series={[{ data: timed.map((x) => statuses[x].seconds ?? 0), label: '秒', color: '#1e88e5' }]}
              hideLegend
            />
          ) : (
            <Empty>运行结束后显示</Empty>
          )}
        </Section>
        <Section title="数量">
          <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap' }}>
            <Chip label={`Agent 实例 ${d.agent_instances.length}`} />
            <Chip label={`LLM 调用 ${d.llm_calls.length}`} />
            <Chip label={`舆情结果 ${d.sentiment_results.length}`} />
            <Chip label={`决策 ${d.decisions.length}`} />
            <Chip label={`风控评估 ${d.risk_assessments.length}`} />
            <Chip label={`订单 ${d.orders.length}`} />
            <Chip
              label={`Token ${d.llm_calls.reduce((n, c) => n + (c.input_tokens ?? 0), 0).toLocaleString()} 入 / ${d.llm_calls
                .reduce((n, c) => n + (c.output_tokens ?? 0), 0)
                .toLocaleString()} 出`}
            />
          </Stack>
        </Section>
      </Grid>
    </Grid>
  );
}

function SelectionTab({ d }: { d: RunDetail }) {
  const sel = d.stock_selection;
  if (!sel && !d.selection_results.length) return <Empty>这次运行没有选股阶段</Empty>;
  const scores: [string, number][] = sel ? Object.entries<number>(sel.scores).sort((a, b) => b[1] - a[1]) : [];
  return (
    <Grid container spacing={2}>
      {sel && (
        <Grid size={{ xs: 12, lg: 5 }}>
          <Section title={`最终选择（${sel.method}）`}>
            <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap', mb: 2 }}>
              {sel.selected.map((s: string) => (
                <Chip key={s} color="primary" label={`${s} ${fmtNum(sel.scores[s], 2)}`} />
              ))}
              {sel.holdings.map((s: string) => (
                <Chip key={s} variant="outlined" label={`${s}（持仓保留）`} />
              ))}
              {!sel.selected.length && <Typography color="text.secondary">没有选出股票</Typography>}
            </Stack>
            {!!scores.length && (
              <BarChart
                height={Math.max(160, scores.length * 26)}
                layout="horizontal"
                yAxis={[{ scaleType: 'band', data: scores.map((x) => x[0]), width: 64 }]}
                xAxis={[{ min: 0, max: 1 }]}
                series={[{ data: scores.map((x) => x[1]), label: '聚合得分', color: '#8e24aa' }]}
                hideLegend
              />
            )}
            {!!Object.keys(sel.rejected ?? {}).length && (
              <>
                <Typography variant="subtitle2" sx={{ mt: 2 }}>
                  初筛淘汰
                </Typography>
                {Object.entries<string>(sel.rejected).map(([s, why]) => (
                  <Typography key={s} variant="body2">
                    <b>{s}</b>：{why}
                  </Typography>
                ))}
              </>
            )}
          </Section>
        </Grid>
      )}
      <Grid size={{ xs: 12, lg: sel ? 7 : 12 }}>
        {d.selection_results.map((r) => (
          <Section key={r.id} title={<AgentLabel agentId={r.agent_id}>{`${r.agent_id} · ${shortId(r.instance_id)}`}</AgentLabel>} actions={r.error && <Chip size="small" color="error" label="失败" />}>
            {r.error && <Alert severity="error" sx={{ mb: 1 }}>{r.error}</Alert>}
            <Typography variant="body2" sx={{ mb: 1 }}>
              {r.summary}
            </Typography>
            <Table size="small">
              <TableBody>
                {r.picks.map((p: any) => (
                  <TableRow key={p.symbol}>
                    <TableCell sx={{ fontWeight: 600, width: 80 }}>{p.symbol}</TableCell>
                    <TableCell sx={{ width: 70 }}>{fmtNum(p.score, 2)}</TableCell>
                    <TableCell>{p.reason}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Section>
        ))}
      </Grid>
    </Grid>
  );
}

function SentimentBar({ value }: { value: number }) {
  const pct = Math.abs(value) * 50;
  return (
    <Box sx={{ position: 'relative', width: 120, height: 10, bgcolor: 'action.hover', borderRadius: 5 }}>
      <Box sx={{ position: 'absolute', left: '50%', top: -2, bottom: -2, width: '1px', bgcolor: 'text.disabled' }} />
      <Box
        sx={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          borderRadius: 5,
          left: value >= 0 ? '50%' : `${50 - pct}%`,
          width: `${pct}%`,
          bgcolor: value >= 0 ? 'success.main' : 'error.main',
        }}
      />
    </Box>
  );
}

function SentimentTab({ d }: { d: RunDetail }) {
  if (!d.sentiment_results.length) return <Empty>没有舆情结果</Empty>;
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>股票</TableCell>
          <TableCell>Agent</TableCell>
          <TableCell>情绪</TableCell>
          <TableCell>置信度</TableCell>
          <TableCell>摘要</TableCell>
          <TableCell>关键事件</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {d.sentiment_results.map((r) => (
          <TableRow key={r.id}>
            <TableCell sx={{ fontWeight: 600 }}>{r.symbol}</TableCell>
            <TableCell>
              <AgentLabel agentId={r.agent_id} />
            </TableCell>
            <TableCell>
              <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                <SentimentBar value={r.sentiment} />
                <span>{fmtNum(r.sentiment, 2)}</span>
              </Stack>
            </TableCell>
            <TableCell>{fmtNum(r.confidence, 2)}</TableCell>
            <TableCell sx={{ maxWidth: 420 }}>
              {r.error && <Chip size="small" color="error" label="失败" sx={{ mr: 1 }} />}
              {r.summary}
            </TableCell>
            <TableCell>{(r.key_events ?? []).join('；')}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function DecisionTab({ d }: { d: RunDetail }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!d.aggregated_decisions.length && !d.decisions.length) return <Empty>没有决策</Empty>;
  const bySymbol: Record<string, any[]> = {};
  for (const x of d.decisions) (bySymbol[x.symbol] ??= []).push(x);
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>股票</TableCell>
          <TableCell>最终动作</TableCell>
          <TableCell>方法</TableCell>
          <TableCell>得分</TableCell>
          <TableCell>投票</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {d.aggregated_decisions.map((a) => (
          <Fragment key={a.id}>
            <TableRow hover sx={{ cursor: 'pointer' }} onClick={() => setOpen(open === a.symbol ? null : a.symbol)}>
              <TableCell sx={{ fontWeight: 600 }}>{a.symbol}</TableCell>
              <TableCell>
                <ActionChip action={a.final_action} />
              </TableCell>
              <TableCell>{a.method}</TableCell>
              <TableCell>{fmtNum(a.score, 3)}</TableCell>
              <TableCell>
                <Stack direction="row" sx={{ gap: 0.5, flexWrap: 'wrap' }}>
                  {a.votes.map((v: any) => (
                    <Tooltip key={v.instance_id} title={`${v.agent_id} · 置信度 ${fmtNum(v.confidence, 2)} · 权重 ${v.weight}`}>
                      <Stack direction="row" spacing={0.5} component="span" sx={{ alignItems: 'center' }}>
                        <AgentAvatar agentId={v.agent_id} size={22} />
                        <ActionChip action={v.action} />
                      </Stack>
                    </Tooltip>
                  ))}
                </Stack>
              </TableCell>
            </TableRow>
            {open === a.symbol &&
              (bySymbol[a.symbol] ?? []).map((x) => (
                <TableRow key={x.id} sx={{ bgcolor: 'action.hover' }}>
                  <TableCell />
                  <TableCell>
                    <ActionChip action={x.action} />
                  </TableCell>
                  <TableCell>
                    <AgentLabel agentId={x.agent_id} />
                    <Typography variant="caption" color="text.secondary" component="div">
                      {shortId(x.instance_id)} · 置信度 {fmtNum(x.confidence, 2)}
                    </Typography>
                  </TableCell>
                  <TableCell colSpan={2}>
                    {x.error && <Chip size="small" color="error" label={x.error} sx={{ mb: 0.5 }} />}
                    <Typography variant="body2">{x.reasoning}</Typography>
                    {!!x.referenced_data_ids?.length && (
                      <Typography variant="caption" color="text.secondary">
                        引用：{x.referenced_data_ids.join(', ')}
                      </Typography>
                    )}
                  </TableCell>
                </TableRow>
              ))}
          </Fragment>
        ))}
      </TableBody>
    </Table>
  );
}

function RiskTab({ d }: { d: RunDetail }) {
  if (!d.risk_assessments.length) return <Empty>没有风控评估</Empty>;
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>股票</TableCell>
          <TableCell>来源</TableCell>
          <TableCell>结论</TableCell>
          <TableCell>动作</TableCell>
          <TableCell>原因</TableCell>
          <TableCell>规则命中</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {d.risk_assessments.map((r) => (
          <TableRow key={r.id}>
            <TableCell sx={{ fontWeight: 600 }}>{r.symbol}</TableCell>
            <TableCell>
              {r.source === 'rules' ? <Chip size="small" label="硬规则" /> : r.source === 'final' ? r.source : <AgentLabel agentId={r.source} />}
            </TableCell>
            <TableCell>
              <Chip size="small" label={r.verdict} color={r.verdict === 'approve' ? 'success' : r.verdict === 'reject' ? 'error' : 'warning'} variant="outlined" />
            </TableCell>
            <TableCell>
              <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                <ActionChip action={r.original_action} />
                <span>→</span>
                <ActionChip action={r.adjusted_action} />
              </Stack>
            </TableCell>
            <TableCell sx={{ maxWidth: 360 }}>{r.reason}</TableCell>
            <TableCell>
              {(r.rule_hits ?? []).map((h: any, i: number) => (
                <Typography key={i} variant="caption" component="div" color={h.blocking ? 'error' : 'text.secondary'}>
                  {h.blocking ? '⛔ ' : '· '}
                  {h.rule}: {h.message}
                </Typography>
              ))}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function OrdersTab({ d }: { d: RunDetail }) {
  if (!d.orders.length) return <Empty>没有订单</Empty>;
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>股票</TableCell>
          <TableCell>动作</TableCell>
          <TableCell>方向 × 数量</TableCell>
          <TableCell>类型 / 限价</TableCell>
          <TableCell>预估金额</TableCell>
          <TableCell>状态</TableCell>
          <TableCell>成交</TableCell>
          <TableCell>信息</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {d.orders.map((o) => (
          <TableRow key={o.id}>
            <TableCell sx={{ fontWeight: 600 }}>{o.intent.symbol}</TableCell>
            <TableCell>
              <ActionChip action={o.intent.action} />
            </TableCell>
            <TableCell>
              {o.intent.side} × {o.intent.quantity}
            </TableCell>
            <TableCell>
              {o.intent.order_type} {o.intent.limit_price ? `@ ${fmtNum(o.intent.limit_price)}` : ''} · {o.intent.time_in_force}
            </TableCell>
            <TableCell>{fmtNum(o.intent.estimated_notional)}</TableCell>
            <TableCell>
              <Chip size="small" label={o.status} color={o.status === 'filled' ? 'success' : o.status === 'rejected' ? 'error' : 'default'} />
            </TableCell>
            <TableCell>
              {o.filled_qty ? `${o.filled_qty} @ ${fmtNum(o.avg_fill_price)}` : '—'}
              {(o.fills ?? []).map((f: any) => (
                <Typography key={f.exec_id} variant="caption" component="div" color="text.secondary">
                  {fmtTime(f.ts, true)} {f.qty} @ {fmtNum(f.price)} 佣金 {fmtNum(f.commission)}
                </Typography>
              ))}
            </TableCell>
            <TableCell sx={{ maxWidth: 280 }}>{o.message}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function LlmCallDialog({ id, onClose }: { id: string | null; onClose: () => void }) {
  const call = useQuery({ queryKey: ['llm_call', id], queryFn: () => api.llmCall(id as string), enabled: !!id });
  const c = call.data;
  let pretty = c?.response_text;
  try {
    pretty = JSON.stringify(JSON.parse(c?.response_text ?? ''), null, 2);
  } catch {
    /* not JSON */
  }
  return (
    <Dialog open={!!id} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle>
        LLM 调用 {c ? `· ${c.agent_id} · ${c.provider}/${c.model} · 第 ${c.attempt} 次` : ''}
        <IconButton onClick={onClose} sx={{ position: 'absolute', right: 8, top: 8 }}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        {!c ? (
          <CircularProgress />
        ) : (
          <Stack spacing={2}>
            {c.error && <Alert severity="error">{c.error}</Alert>}
            <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap' }}>
              <Chip size="small" label={`输入 ${c.input_tokens ?? '?'} tokens`} />
              <Chip size="small" label={`输出 ${c.output_tokens ?? '?'} tokens`} />
              {!!c.cache_read_input_tokens && <Chip size="small" label={`缓存读 ${c.cache_read_input_tokens}`} />}
              <Chip size="small" label={`耗时 ${fmtNum(c.latency_ms, 0)} ms`} />
              <Chip size="small" label={`stop: ${c.stop_reason ?? '—'}`} />
            </Stack>
            {c.request?.system && (
              <div>
                <Typography variant="subtitle2">System</Typography>
                <JsonView value={typeof c.request.system === 'string' ? c.request.system : c.request.system} maxHeight={200} />
              </div>
            )}
            {(c.request?.messages ?? []).map((m: any, i: number) => (
              <div key={i}>
                <Typography variant="subtitle2">{m.role}</Typography>
                <JsonView value={typeof m.content === 'string' ? m.content : m.content} maxHeight={360} />
              </div>
            ))}
            <div>
              <Typography variant="subtitle2">响应</Typography>
              <JsonView value={pretty ?? ''} maxHeight={360} />
            </div>
            {c.request?.json_schema && (
              <div>
                <Typography variant="subtitle2">输出 JSON Schema</Typography>
                <JsonView value={c.request.json_schema} maxHeight={240} asJson />
              </div>
            )}
          </Stack>
        )}
      </DialogContent>
    </Dialog>
  );
}

function LlmTab({ d }: { d: RunDetail }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!d.llm_calls.length) return <Empty>没有 LLM 调用</Empty>;
  return (
    <>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>时间</TableCell>
            <TableCell>Agent</TableCell>
            <TableCell>模型</TableCell>
            <TableCell>尝试</TableCell>
            <TableCell>Token 入 / 出</TableCell>
            <TableCell>耗时</TableCell>
            <TableCell>结果</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {d.llm_calls.map((c) => (
            <TableRow key={c.id} hover sx={{ cursor: 'pointer' }} onClick={() => setOpen(c.id)}>
              <TableCell>{fmtTime(c.created_at, true)}</TableCell>
              <TableCell>
                <AgentLabel agentId={c.agent_id} />
                <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                  {shortId(c.instance_id)}
                </Typography>
              </TableCell>
              <TableCell>
                {c.provider}/{c.model}
              </TableCell>
              <TableCell>{c.attempt}</TableCell>
              <TableCell>
                {c.input_tokens ?? '—'} / {c.output_tokens ?? '—'}
              </TableCell>
              <TableCell>{c.latency_ms !== null ? `${fmtNum(c.latency_ms / 1000, 1)} s` : '—'}</TableCell>
              <TableCell>{c.error ? <Chip size="small" color="error" label={c.error.slice(0, 60)} /> : <Chip size="small" color="success" variant="outlined" label={c.stop_reason ?? 'ok'} />}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <LlmCallDialog id={open} onClose={() => setOpen(null)} />
    </>
  );
}

function AgentsTab({ d }: { d: RunDetail }) {
  if (!d.agent_instances.length) return <Empty>没有 agent 实例</Empty>;
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>实例</TableCell>
          <TableCell>Agent</TableCell>
          <TableCell>角色</TableCell>
          <TableCell>模型</TableCell>
          <TableCell>提示词版本</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {d.agent_instances.map((a) => (
          <TableRow key={a.instance_id}>
            <TableCell sx={{ fontFamily: 'monospace' }}>{shortId(a.instance_id)}</TableCell>
            <TableCell>
              <RouterLink to={`/configs/agents/${a.agent_id}`} style={{ color: 'inherit' }}>
                <AgentLabel agentId={a.agent_id} />
              </RouterLink>
            </TableCell>
            <TableCell>{a.agent_type}</TableCell>
            <TableCell>
              {a.provider}/{a.model}
            </TableCell>
            <TableCell>{a.prompt_version}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

// ------------------------------------------------------------------ page

export function RunDetailPage() {
  const { runId = '' } = useParams();
  const qc = useQueryClient();
  const [tab, setTab] = useState('summary');
  const [live, setLive] = useState<Record<string, StageTiming>>({});
  const [rerun, setRerun] = useState(false);
  const detail = useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.run(runId),
    refetchInterval: (q) => (q.state.data?.run.status === 'running' ? 2000 : false),
  });
  const jobs = useQuery({ queryKey: ['jobs'], queryFn: api.jobs, refetchInterval: 3000 });
  const job = jobs.data?.find((j) => j.run_id === runId && (j.status === 'running' || j.status === 'starting'));
  const cancel = useMutation({ mutationFn: (id: string) => api.cancelJob(id), onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }) });

  useEffect(() => setLive({}), [runId]);
  const { events, state } = useRunEvents(runId, (e) => {
    if (e.event === 'pipeline.stage_start' && e.stage) setLive((p) => ({ ...p, [e.stage!]: { status: 'running', started: e.ts } }));
    if (e.event === 'pipeline.stage_done' && e.stage) {
      setLive((p) => ({ ...p, [e.stage!]: { ...p[e.stage!], status: e.status, seconds: e.seconds } }));
      qc.invalidateQueries({ queryKey: ['run', runId] });
    }
    if (e.event === 'pipeline.finish' || e.event === 'pipeline.cancelled') qc.invalidateQueries({ queryKey: ['run', runId] });
  });

  if (detail.isLoading) return <CircularProgress />;
  if (detail.error || !detail.data) return <Alert severity="error">{String((detail.error as Error)?.message ?? '未找到')}</Alert>;
  const d = detail.data;
  const r = d.run;
  const statuses = stageStatuses(d, live);
  const status = r.status;

  return (
    <Box>
      <PageHeader
        title={
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
            <RouterLink to={`/configs/pipelines/${r.pipeline_name}`} style={{ color: 'inherit', textDecoration: 'none' }}>
              {r.pipeline_name}
            </RouterLink>
            <StatusChip status={status} size="medium" />
            <ModeChip mode={r.mode} offline={r.offline} />
            {d.database === 'offline' && <Chip size="small" color="secondary" variant="outlined" label="离线沙盒数据库" />}
          </Stack>
        }
        subtitle={
          <span>
            Run <code>{r.run_id}</code> · 开始 {fmtTime(r.started_at, true)} · 耗时 {fmtDuration(r.started_at, r.ended_at)} · as_of {fmtTime(r.as_of, true)}
          </span>
        }
        actions={
          <>
            {job && (
              <Button color="error" variant="outlined" startIcon={<StopIcon />} onClick={() => cancel.mutate(job.id)}>
                取消运行
              </Button>
            )}
            <Button startIcon={<ReplayIcon />} onClick={() => setRerun(true)}>
              再次运行
            </Button>
          </>
        }
      />
      <StageProgress stages={r.stages_run} statuses={statuses} runStatus={status} />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Tab value="summary" label="概要" />
        <Tab value="log" label={`实时日志${events.length ? ` (${events.length})` : ''}`} />
        {r.stages_run.includes('selection') && <Tab value="selection" label="选股" />}
        <Tab value="sentiment" label={`舆情 (${d.sentiment_results.length})`} />
        <Tab value="decision" label={`决策 (${d.aggregated_decisions.length})`} />
        <Tab value="risk" label={`风控 (${d.risk_assessments.length})`} />
        <Tab value="orders" label={`订单 (${d.orders.length})`} />
        <Tab value="agents" label={`Agent (${d.agent_instances.length})`} />
        <Tab value="llm" label={`LLM 调用 (${d.llm_calls.length})`} />
        <Tab value="config" label="配置快照" />
      </Tabs>
      {tab === 'summary' && <SummaryTab d={d} statuses={statuses} />}
      {tab === 'log' && <LogView events={events} state={state} />}
      {tab === 'selection' && <SelectionTab d={d} />}
      {tab === 'sentiment' && <SentimentTab d={d} />}
      {tab === 'decision' && <DecisionTab d={d} />}
      {tab === 'risk' && <RiskTab d={d} />}
      {tab === 'orders' && <OrdersTab d={d} />}
      {tab === 'agents' && <AgentsTab d={d} />}
      {tab === 'llm' && <LlmTab d={d} />}
      {tab === 'config' && (
        <Section title={`配置快照 · hash ${r.config_hash.slice(0, 12)}`}>
          <JsonView value={r.config} maxHeight={640} />
        </Section>
      )}
      <RunDialog open={rerun} pipeline={r.pipeline_name} onClose={() => setRerun(false)} />
    </Box>
  );
}
