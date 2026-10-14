import { Alert, Box, Button, Card, CardContent, Collapse, Grid, MenuItem, Stack, TextField, Typography } from '@mui/material';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import { useQuery } from '@tanstack/react-query';
import { useContext, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { api } from '../api/client';
import { useConfigs, useMeta } from '../api/hooks';
import { MODEL_SUGGESTIONS, useProviderNames } from '../components/AgentRefs';
import { AgentAvatar } from '../components/AgentAvatar';
import { CodeEditor } from '../components/CodeEditor';
import type { FormProps } from '../components/ConfigEditor';
import { ErrorsContext, FieldEditor, SchemaFields } from '../components/SchemaForm';
import { roleLabel, withKey } from '../lib/labels';
import { normalize, objectFields } from '../lib/schema';
import { setIn } from '../lib/yamlDoc';
import { t } from '../i18n';

export function AgentForm({ data, onChange, name }: FormProps) {
  const { data: meta } = useMeta();
  const { data: configs } = useConfigs();
  const errors = useContext(ErrorsContext);
  const providers = useProviderNames();
  const [showTemplate, setShowTemplate] = useState(false);
  const prompts = (configs?.prompts ?? []).map((p) => `prompts/${p.name}.j2`);
  const templateName = typeof data.prompt_template === 'string' ? data.prompt_template.replace(/^prompts\//, '').replace(/\.j2$/, '') : null;
  const template = useQuery({
    queryKey: ['config', 'prompts', templateName],
    queryFn: () => api.config('prompts', templateName as string),
    enabled: showTemplate && !!templateName,
  });
  if (!meta) return null;
  const schema = normalize(meta.schemas.agent);
  const modelSchema = objectFields(meta.schemas.llm_model, ['provider', 'name']);
  const set = (path: (string | number)[], v: any) => onChange(setIn(data, path, v));
  const params = data.params && typeof data.params === 'object' ? data.params : {};
  const otherParams = Object.fromEntries(Object.entries(params).filter(([k]) => k !== 'instructions'));

  return (
    <Stack spacing={2}>
      <Card variant="outlined">
        <CardContent>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <TextField fullWidth size="small" label="Agent ID agent_id" value={data.agent_id ?? ''} disabled error={data.agent_id !== name} helperText={data.agent_id !== name ? t('Must equal the file name {name}', { name }) : t('Equals the file name')} />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <TextField
                select
                fullWidth
                size="small"
                label={withKey('Role', 'role')}
                value={data.role ?? ''}
                onChange={(e) => set(['role'], e.target.value)}
                error={!!errors.role}
                helperText={errors.role ?? t('Decides which stage it can be used in')}
                slotProps={{ inputLabel: { shrink: true } }}
              >
                {meta.agent_roles.map((r) => (
                  <MenuItem key={r} value={r}>
                    {roleLabel(r)} <Typography component="span" variant="caption" sx={{ ml: 1, fontFamily: 'monospace' }}>{r}</Typography>
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <FieldEditor name="prompt_version" field={schema.properties!.prompt_version} value={data.prompt_version} path={['prompt_version']} required onChange={(v) => set(['prompt_version'], v)} />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <TextField
                select
                fullWidth
                size="small"
                label={withKey('Implementation', 'impl')}
                value={data.impl ?? ''}
                onChange={(e) => set(['impl'], e.target.value || undefined)}
                helperText={t('Empty = the implementation named after the role')}
                slotProps={{ inputLabel: { shrink: true } }}
              >
                <MenuItem value="">
                  <em>{t('Default ({value})', { value: data.role ?? t('role') })}</em>
                </MenuItem>
                {meta.registry.agents.map((a) => (
                  <MenuItem key={a} value={a}>
                    {a}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid size={{ xs: 12, md: 8 }}>
              <TextField
                select
                fullWidth
                size="small"
                label={withKey('Prompt template', 'prompt_template')}
                value={data.prompt_template ?? ''}
                onChange={(e) => set(['prompt_template'], e.target.value)}
                error={!!errors.prompt_template}
                helperText={errors.prompt_template ?? t('Path relative to configs/agents/')}
                slotProps={{ inputLabel: { shrink: true } }}
              >
                {prompts.map((p) => (
                  <MenuItem key={p} value={p}>
                    {p}
                  </MenuItem>
                ))}
                {data.prompt_template && !prompts.includes(data.prompt_template) && <MenuItem value={data.prompt_template}>{data.prompt_template} ({t('missing')})</MenuItem>}
              </TextField>
            </Grid>
            <Grid size={{ xs: 12, md: 4 }} sx={{ display: 'flex', gap: 1, alignItems: 'flex-start' }}>
              <Button size="small" onClick={() => setShowTemplate(!showTemplate)} disabled={!templateName}>
                {showTemplate ? t('Hide template') : t('Preview template')}
              </Button>
              {templateName && (
                <Button size="small" endIcon={<OpenInNewIcon />} component={RouterLink} to={`/configs/prompts/${templateName}`}>
                  {t('Edit template')}
                </Button>
              )}
            </Grid>
            <Grid size={12}>
              <Stack direction="row" spacing={2} sx={{ alignItems: 'flex-start' }}>
                <AgentAvatar agentId={name} size={56} src={typeof data.avatar === 'string' ? data.avatar : null} role={data.role} />
                <TextField
                  fullWidth
                  size="small"
                  label={withKey('Avatar', 'avatar')}
                  placeholder="https://..."
                  value={data.avatar ?? ''}
                  onChange={(e) => set(['avatar'], e.target.value.trim() || undefined)}
                  error={!!errors.avatar}
                  helperText={errors.avatar ?? t('Image URL (http/https), shown only in the console; empty shows initials colored by role')}
                  slotProps={{ inputLabel: { shrink: true } }}
                />
              </Stack>
            </Grid>
            <Grid size={12}>
              <Collapse in={showTemplate} unmountOnExit>
                {template.data && <CodeEditor value={template.data.text} lang="jinja" readOnly height="320px" />}
              </Collapse>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 2 }}>
            {t('Persona and strategy')}
          </Typography>
          <Stack spacing={2}>
            <FieldEditor name="persona" field={schema.properties!.persona} value={data.persona} path={['persona']} required onChange={(v) => set(['persona'], v)} />
            <TextField
              fullWidth
              multiline
              minRows={3}
              size="small"
              label={withKey('Strategy instructions', 'params.instructions')}
              value={params.instructions ?? ''}
              onChange={(e) => set(['params', 'instructions'], e.target.value || undefined)}
              helperText={t('Inserted into {{ instructions }} in the prompt template')}
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <FieldEditor
              name="params"
              field={{ kind: 'map', nullable: false, hasDefault: false, values: { kind: 'any', nullable: true, hasDefault: false } }}
              value={Object.keys(otherParams).length ? otherParams : undefined}
              path={['params']}
              onChange={(v) => set(['params'], { ...(params.instructions ? { instructions: params.instructions } : {}), ...(v ?? {}) })}
            />
          </Stack>
        </CardContent>
      </Card>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {t('Default model (optional)')}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t('The model is usually chosen when a pipeline instantiates the agent; this sets the default when none is given.')}
          </Typography>
          {data.model ? (
            <Box>
              <Grid container spacing={2} sx={{ mb: 2 }}>
                <Grid size={{ xs: 12, sm: 6 }}>
                  <TextField select fullWidth size="small" label={withKey('LLM provider', 'provider')} value={data.model.provider ?? ''} onChange={(e) => set(['model', 'provider'], e.target.value || undefined)} slotProps={{ inputLabel: { shrink: true } }}>
                    {providers.map((p) => (
                      <MenuItem key={p} value={p}>
                        {p}
                      </MenuItem>
                    ))}
                  </TextField>
                </Grid>
                <Grid size={{ xs: 12, sm: 6 }}>
                  <FieldEditor name="name" field={{ kind: 'string', nullable: false, hasDefault: false }} value={data.model.name} path={['model', 'name']} required options={MODEL_SUGGESTIONS} onChange={(v) => set(['model', 'name'], v)} />
                </Grid>
              </Grid>
              <SchemaFields field={modelSchema} value={data.model} path={['model']} columns={4} onChange={(v) => set(['model'], { provider: data.model.provider, name: data.model.name, ...(v ?? {}) })} />
              <Button size="small" color="error" sx={{ mt: 1 }} onClick={() => set(['model'], undefined)}>
                {t('Remove default model')}
              </Button>
            </Box>
          ) : (
            <Button size="small" variant="outlined" onClick={() => set(['model'], { provider: providers[0] ?? 'anthropic', name: '' })}>
              {t('Set default model')}
            </Button>
          )}
          {errors.model && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {errors.model}
            </Alert>
          )}
        </CardContent>
      </Card>
    </Stack>
  );
}
