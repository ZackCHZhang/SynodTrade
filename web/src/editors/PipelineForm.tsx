import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Collapse,
  FormControlLabel,
  Grid,
  IconButton,
  Menu,
  MenuItem,
  Paper,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { useContext, useMemo, useRef, useState } from 'react';
import type { Meta } from '../api/client';
import { useConfigs, useMeta } from '../api/hooks';
import { AgentRefsEditor } from '../components/AgentRefs';
import type { FormProps } from '../components/ConfigEditor';
import { ErrorsContext, FieldEditor, SchemaFields, pathKey } from '../components/SchemaForm';
import { STAGE_INFO, label, stageLabel } from '../lib/labels';
import { normalize, objectFields } from '../lib/schema';
import { setIn } from '../lib/yamlDoc';

const STAGE_TEMPLATES: Record<string, any> = {
  selection: { type: 'selection', sources: [], agents: [], aggregation: { method: 'weighted_score', top_n: 5 } },
  data_update: { type: 'data_update', timeframes: ['1d'], lookback_days: 365 },
  sentiment: { type: 'sentiment', on_error: 'skip', sources: ['reddit', 'stocktwits', 'ibkr_news'], lookback_hours: 24, agents: [] },
  decision: { type: 'decision', agents: [], aggregation: { method: 'weighted_vote', min_confidence: 0.6 } },
  risk: { type: 'risk', rules: 'default', agents: [], combine: 'most_conservative', on_agent_failure: 'reject' },
  trading: { type: 'trading', order_type: 'limit', limit_offset_bps: 5, cancel_after_minutes: 30 },
};

// Keys edited by dedicated widgets instead of the generic schema form.
const CUSTOM_KEYS: Record<string, string[]> = {
  selection: ['sources'],
  sentiment: ['sources', 'source_options'],
  risk: ['rules'],
};

function insertCanonical(stages: any[], stage: any, order: string[]): any[] {
  const rank = (t: string) => (order.includes(t) ? order.indexOf(t) : order.length);
  const idx = stages.findIndex((s) => rank(s?.type) > rank(stage.type));
  return idx < 0 ? [...stages, stage] : [...stages.slice(0, idx), stage, ...stages.slice(idx)];
}

export function PipelineForm({ data, onChange, name }: FormProps) {
  const { data: meta } = useMeta();
  const { data: configs } = useConfigs();
  const cardRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  if (!meta) return null;

  const pipelineSchema = normalize(meta.schemas.pipeline);
  const stages: any[] = Array.isArray(data.stages) ? data.stages : [];
  const set = (path: (string | number)[], v: any) => onChange(setIn(data, path, v));
  const accounts = (configs?.accounts ?? []).map((a) => a.name);
  const isOpen = (i: number) => expanded[i] ?? true;

  return (
    <Stack spacing={2}>
      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 2 }}>
            基本设置
          </Typography>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <TextField fullWidth size="small" label="名称 name" value={data.name ?? ''} disabled helperText={data.name !== name ? `必须等于文件名 ${name}` : '等于文件名'} error={data.name !== name} />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <FieldEditor name="mode" field={pipelineSchema.properties!.mode} value={data.mode} path={['mode']} onChange={(v) => set(['mode'], v)} />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <TextField select fullWidth size="small" label="账户 account" value={data.account ?? ''} onChange={(e) => set(['account'], e.target.value)} slotProps={{ inputLabel: { shrink: true } }} helperText="configs/accounts/">
                {accounts.map((a) => (
                  <MenuItem key={a} value={a}>
                    {a}
                  </MenuItem>
                ))}
                {data.account && !accounts.includes(data.account) && <MenuItem value={data.account}>{data.account}（不存在）</MenuItem>}
              </TextField>
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <FieldEditor
                name="max_capital"
                field={normalize(meta.schemas.pipeline.$defs.BudgetConfig.properties.max_capital, meta.schemas.pipeline.$defs)}
                value={data.budget?.max_capital}
                path={['budget', 'max_capital']}
                required
                onChange={(v) => set(['budget', 'max_capital'], v)}
              />
            </Grid>
            <Grid size={12}>
              <FieldEditor name="universe" field={pipelineSchema.properties!.universe} value={data.universe} path={['universe']} onChange={(v) => set(['universe'], v)} />
            </Grid>
            <Grid size={12}>
              <SchemaFields field={pipelineSchema.properties!.sizing} value={data.sizing} path={['sizing']} onChange={(v) => set(['sizing'], v)} />
            </Grid>
          </Grid>
          {data.mode === 'live' && (
            <Alert severity="error" sx={{ mt: 2 }}>
              live 模式使用真实资金；只有服务器设置了 QUANT_ALLOW_LIVE=1 才能运行。
            </Alert>
          )}
        </CardContent>
      </Card>

      <StageFlow meta={meta} stages={stages} onAdd={(t) => set(['stages'], insertCanonical(stages, STAGE_TEMPLATES[t] ?? { type: t }, meta.stage_order))} onJump={(i) => {
        setExpanded({ ...expanded, [i]: true });
        cardRefs.current[i]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }} />

      {stages.map((stage, i) => (
        <div key={`${stage?.type}-${i}`} ref={(el) => { cardRefs.current[i] = el; }} style={{ scrollMarginTop: 80 }}>
          <StageCard
            meta={meta}
            stage={stage ?? {}}
            index={i}
            count={stages.length}
            open={isOpen(i)}
            onToggle={() => setExpanded({ ...expanded, [i]: !isOpen(i) })}
            onChange={(v) => set(['stages', i], v)}
            onRemove={() => set(['stages'], stages.filter((_, j) => j !== i))}
            onMove={(d) => {
              const next = [...stages];
              const [s] = next.splice(i, 1);
              next.splice(i + d, 0, s);
              set(['stages'], next);
            }}
          />
        </div>
      ))}
    </Stack>
  );
}

function StageFlow({ meta, stages, onAdd, onJump }: { meta: Meta; stages: any[]; onAdd: (type: string) => void; onJump: (i: number) => void }) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const present = new Set(stages.map((s) => s?.type));
  const missing = meta.registry.stages.filter((t) => !present.has(t));
  const nodes: { type: string; index: number | null }[] = [];
  const order = [...meta.stage_order, ...stages.map((s) => s?.type).filter((t) => !meta.stage_order.includes(t))];
  for (const t of order) nodes.push({ type: t, index: stages.findIndex((s) => s?.type === t) });

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            流程
          </Typography>
          <Button size="small" startIcon={<AddIcon />} disabled={!missing.length} onClick={(e) => setAnchor(e.currentTarget)}>
            添加阶段
          </Button>
          <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
            {missing.map((t) => (
              <MenuItem
                key={t}
                onClick={() => {
                  setAnchor(null);
                  onAdd(t);
                }}
              >
                {stageLabel(t)}
                <Typography variant="caption" color="text.secondary" sx={{ ml: 1, fontFamily: 'monospace' }}>
                  {t}
                </Typography>
              </MenuItem>
            ))}
          </Menu>
        </Stack>
        <Stack direction="row" sx={{ alignItems: 'stretch', overflowX: 'auto', pb: 1 }}>
          {nodes.map((n, k) => {
            const stage = n.index !== null && n.index >= 0 ? stages[n.index] : null;
            const info = STAGE_INFO[n.type];
            const color = info?.color ?? '#757575';
            const enabled = stage && stage.enabled !== false;
            const agents = Array.isArray(stage?.agents) ? stage.agents.reduce((s: number, r: any) => s + (Number(r?.count) || 1), 0) : 0;
            return (
              <Stack key={n.type} direction="row" sx={{ alignItems: 'center' }}>
                {k > 0 && <ArrowForwardIcon sx={{ mx: 0.5, color: 'text.disabled' }} fontSize="small" />}
                <Paper
                  variant="outlined"
                  onClick={() => (stage ? onJump(n.index as number) : onAdd(n.type))}
                  sx={{
                    px: 1.5,
                    py: 1,
                    minWidth: 112,
                    cursor: 'pointer',
                    borderStyle: stage ? 'solid' : 'dashed',
                    borderColor: stage ? color : 'divider',
                    borderLeftWidth: stage ? 4 : 1,
                    opacity: stage ? (enabled ? 1 : 0.5) : 0.6,
                    '&:hover': { boxShadow: 2 },
                  }}
                >
                  <Typography variant="body2" sx={{ fontWeight: 600, color: stage ? color : 'text.secondary' }}>
                    {stage ? info?.label ?? n.type : `+ ${info?.label ?? n.type}`}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" component="div">
                    {!stage ? '未配置' : !enabled ? '已禁用' : agents ? `${agents} 个 agent 实例` : stage.on_error === 'skip' ? '失败跳过' : n.type}
                  </Typography>
                </Paper>
              </Stack>
            );
          })}
        </Stack>
      </CardContent>
    </Card>
  );
}

function StageCard({
  meta,
  stage,
  index,
  count,
  open,
  onToggle,
  onChange,
  onRemove,
  onMove,
}: {
  meta: Meta;
  stage: any;
  index: number;
  count: number;
  open: boolean;
  onToggle: () => void;
  onChange: (v: any) => void;
  onRemove: () => void;
  onMove: (delta: number) => void;
}) {
  const errors = useContext(ErrorsContext);
  const type: string = stage.type ?? '?';
  const info = STAGE_INFO[type];
  const color = info?.color ?? '#757575';
  const role = meta.stage_roles[type];
  const schema = meta.schemas.stages[type];
  const custom = CUSTOM_KEYS[type] ?? [];
  const options = useMemo(() => (schema ? objectFields(schema, [...meta.stage_common_keys, ...custom]) : null), [schema, meta, custom]);
  const base = ['stages', index];
  const set = (key: string, v: any) => {
    const next = { ...stage };
    if (v === undefined) delete next[key];
    else next[key] = v;
    onChange(next);
  };
  const stageErrors = Object.entries(errors).filter(([k]) => k === pathKey(base) || k.startsWith(`${pathKey(base)}.`));
  const known = new Set([...(options?.order ?? []), ...meta.stage_common_keys, ...custom]);
  const unknown = Object.keys(stage).filter((k) => !known.has(k));

  return (
    <Card variant="outlined" sx={{ borderLeft: `4px solid ${color}`, opacity: stage.enabled === false ? 0.7 : 1 }}>
      <Stack direction="row" sx={{ alignItems: 'center', px: 2, py: 1, gap: 1, cursor: 'pointer' }} onClick={onToggle}>
        <ExpandMoreIcon sx={{ transform: open ? 'rotate(0deg)' : 'rotate(-90deg)', transition: '0.2s' }} />
        <Typography variant="subtitle1" sx={{ fontWeight: 600, color }}>
          {index + 1}. {info?.label ?? type}
        </Typography>
        <Typography variant="caption" sx={{ fontFamily: 'monospace' }} color="text.secondary">
          {type}
        </Typography>
        {!!stageErrors.length && <Chip size="small" color="error" variant="outlined" label={`${stageErrors.length} 个问题`} />}
        <Box sx={{ flex: 1 }} />
        <Box onClick={(e) => e.stopPropagation()} sx={{ display: 'flex', alignItems: 'center' }}>
          <FormControlLabel
            control={<Switch size="small" checked={stage.enabled !== false} onChange={(e) => set('enabled', e.target.checked ? undefined : false)} />}
            label={<Typography variant="body2">启用</Typography>}
          />
          <TextField
            select
            size="small"
            value={stage.on_error ?? 'abort'}
            onChange={(e) => set('on_error', e.target.value === 'abort' ? undefined : e.target.value)}
            sx={{ width: 170, mr: 1 }}
            label={label('on_error')}
            slotProps={{ inputLabel: { shrink: true } }}
          >
            <MenuItem value="abort">abort 终止运行</MenuItem>
            <MenuItem value="skip">skip 跳过继续</MenuItem>
          </TextField>
          <Tooltip title="上移">
            <span>
              <IconButton size="small" disabled={index === 0} onClick={() => onMove(-1)}>
                <ArrowUpwardIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="下移">
            <span>
              <IconButton size="small" disabled={index === count - 1} onClick={() => onMove(1)}>
                <ArrowDownwardIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="删除阶段">
            <IconButton size="small" onClick={onRemove}>
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      </Stack>
      <Collapse in={open} unmountOnExit>
        <CardContent sx={{ pt: 0 }}>
          {info && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              {info.desc}
            </Typography>
          )}
          {errors[pathKey(base)] && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {errors[pathKey(base)]}
            </Alert>
          )}
          <Stack spacing={2.5}>
            {role && <AgentRefsEditor role={role} value={stage.agents} path={[...base, 'agents']} showWeight={type === 'decision' || type === 'selection'} onChange={(v) => set('agents', v)} />}
            {type === 'selection' && <CandidateSources meta={meta} value={stage.sources} path={[...base, 'sources']} onChange={(v) => set('sources', v)} />}
            {type === 'sentiment' && <SentimentSources meta={meta} stage={stage} base={base} set={set} />}
            {type === 'risk' && <RiskRulesSelect value={stage.rules} path={[...base, 'rules']} onChange={(v) => set('rules', v)} />}
            {options && options.order && options.order.length > 0 && (
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 600, mb: 1.5 }}>
                  阶段选项
                </Typography>
                <SchemaFields field={options} value={stage} path={base} onChange={(v) => onChange({ ...Object.fromEntries(Object.entries(stage).filter(([k]) => !options.order!.includes(k))), ...(v ?? {}) })} />
              </Box>
            )}
            {!schema && <Alert severity="info">自定义阶段类型 {type}：没有可用的选项模型，请在 YAML 标签页编辑选项。</Alert>}
            {!!unknown.length && (
              <Alert severity="warning">
                未识别的选项（运行时会被忽略）：{unknown.join('、')}。可在 YAML 标签页修改。
              </Alert>
            )}
          </Stack>
        </CardContent>
      </Collapse>
    </Card>
  );
}

function RiskRulesSelect({ value, onChange, path }: { value: any; onChange: (v: any) => void; path: (string | number)[] }) {
  const { data: configs } = useConfigs();
  const errors = useContext(ErrorsContext);
  const rules = (configs?.risk ?? []).map((r) => r.name);
  const err = errors[pathKey(path)];
  return (
    <TextField
      select
      size="small"
      sx={{ maxWidth: 360 }}
      label="风控规则 rules"
      value={value ?? 'default'}
      onChange={(e) => onChange(e.target.value === 'default' ? undefined : e.target.value)}
      error={!!err}
      helperText={err ?? 'configs/risk/<名称>.yaml，硬规则先于风控 agent 执行'}
      slotProps={{ inputLabel: { shrink: true } }}
    >
      {rules.map((r) => (
        <MenuItem key={r} value={r}>
          {r}
        </MenuItem>
      ))}
      {value && !rules.includes(value) && <MenuItem value={value}>{value}（不存在）</MenuItem>}
    </TextField>
  );
}

function CandidateSources({ meta, value, onChange, path }: { meta: Meta; value: any; onChange: (v: any) => void; path: (string | number)[] }) {
  const sources: any[] = Array.isArray(value) ? value : [];
  const types = meta.registry.candidate_sources;
  const update = (i: number, v: any) => onChange(sources.map((s, j) => (j === i ? v : s)));
  return (
    <Box>
      <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
        候选来源 sources
        <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
          流水线的 universe 也是候选来源（include_universe）
        </Typography>
      </Typography>
      <Stack spacing={1}>
        {sources.map((s, i) => {
          const schema = meta.schemas.candidate_sources[s?.type];
          const fields = schema ? objectFields(schema, ['name']) : null;
          return (
            <Paper key={i} variant="outlined" sx={{ p: 1.5 }}>
              <Stack direction="row" spacing={1.5} sx={{ mb: 2, alignItems: 'center' }}>
                <TextField select size="small" label="类型" value={s?.type ?? ''} sx={{ width: 200 }} onChange={(e) => update(i, { type: e.target.value })} slotProps={{ inputLabel: { shrink: true } }}>
                  {types.map((t) => (
                    <MenuItem key={t} value={t}>
                      {t}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  size="small"
                  label="名称（可选，多个同类来源时必填）"
                  value={s?.name ?? ''}
                  sx={{ width: 280 }}
                  onChange={(e) => update(i, { ...s, name: e.target.value || undefined })}
                  slotProps={{ inputLabel: { shrink: true } }}
                />
                <Box sx={{ flex: 1 }} />
                <IconButton size="small" onClick={() => onChange(sources.filter((_, j) => j !== i))}>
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              </Stack>
              {fields && (
                <SchemaFields
                  field={fields}
                  value={s}
                  path={[...path, i]}
                  columns={4}
                  onChange={(v) => update(i, { type: s.type, ...(s.name ? { name: s.name } : {}), ...(v ?? {}) })}
                />
              )}
            </Paper>
          );
        })}
      </Stack>
      <Button size="small" startIcon={<AddIcon />} sx={{ mt: 1 }} onClick={() => onChange([...sources, { type: types.includes('ibkr_scanner') ? 'ibkr_scanner' : types[0] }])}>
        添加来源
      </Button>
    </Box>
  );
}

function SentimentSources({ meta, stage, base, set }: { meta: Meta; stage: any; base: (string | number)[]; set: (key: string, v: any) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const errors = useContext(ErrorsContext);
  const selected: string[] = Array.isArray(stage.sources) ? stage.sources : [];
  const options = stage.source_options ?? {};
  const all = meta.registry.sentiment_sources;
  const err = errors[pathKey([...base, 'sources'])];
  return (
    <Box>
      <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
        舆情来源 sources
      </Typography>
      <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
        {all.map((src) => {
          const on = selected.includes(src);
          return (
            <Chip
              key={src}
              label={src}
              color={on ? 'primary' : 'default'}
              variant={on ? 'filled' : 'outlined'}
              onClick={() => set('sources', on ? selected.filter((x) => x !== src) : [...selected, src])}
            />
          );
        })}
        <Box sx={{ flex: 1 }} />
        {selected.map((src) => (
          <Button key={src} size="small" variant={open === src ? 'contained' : 'text'} onClick={() => setOpen(open === src ? null : src)}>
            {src} 选项{options[src] ? ' •' : ''}
          </Button>
        ))}
      </Stack>
      {err && (
        <Typography variant="caption" color="error">
          {err}
        </Typography>
      )}
      {open && meta.schemas.sentiment_sources[open] && (
        <Paper variant="outlined" sx={{ p: 1.5, mt: 1.5 }}>
          <Typography variant="body2" sx={{ fontWeight: 600, mb: 1.5 }}>
            {open} 的选项 source_options.{open}
          </Typography>
          <SchemaFields
            field={objectFields(meta.schemas.sentiment_sources[open])}
            value={options[open]}
            path={[...base, 'source_options', open]}
            columns={4}
            onChange={(v) => {
              const next = { ...options };
              if (v === undefined) delete next[open];
              else next[open] = v;
              set('source_options', Object.keys(next).length ? next : undefined);
            }}
          />
        </Paper>
      )}
    </Box>
  );
}
