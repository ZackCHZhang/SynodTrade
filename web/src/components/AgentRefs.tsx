import { Autocomplete, Box, Button, Chip, Collapse, Grid, IconButton, MenuItem, Paper, Stack, TextField, Tooltip, Typography } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined';
import TuneIcon from '@mui/icons-material/Tune';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import { useQuery } from '@tanstack/react-query';
import { useContext, useMemo, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { api } from '../api/client';
import { useConfigs, useMeta } from '../api/hooks';
import { ROLE_LABEL } from '../lib/labels';
import { objectFields } from '../lib/schema';
import { parseYaml } from '../lib/yamlDoc';
import { ErrorsContext, type Path, SchemaFields, pathKey } from './SchemaForm';

export const MODEL_SUGGESTIONS = ['deepseek-chat', 'deepseek-reasoner', 'claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5'];

export function useProviderNames(): string[] {
  const { data } = useQuery({ queryKey: ['config', 'llm_providers', 'llm_providers'], queryFn: () => api.config('llm_providers', 'llm_providers') });
  return useMemo(() => {
    const parsed = data ? parseYaml(data.text).data : null;
    return Object.keys(parsed?.providers ?? {});
  }, [data]);
}

function NumberBox({ label, value, onChange, error, step }: { label: string; value: any; onChange: (v: any) => void; error?: string; step?: number }) {
  return (
    <TextField
      size="small"
      type="number"
      label={label}
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
      error={!!error}
      helperText={error}
      slotProps={{ inputLabel: { shrink: true }, htmlInput: { step: step ?? 1, min: 0 } }}
      fullWidth
    />
  );
}

export function AgentRefsEditor({ role, value, onChange, path, showWeight = true }: { role: string; value: any; onChange: (v: any) => void; path: Path; showWeight?: boolean }) {
  const { data: configs } = useConfigs();
  const { data: meta } = useMeta();
  const errors = useContext(ErrorsContext);
  const providers = useProviderNames();
  const refs: any[] = Array.isArray(value) ? value : [];
  const agents = configs?.agents ?? [];
  const matching = agents.filter((a) => a.role === role);
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const advanced = useMemo(() => (meta ? objectFields(meta.schemas.llm_model, ['provider', 'name']) : null), [meta]);
  const knownModels = useMemo(() => {
    const names = new Set(MODEL_SUGGESTIONS);
    refs.forEach((r) => r?.model?.name && names.add(r.model.name));
    return [...names];
  }, [refs]);

  const update = (i: number, patch: Record<string, any>) => {
    const next = refs.map((r, j) => {
      if (j !== i) return r;
      const merged = { ...r, ...patch };
      for (const k of Object.keys(merged)) if (merged[k] === undefined) delete merged[k];
      return merged;
    });
    onChange(next);
  };
  const updateModel = (i: number, patch: Record<string, any>) => {
    const model = { ...(refs[i]?.model ?? {}), ...patch };
    for (const k of Object.keys(model)) if (model[k] === undefined) delete model[k];
    update(i, { model: Object.keys(model).length ? model : undefined });
  };
  const err = (i: number, ...rest: (string | number)[]) => errors[pathKey([...path, i, ...rest])];

  return (
    <Box>
      <Stack direction="row" sx={{ alignItems: 'center', mb: 1, gap: 1 }}>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          Agent 实例
        </Typography>
        <Chip size="small" variant="outlined" label={`需要${ROLE_LABEL[role] ?? role}角色`} />
        <Typography variant="caption" color="text.secondary">
          共 {refs.reduce((n, r) => n + (Number(r?.count) || 1), 0)} 个实例
        </Typography>
      </Stack>
      <Stack spacing={1}>
        {refs.map((ref, i) => {
          const agent = agents.find((a) => a.name === ref?.agent);
          const mismatch = agent && agent.role !== role;
          return (
            <Paper key={i} variant="outlined" sx={{ p: 1.5 }}>
              <Grid container spacing={1.5} sx={{ alignItems: 'flex-start' }}>
                <Grid size={{ xs: 12, md: 3.2 }}>
                  <TextField
                    select
                    fullWidth
                    size="small"
                    label="Agent"
                    value={ref?.agent ?? ''}
                    onChange={(e) => update(i, { agent: e.target.value })}
                    error={!!(mismatch || err(i, 'agent'))}
                    helperText={mismatch ? `角色是 ${agent?.role}` : err(i, 'agent')}
                    slotProps={{ inputLabel: { shrink: true } }}
                  >
                    {matching.map((a) => (
                      <MenuItem key={a.name} value={a.name}>
                        {a.name}
                      </MenuItem>
                    ))}
                    {ref?.agent && !matching.some((a) => a.name === ref.agent) && (
                      <MenuItem value={ref.agent} disabled>
                        {ref.agent}（{agent ? agent.role : '不存在'}）
                      </MenuItem>
                    )}
                  </TextField>
                </Grid>
                <Grid size={{ xs: 4, md: 1.2 }}>
                  <NumberBox label="实例数" value={ref?.count} onChange={(v) => update(i, { count: v })} error={err(i, 'count')} />
                </Grid>
                {showWeight && (
                  <Grid size={{ xs: 4, md: 1.2 }}>
                    <NumberBox label="权重" value={ref?.weight} step={0.1} onChange={(v) => update(i, { weight: v })} error={err(i, 'weight')} />
                  </Grid>
                )}
                <Grid size={{ xs: 12, md: 2.2 }}>
                  <TextField
                    select
                    fullWidth
                    size="small"
                    label="LLM 供应商"
                    value={ref?.model?.provider ?? ''}
                    onChange={(e) => updateModel(i, { provider: e.target.value || undefined })}
                    error={!!err(i, 'model', 'provider') || !!err(i, 'model')}
                    helperText={err(i, 'model', 'provider')}
                    slotProps={{ inputLabel: { shrink: true } }}
                  >
                    <MenuItem value="">
                      <em>（用 agent 默认）</em>
                    </MenuItem>
                    {providers.map((p) => (
                      <MenuItem key={p} value={p}>
                        {p}
                      </MenuItem>
                    ))}
                    {ref?.model?.provider && !providers.includes(ref.model.provider) && <MenuItem value={ref.model.provider}>{ref.model.provider}（未定义）</MenuItem>}
                  </TextField>
                </Grid>
                <Grid size={{ xs: 12, md: showWeight ? 2.8 : 4 }}>
                  <Autocomplete
                    freeSolo
                    options={knownModels}
                    value={ref?.model?.name ?? ''}
                    onChange={(_, v) => updateModel(i, { name: v || undefined })}
                    onInputChange={(_, v, reason) => reason === 'input' && updateModel(i, { name: v || undefined })}
                    renderInput={(params) => (
                      <TextField
                        {...params}
                        size="small"
                        label="模型名"
                        error={!!err(i, 'model')}
                        helperText={err(i, 'model')}
                        slotProps={{ ...params.slotProps, inputLabel: { shrink: true } }}
                      />
                    )}
                  />
                </Grid>
                <Grid size={{ xs: 12, md: 1.4 }} sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <Tooltip title="高级模型参数">
                    <IconButton size="small" onClick={() => setOpen({ ...open, [i]: !open[i] })} color={open[i] ? 'primary' : 'default'}>
                      <TuneIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  {ref?.agent && (
                    <Tooltip title="编辑该 agent">
                      <IconButton size="small" component={RouterLink} to={`/configs/agents/${ref.agent}`}>
                        <OpenInNewIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  )}
                  <Tooltip title="移除">
                    <IconButton size="small" onClick={() => onChange(refs.filter((_, j) => j !== i))}>
                      <DeleteOutlineIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </Grid>
              </Grid>
              <Collapse in={!!open[i]} unmountOnExit>
                {advanced && (
                  <Box sx={{ mt: 2 }}>
                    <SchemaFields
                      field={advanced}
                      value={ref?.model}
                      path={[...path, i, 'model']}
                      columns={4}
                      onChange={(v) => {
                        const keep = { provider: ref?.model?.provider, name: ref?.model?.name };
                        const model = { ...keep, ...(v ?? {}) };
                        for (const k of Object.keys(model)) if ((model as any)[k] === undefined) delete (model as any)[k];
                        update(i, { model: Object.keys(model).length ? model : undefined });
                      }}
                    />
                  </Box>
                )}
              </Collapse>
            </Paper>
          );
        })}
      </Stack>
      <Button
        size="small"
        startIcon={<AddIcon />}
        sx={{ mt: 1 }}
        disabled={!matching.length}
        onClick={() => {
          const last = refs[refs.length - 1];
          onChange([...refs, { agent: matching[0]?.name, count: 1, ...(last?.model ? { model: { provider: last.model.provider, name: last.model.name } } : {}) }]);
        }}
      >
        添加 agent
      </Button>
      {!matching.length && (
        <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
          还没有{ROLE_LABEL[role] ?? role}角色的 agent，<RouterLink to="/configs/agents">去创建</RouterLink>
        </Typography>
      )}
    </Box>
  );
}
