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
import { locale } from '../i18n';
import { fmtDuration, fmtNum, fmtSeconds, fmtTime, shortId } from '../lib/format';
import { STAGE_INFO, stageLabel } from '../lib/labels';
import { t } from '../i18n';

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
            {t('Progress')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('{done} / {total} stages', { done, total: stages.length })}
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
        <TextField size="small" placeholder={t('Filter…')} value={filter} onChange={(e) => setFilter(e.target.value)} />
        <TextField select size="small" value={level} onChange={(e) => setLevel(e.target.value)} sx={{ width: 140 }} label={t('Level')} slotProps={{ inputLabel: { shrink: true } }}>
          <MenuItem value="">{t('All')}</MenuItem>
          {['info', 'warning', 'error', 'debug'].map((l) => (
            <MenuItem key={l} value={l}>
              {l}
            </MenuItem>
          ))}
        </TextField>
        <FormControlLabel control={<Switch size="small" checked={follow} onChange={(e) => setFollow(e.target.checked)} />} label={t('Auto-scroll')} />
        <Chip size="small" label={t(state === 'live' ? 'Live' : state === 'ended' ? 'Ended' : state === 'error' ? 'Disconnected' : 'Connecting')} color={state === 'live' ? 'success' : 'default'} variant="outlined" />
        <Typography variant="caption" color="text.secondary">
          {t('{shown} / {total} entries', { shown: shown.length, total: events.length })}
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
        {!events.length && <Empty>{state === 'ended' ? t('No logs (this run was not started by this server; only its results in the database are available)') : t('Waiting for events…')}</Empty>}
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
  if (!symbols.length) return <Empty>{t('No results yet')}</Empty>;
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>{t('Symbol')}</TableCell>
          <TableCell>{t('Decision')}</TableCell>
          <TableCell>{t('Score')}</TableCell>
          <TableCell>{t('After risk')}</TableCell>
          <TableCell>{t('Orders')}</TableCell>
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
                    {o.filled_qty ? ` · ${t('filled')} ${o.filled_qty} @ ${fmtNum(o.avg_fill_price)}` : ''}
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
        <Section title={t('Results per symbol')}>
          <SymbolOverview d={d} />
        </Section>
        {!!s?.errors?.length && (
          <Section title={t('Errors')}>
            {s.errors.map((e, i) => (
              <Alert key={i} severity={e.skipped ? 'warning' : 'error'} sx={{ mb: 1 }}>
                <b>{stageLabel(e.stage)}</b> ({e.error_type}{e.skipped ? `, ${t('skipped')}` : ''}): {e.message}
              </Alert>
            ))}
          </Section>
        )}
        {d.run.error && !s?.errors?.length && <Alert severity="error">{d.run.error}</Alert>}
      </Grid>
      <Grid size={{ xs: 12, lg: 5 }}>
        <Section title={t('Stage durations')}>
          {timed.length ? (
            <BarChart
              height={220}
              layout="horizontal"
              yAxis={[{ scaleType: 'band', data: timed.map(stageLabel), width: 72 }]}
              series={[{ data: timed.map((x) => statuses[x].seconds ?? 0), label: t('seconds'), color: '#1e88e5' }]}
              hideLegend
            />
          ) : (
            <Empty>{t('Shown after the run ends')}</Empty>
          )}
        </Section>
        <Section title={t('Counts')}>
          <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap' }}>
            <Chip label={`${t('Agent instances')} ${d.agent_instances.length}`} />
            <Chip label={`${t('LLM calls')} ${d.llm_calls.length}`} />
            <Chip label={`${t('Sentiment results')} ${d.sentiment_results.length}`} />
            <Chip label={`${t('Decisions')} ${d.decisions.length}`} />
            <Chip label={`${t('Risk assessments')} ${d.risk_assessments.length}`} />
            <Chip label={`${t('Orders')} ${d.orders.length}`} />
            <Chip
              label={t('Tokens {in} in / {out} out', {
                in: d.llm_calls.reduce((n, c) => n + (c.input_tokens ?? 0), 0).toLocaleString(locale()),
                out: d.llm_calls.reduce((n, c) => n + (c.output_tokens ?? 0), 0).toLocaleString(locale()),
              })}
            />
          </Stack>
        </Section>
      </Grid>
    </Grid>
  );
}

function SelectionTab({ d }: { d: RunDetail }) {
  const sel = d.stock_selection;
  if (!sel && !d.selection_results.length) return <Empty>{t('This run has no selection stage')}</Empty>;
  const scores: [string, number][] = sel ? Object.entries<number>(sel.scores).sort((a, b) => b[1] - a[1]) : [];
  return (
    <Grid container spacing={2}>
      {sel && (
        <Grid size={{ xs: 12, lg: 5 }}>
          <Section title={t('Final selection ({method})', { method: sel.method })}>
            <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap', mb: 2 }}>
              {sel.selected.map((s: string) => (
                <Chip key={s} color="primary" label={`${s} ${fmtNum(sel.scores[s], 2)}`} />
              ))}
              {sel.holdings.map((s: string) => (
                <Chip key={s} variant="outlined" label={`${s} (${t('kept as holding')})`} />
              ))}
              {!sel.selected.length && <Typography color="text.secondary">{t('No symbols selected')}</Typography>}
            </Stack>
            {!!scores.length && (
              <BarChart
                height={Math.max(160, scores.length * 26)}
                layout="horizontal"
                yAxis={[{ scaleType: 'band', data: scores.map((x) => x[0]), width: 64 }]}
                xAxis={[{ min: 0, max: 1 }]}
                series={[{ data: scores.map((x) => x[1]), label: t('Aggregated score'), color: '#8e24aa' }]}
                hideLegend
              />
            )}
            {!!Object.keys(sel.rejected ?? {}).length && (
              <>
                <Typography variant="subtitle2" sx={{ mt: 2 }}>
                  {t('Dropped by the screen')}
                </Typography>
                {Object.entries<string>(sel.rejected).map(([s, why]) => (
                  <Typography key={s} variant="body2">
                    <b>{s}</b>: {why}
                  </Typography>
                ))}
              </>
            )}
          </Section>
        </Grid>
      )}
      <Grid size={{ xs: 12, lg: sel ? 7 : 12 }}>
        {d.selection_results.map((r) => (
          <Section key={r.id} title={<AgentLabel agentId={r.agent_id}>{`${r.agent_id} · ${shortId(r.instance_id)}`}</AgentLabel>} actions={r.error && <Chip size="small" color="error" label={t('Failed')} />}>
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
  if (!d.sentiment_results.length) return <Empty>{t('No sentiment results')}</Empty>;
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>{t('Symbol')}</TableCell>
          <TableCell>Agent</TableCell>
          <TableCell>{t('Sentiment score')}</TableCell>
          <TableCell>{t('Confidence')}</TableCell>
          <TableCell>{t('Summary')}</TableCell>
          <TableCell>{t('Key events')}</TableCell>
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
              {r.error && <Chip size="small" color="error" label={t('Failed')} sx={{ mr: 1 }} />}
              {r.summary}
            </TableCell>
            <TableCell>{(r.key_events ?? []).join('; ')}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function DecisionTab({ d }: { d: RunDetail }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!d.aggregated_decisions.length && !d.decisions.length) return <Empty>{t('No decisions')}</Empty>;
  const bySymbol: Record<string, any[]> = {};
  for (const x of d.decisions) (bySymbol[x.symbol] ??= []).push(x);
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>{t('Symbol')}</TableCell>
          <TableCell>{t('Final action')}</TableCell>
          <TableCell>{t('Method')}</TableCell>
          <TableCell>{t('Score')}</TableCell>
          <TableCell>{t('Votes')}</TableCell>
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
                    <Tooltip key={v.instance_id} title={`${v.agent_id} · ${t('Confidence')} ${fmtNum(v.confidence, 2)} · ${t('Weight')} ${v.weight}`}>
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
                      {shortId(x.instance_id)} · {t('Confidence')} {fmtNum(x.confidence, 2)}
                    </Typography>
                  </TableCell>
                  <TableCell colSpan={2}>
                    {x.error && <Chip size="small" color="error" label={x.error} sx={{ mb: 0.5 }} />}
                    <Typography variant="body2">{x.reasoning}</Typography>
                    {!!x.referenced_data_ids?.length && (
                      <Typography variant="caption" color="text.secondary">
                        {t('References: {list}', { list: x.referenced_data_ids.join(', ') })}
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
  if (!d.risk_assessments.length) return <Empty>{t('No risk assessments')}</Empty>;
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>{t('Symbol')}</TableCell>
          <TableCell>{t('Source')}</TableCell>
          <TableCell>{t('Verdict')}</TableCell>
          <TableCell>{t('Action')}</TableCell>
          <TableCell>{t('Reason')}</TableCell>
          <TableCell>{t('Rules hit')}</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {d.risk_assessments.map((r) => (
          <TableRow key={r.id}>
            <TableCell sx={{ fontWeight: 600 }}>{r.symbol}</TableCell>
            <TableCell>
              {r.source === 'rules' ? <Chip size="small" label={t('Hard rules')} /> : r.source === 'final' ? r.source : <AgentLabel agentId={r.source} />}
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
  if (!d.orders.length) return <Empty>{t('No orders')}</Empty>;
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>{t('Symbol')}</TableCell>
          <TableCell>{t('Action')}</TableCell>
          <TableCell>{t('Side × quantity')}</TableCell>
          <TableCell>{t('Type / limit')}</TableCell>
          <TableCell>{t('Est. notional')}</TableCell>
          <TableCell>{t('Status')}</TableCell>
          <TableCell>{t('Fills')}</TableCell>
          <TableCell>{t('Message')}</TableCell>
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
                  {fmtTime(f.ts, true)} {f.qty} @ {fmtNum(f.price)} {t('commission')} {fmtNum(f.commission)}
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
        {t('LLM call')} {c ? `· ${c.agent_id} · ${c.provider}/${c.model} · ${t('attempt {n}', { n: c.attempt })}` : ''}
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
              <Chip size="small" label={t('Input {n} tokens', { n: c.input_tokens ?? '?' })} />
              <Chip size="small" label={t('Output {n} tokens', { n: c.output_tokens ?? '?' })} />
              {!!c.cache_read_input_tokens && <Chip size="small" label={t('Cache read {n}', { n: c.cache_read_input_tokens })} />}
              <Chip size="small" label={t('Latency {n} ms', { n: fmtNum(c.latency_ms, 0) })} />
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
              <Typography variant="subtitle2">{t('Response')}</Typography>
              <JsonView value={pretty ?? ''} maxHeight={360} />
            </div>
            {c.request?.json_schema && (
              <div>
                <Typography variant="subtitle2">{t('Output JSON Schema')}</Typography>
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
  if (!d.llm_calls.length) return <Empty>{t('No LLM calls')}</Empty>;
  return (
    <>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>{t('Time')}</TableCell>
            <TableCell>Agent</TableCell>
            <TableCell>{t('Model')}</TableCell>
            <TableCell>{t('Attempt')}</TableCell>
            <TableCell>{t('Tokens in / out')}</TableCell>
            <TableCell>{t('Duration')}</TableCell>
            <TableCell>{t('Result')}</TableCell>
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
  if (!d.agent_instances.length) return <Empty>{t('No agent instances')}</Empty>;
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>{t('Instance')}</TableCell>
          <TableCell>Agent</TableCell>
          <TableCell>{t('Role')}</TableCell>
          <TableCell>{t('Model')}</TableCell>
          <TableCell>{t('Prompt version')}</TableCell>
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
  if (detail.error || !detail.data) return <Alert severity="error">{String((detail.error as Error)?.message ?? t('Not found'))}</Alert>;
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
            {d.database === 'offline' && <Chip size="small" color="secondary" variant="outlined" label={t('Offline sandbox database')} />}
          </Stack>
        }
        subtitle={
          <span>
            Run <code>{r.run_id}</code> · {t('started')} {fmtTime(r.started_at, true)} · {t('took {d}', { d: fmtDuration(r.started_at, r.ended_at) })} · as_of {fmtTime(r.as_of, true)}
          </span>
        }
        actions={
          <>
            {job && (
              <Button color="error" variant="outlined" startIcon={<StopIcon />} onClick={() => cancel.mutate(job.id)}>
                {t('Cancel run')}
              </Button>
            )}
            <Button startIcon={<ReplayIcon />} onClick={() => setRerun(true)}>
              {t('Run again')}
            </Button>
          </>
        }
      />
      <StageProgress stages={r.stages_run} statuses={statuses} runStatus={status} />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Tab value="summary" label={t('Summary')} />
        <Tab value="log" label={`${t('Live log')}${events.length ? ` (${events.length})` : ''}`} />
        {r.stages_run.includes('selection') && <Tab value="selection" label={t('Selection')} />}
        <Tab value="sentiment" label={`${t('Sentiment')} (${d.sentiment_results.length})`} />
        <Tab value="decision" label={`${t('Decision')} (${d.aggregated_decisions.length})`} />
        <Tab value="risk" label={`${t('Risk')} (${d.risk_assessments.length})`} />
        <Tab value="orders" label={`${t('Orders')} (${d.orders.length})`} />
        <Tab value="agents" label={`Agent (${d.agent_instances.length})`} />
        <Tab value="llm" label={`${t('LLM calls')} (${d.llm_calls.length})`} />
        <Tab value="config" label={t('Config snapshot')} />
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
        <Section title={`${t('Config snapshot')} · hash ${r.config_hash.slice(0, 12)}`}>
          <JsonView value={r.config} maxHeight={640} />
        </Section>
      )}
      <RunDialog open={rerun} pipeline={r.pipeline_name} onClose={() => setRerun(false)} />
    </Box>
  );
}
