// Shared editor for one file under configs/: a visual form and the raw YAML stay in sync
// (form edits are merged into the YAML document, keeping comments), validation runs live
// against the server, saving checks the file was not changed meanwhile.

import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Grid,
  List,
  ListItem,
  ListItemText,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';
import RefreshIcon from '@mui/icons-material/Refresh';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutlined';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlined';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link as RouterLink, useBlocker, useNavigate } from 'react-router-dom';
import { ApiError, api, type Diagnostics } from '../api/client';
import { useMeta } from '../api/hooks';
import { applyJson, parseYaml } from '../lib/yamlDoc';
import { CodeEditor } from './CodeEditor';
import { ConfirmDialog, PageHeader } from './common';
import { ErrorsContext } from './SchemaForm';

export interface FormProps {
  data: any;
  onChange: (data: any) => void;
  name: string;
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function ConfigEditor({
  kind,
  name,
  Form,
  side,
  actions,
  lang = 'yaml',
}: {
  kind: string;
  name: string;
  Form?: React.ComponentType<FormProps>;
  side?: (ctx: { data: any; diagnostics: Diagnostics | null }) => React.ReactNode;
  actions?: (ctx: { dirty: boolean; data: any }) => React.ReactNode;
  lang?: 'yaml' | 'jinja';
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: meta } = useMeta();
  const kindInfo = meta?.kinds.find((k) => k.name === kind);
  const file = useQuery({ queryKey: ['config', kind, name], queryFn: () => api.config(kind, name) });
  const [text, setText] = useState<string | null>(null);
  const [tab, setTab] = useState<'form' | 'yaml'>(Form ? 'form' : 'yaml');
  const [saveProblem, setSaveProblem] = useState<{ diagnostics: Diagnostics; syntax: boolean } | null>(null);
  const [conflict, setConflict] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [copyName, setCopyName] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (file.data && text === null) setText(file.data.text);
  }, [file.data, text]);
  useEffect(() => {
    setText(null);
    setConflict(false);
    setSaveProblem(null);
  }, [kind, name]);

  const current = text ?? file.data?.text ?? '';
  const dirty = !!file.data && text !== null && text !== file.data.text;
  const parsed = useMemo(() => (lang === 'yaml' ? parseYaml(current) : null), [current, lang]);

  const debounced = useDebounced(current, 450);
  const validation = useQuery({
    queryKey: ['validate', kind, name, debounced],
    queryFn: () => api.validate(kind, name, debounced),
    enabled: !!file.data,
    placeholderData: (prev) => prev,
  });
  const diagnostics = validation.data ?? null;
  const errorsByPath = useMemo(() => {
    const out: Record<string, string> = {};
    for (const w of diagnostics?.warnings ?? []) if (w.loc.length) out[w.loc.join('.')] = w.message;
    for (const e of diagnostics?.errors ?? []) if (e.loc.length) out[e.loc.join('.')] = e.message;
    return out;
  }, [diagnostics]);

  const save = useMutation({
    mutationFn: (force: boolean) => api.save(kind, name, current, file.data?.etag ?? null, force),
    onSuccess: (saved) => {
      qc.setQueryData(['config', kind, name], saved);
      qc.invalidateQueries({ queryKey: ['configs'] });
      setText(saved.text);
      setSaveProblem(null);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) setConflict(true);
      if (err instanceof ApiError && err.status === 422) {
        const d = err.body?.diagnostics as Diagnostics;
        const syntax = d.errors.some((e) => e.message.includes('语法错误'));
        setSaveProblem({ diagnostics: d, syntax });
      }
    },
  });

  const remove = useMutation({
    mutationFn: () => api.remove(kind, name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['configs'] });
      setText(file.data?.text ?? null);
      navigate(`/configs/${kind}`);
    },
  });

  const duplicate = useMutation({
    mutationFn: async (newName: string) => {
      let body = current;
      if (lang === 'yaml' && kindInfo?.key && parsed?.data) body = applyJson(current, { ...parsed.data, [kindInfo.key]: newName });
      return api.create(kind, newName, body, true);
    },
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['configs'] });
      setCopyName(null);
      navigate(`/configs/${kind}/${created.name}`);
    },
  });

  const onFormChange = useCallback(
    (data: any) => {
      try {
        setText(applyJson(current, data));
        setFormError(null);
      } catch (e) {
        setFormError(String(e));
      }
    },
    [current],
  );

  // Ctrl+S
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (dirty && !save.isPending) save.mutate(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [dirty, save]);

  useEffect(() => {
    if (!dirty) return;
    const onUnload = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', onUnload);
    return () => window.removeEventListener('beforeunload', onUnload);
  }, [dirty]);
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname);

  if (file.isLoading) return <CircularProgress />;
  if (file.error) return <Alert severity="error">{String((file.error as Error).message)}</Alert>;

  const errorCount = diagnostics?.errors.length ?? 0;
  const warnCount = diagnostics?.warnings.length ?? 0;

  return (
    <Box>
      <PageHeader
        title={
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
            <span>{kindInfo?.single ? kindInfo.label : name}</span>
            {dirty && <Chip size="small" color="warning" label="未保存" />}
            {validation.isFetching ? (
              <CircularProgress size={16} />
            ) : diagnostics ? (
              diagnostics.ok ? (
                <Chip size="small" color="success" variant="outlined" icon={<CheckCircleOutlineIcon />} label={warnCount ? `有效 · ${warnCount} 警告` : '有效'} />
              ) : (
                <Chip size="small" color="error" variant="outlined" icon={<ErrorOutlineIcon />} label={`${errorCount} 个错误`} />
              )
            ) : null}
          </Stack>
        }
        subtitle={<span style={{ fontFamily: 'monospace' }}>configs/{file.data?.path}</span>}
        actions={
          <>
            {actions?.({ dirty, data: parsed?.data })}
            {!kindInfo?.single && (
              <>
                <Button size="small" startIcon={<ContentCopyIcon />} onClick={() => setCopyName(`${name}_copy`)}>
                  复制
                </Button>
                <Button size="small" color="error" startIcon={<DeleteOutlineIcon />} onClick={() => setConfirmDelete(true)}>
                  删除
                </Button>
              </>
            )}
            <Button size="small" startIcon={<RefreshIcon />} disabled={!dirty} onClick={() => setText(file.data!.text)}>
              放弃修改
            </Button>
            <Tooltip title="Ctrl+S">
              <span>
                <Button variant="contained" size="small" startIcon={<SaveIcon />} disabled={!dirty || save.isPending} onClick={() => save.mutate(false)}>
                  保存
                </Button>
              </span>
            </Tooltip>
          </>
        }
      />

      {conflict && (
        <Alert
          severity="warning"
          sx={{ mb: 2 }}
          action={
            <Button
              color="inherit"
              size="small"
              onClick={async () => {
                const fresh = await file.refetch();
                if (fresh.data) setText(fresh.data.text);
                setConflict(false);
              }}
            >
              重新加载（丢弃本地修改）
            </Button>
          }
        >
          文件在你编辑期间被其他程序或页面修改了，保存已取消。
        </Alert>
      )}
      {save.error && !(save.error instanceof ApiError && [409, 422].includes(save.error.status)) && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {String((save.error as Error).message)}
        </Alert>
      )}
      {saveProblem && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          action={
            !saveProblem.syntax && (
              <Button color="inherit" size="small" onClick={() => save.mutate(true)}>
                仍然保存
              </Button>
            )
          }
        >
          <AlertTitle>配置校验失败，未保存</AlertTitle>
          {saveProblem.diagnostics.errors.map((e, i) => (
            <div key={i}>{e.message}</div>
          ))}
        </Alert>
      )}

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: side ? 8.5 : 9 }}>
          {Form && (
            <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}>
              <Tab value="form" label="可视化编辑" />
              <Tab value="yaml" label="YAML" />
            </Tabs>
          )}
          {tab === 'form' && Form ? (
            parsed?.error ? (
              <Alert severity="error">YAML 有语法错误，请先在 YAML 标签页修复：{parsed.error}</Alert>
            ) : (
              <ErrorsContext.Provider value={errorsByPath}>
                {formError && (
                  <Alert severity="error" sx={{ mb: 2 }}>
                    {formError}
                  </Alert>
                )}
                <Form data={parsed?.data ?? {}} onChange={onFormChange} name={name} />
              </ErrorsContext.Provider>
            )
          ) : (
            <CodeEditor value={current} onChange={(v) => setText(v)} lang={lang} height="calc(100vh - 260px)" />
          )}
        </Grid>
        <Grid size={{ xs: 12, lg: side ? 3.5 : 3 }}>
          <Stack spacing={2} sx={{ position: { lg: 'sticky' }, top: { lg: 80 } }}>
            <DiagnosticsCard diagnostics={diagnostics} />
            {side?.({ data: parsed?.data, diagnostics })}
            {!!file.data?.used_by.length && (
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="subtitle2" gutterBottom>
                    被引用
                  </Typography>
                  <List dense disablePadding>
                    {file.data.used_by.map((u) => {
                      const [k, n] = u.split('/');
                      return (
                        <ListItem key={u} disableGutters>
                          <ListItemText
                            primary={
                              <RouterLink to={`/configs/${k}/${k === 'schedules' || !n ? k : n}`} style={{ color: 'inherit' }}>
                                {u}
                              </RouterLink>
                            }
                          />
                        </ListItem>
                      );
                    })}
                  </List>
                </CardContent>
              </Card>
            )}
          </Stack>
        </Grid>
      </Grid>

      <ConfirmDialog
        open={confirmDelete}
        title={`删除 ${kind}/${name}？`}
        danger
        confirmText="删除"
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => {
          setConfirmDelete(false);
          remove.mutate();
        }}
      >
        <Typography>文件会先备份到 configs/.web_backups/ 再删除。</Typography>
        {!!file.data?.used_by.length && (
          <Alert severity="warning" sx={{ mt: 2 }}>
            仍被引用：{file.data.used_by.join('，')}。删除后这些配置会校验失败。
          </Alert>
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={copyName !== null}
        title="复制为新文件"
        confirmText="创建"
        onClose={() => setCopyName(null)}
        onConfirm={() => copyName && duplicate.mutate(copyName)}
      >
        <TextField
          autoFocus
          fullWidth
          size="small"
          sx={{ mt: 1 }}
          label="新名称"
          value={copyName ?? ''}
          onChange={(e) => setCopyName(e.target.value)}
          helperText={kindInfo ? `格式 ${kindInfo.name_pattern}` : undefined}
        />
        {duplicate.error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {String((duplicate.error as Error).message)}
          </Alert>
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={blocker.state === 'blocked'}
        title="有未保存的修改"
        confirmText="离开并丢弃"
        danger
        onClose={() => blocker.reset?.()}
        onConfirm={() => blocker.proceed?.()}
      >
        <Typography>离开此页面会丢失未保存的修改。</Typography>
      </ConfirmDialog>
    </Box>
  );
}

export function DiagnosticsCard({ diagnostics }: { diagnostics: Diagnostics | null }) {
  if (!diagnostics) return null;
  const { errors, warnings } = diagnostics;
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>
          校验结果
        </Typography>
        {!errors.length && !warnings.length && (
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center', color: 'success.main' }}>
            <CheckCircleOutlineIcon fontSize="small" />
            <Typography variant="body2">与运行时使用的模型一致，可以运行</Typography>
          </Stack>
        )}
        <Stack spacing={1}>
          {errors.map((e, i) => (
            <Stack key={`e${i}`} direction="row" spacing={1}>
              <ErrorOutlineIcon fontSize="small" color="error" sx={{ mt: '2px' }} />
              <Typography variant="body2" sx={{ wordBreak: 'break-word' }}>
                {e.line ? `第 ${e.line} 行：` : ''}
                {e.message}
              </Typography>
            </Stack>
          ))}
          {warnings.map((w, i) => (
            <Stack key={`w${i}`} direction="row" spacing={1}>
              <WarningAmberIcon fontSize="small" color="warning" sx={{ mt: '2px' }} />
              <Typography variant="body2" sx={{ wordBreak: 'break-word' }}>
                {w.message}
              </Typography>
            </Stack>
          ))}
        </Stack>
        {diagnostics.info?.variables && (
          <Box sx={{ mt: 1.5 }}>
            <Typography variant="caption" color="text.secondary">
              模板变量
            </Typography>
            <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
              {(diagnostics.info.variables as string[]).map((v) => (
                <Chip key={v} size="small" label={v} variant="outlined" sx={{ fontFamily: 'monospace' }} />
              ))}
            </Stack>
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
