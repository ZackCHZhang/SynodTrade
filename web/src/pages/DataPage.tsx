import {
  Alert,
  Box,
  Button,
  Chip,
  Drawer,
  Grid,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import CloseIcon from '@mui/icons-material/Close';
import { DataGrid, type GridColDef, type GridPaginationModel, type GridSortModel } from '@mui/x-data-grid';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api, type ColumnInfo, type Filter } from '../api/client';
import { useMeta } from '../api/hooks';
import { JsonView, PageHeader } from '../components/common';
import { fmtTime } from '../lib/format';

const TABLE_LABEL: Record<string, string> = {
  instruments: '证券',
  market_bars: 'K 线',
  quote_snapshots: '报价快照',
  account_snapshots: '账户快照',
  position_snapshots: '持仓快照',
  pipeline_runs: '流水线运行',
  agent_instances: 'Agent 实例',
  llm_calls: 'LLM 调用',
  selection_results: '选股结果（agent）',
  stock_selections: '选股结果（聚合）',
  sentiment_items: '舆情原始条目',
  sentiment_results: '舆情结果',
  decisions: '决策（agent）',
  aggregated_decisions: '决策（聚合）',
  risk_assessments: '风控评估',
  orders: '订单',
  fills: '成交',
  system_flags: '系统开关',
};

const OPS: [string, string][] = [
  ['eq', '='],
  ['ne', '≠'],
  ['contains', '包含'],
  ['gt', '>'],
  ['gte', '≥'],
  ['lt', '<'],
  ['lte', '≤'],
  ['is_null', '为空'],
  ['not_null', '非空'],
];

function renderCell(value: any, col: ColumnInfo) {
  if (value === null || value === undefined) return <span style={{ opacity: 0.4 }}>null</span>;
  if (col.kind === 'datetime') return fmtTime(value, true);
  if (col.kind === 'boolean') return value ? '✓' : '✗';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function DataPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const table = params.get('table') ?? 'pipeline_runs';
  const db = params.get('db') === 'offline' ? 'offline' : 'main';
  const { data: meta } = useMeta();
  const tables = useQuery({ queryKey: ['tables', db], queryFn: () => api.tables(db), refetchInterval: 10_000 });
  const info = tables.data?.find((t) => t.name === table);
  const [page, setPage] = useState<GridPaginationModel>({ page: 0, pageSize: 50 });
  const [sort, setSort] = useState<GridSortModel>([]);
  const [filters, setFilters] = useState<Filter[]>([]);
  const [draft, setDraft] = useState<Filter>({ column: '', op: 'eq', value: '' });
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    setPage((p) => ({ ...p, page: 0 }));
    setSort([]);
    setSelected(null);
    const preset = params.get('filter');
    setFilters(preset ? JSON.parse(preset) : []);
  }, [table, db]); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useQuery({
    queryKey: ['rows', table, page, sort, filters, db],
    queryFn: () =>
      api.rows(table, {
        offset: page.page * page.pageSize,
        limit: page.pageSize,
        sort: sort[0]?.field,
        desc: sort[0] ? sort[0].sort === 'desc' : true,
        filters,
        db,
      }),
    placeholderData: (prev) => prev,
  });
  const row = useQuery({ queryKey: ['row', table, selected, db], queryFn: () => api.row(table, selected as string, db), enabled: !!selected });

  const columns: GridColDef[] = useMemo(
    () =>
      (info?.columns ?? []).map((c) => ({
        field: c.name,
        headerName: c.name,
        width: c.kind === 'uuid' ? 120 : c.kind === 'datetime' ? 170 : c.kind === 'json' || c.name === 'text' ? 260 : c.kind === 'string' ? 160 : 110,
        renderCell: (p) => renderCell(p.value, c),
        description: `${c.kind}${c.primary_key ? ' · 主键' : ''}${c.foreign_key ? ` · → ${c.foreign_key}` : ''}`,
      })),
    [info],
  );
  const pk = rows.data?.primary_key ?? 'id';
  const gridRows = (rows.data?.rows ?? []).map((r) => ({ __pk: String(r.cells[pk]), ...r.cells }));
  const runId = row.data?.run_id ?? (table === 'pipeline_runs' ? row.data?.run_id : null);

  return (
    <Box>
      <PageHeader
        title="数据库"
        subtitle="所有表的原始数据（只读）。点击行查看完整内容。"
        actions={
          meta?.offline_db && (
            <ToggleButtonGroup size="small" exclusive value={db} onChange={(_, v) => v && setParams({ table, db: v })}>
              <ToggleButton value="main">正式数据库</ToggleButton>
              <ToggleButton value="offline">离线沙盒</ToggleButton>
            </ToggleButtonGroup>
          )
        }
      />
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 3, lg: 2.4 }}>
          <Paper variant="outlined">
            <List dense disablePadding sx={{ maxHeight: 'calc(100vh - 180px)', overflow: 'auto' }}>
              {(tables.data ?? []).map((t) => (
                <ListItemButton key={t.name} selected={t.name === table} onClick={() => setParams({ table: t.name, db })}>
                  <ListItemText
                    primary={TABLE_LABEL[t.name] ?? t.name}
                    secondary={t.name}
                    slotProps={{ secondary: { sx: { fontFamily: 'monospace', fontSize: 11 } } }}
                  />
                  <Chip size="small" label={t.rows.toLocaleString()} variant="outlined" />
                </ListItemButton>
              ))}
            </List>
          </Paper>
        </Grid>
        <Grid size={{ xs: 12, md: 9, lg: 9.6 }}>
          <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap', alignItems: 'center', mb: 1.5 }}>
            {filters.map((f, i) => (
              <Chip
                key={i}
                label={`${f.column} ${OPS.find((o) => o[0] === f.op)?.[1]} ${f.value ?? ''}`}
                onDelete={() => setFilters(filters.filter((_, j) => j !== i))}
                color="primary"
                variant="outlined"
              />
            ))}
            <TextField select size="small" label="列" value={draft.column} onChange={(e) => setDraft({ ...draft, column: e.target.value })} sx={{ minWidth: 150 }}>
              {(info?.columns ?? []).map((c) => (
                <MenuItem key={c.name} value={c.name}>
                  {c.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField select size="small" label="条件" value={draft.op} onChange={(e) => setDraft({ ...draft, op: e.target.value })} sx={{ width: 100 }}>
              {OPS.map(([v, l]) => (
                <MenuItem key={v} value={v}>
                  {l}
                </MenuItem>
              ))}
            </TextField>
            {!['is_null', 'not_null'].includes(draft.op) && (
              <TextField size="small" label="值" value={draft.value} onChange={(e) => setDraft({ ...draft, value: e.target.value })} sx={{ width: 200 }} />
            )}
            <Button
              size="small"
              startIcon={<AddIcon />}
              disabled={!draft.column}
              onClick={() => {
                setFilters([...filters, draft]);
                setPage({ ...page, page: 0 });
                setDraft({ column: draft.column, op: 'eq', value: '' });
              }}
            >
              添加过滤
            </Button>
          </Stack>
          {rows.error && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {String((rows.error as Error).message)}
            </Alert>
          )}
          <Box sx={{ height: 'calc(100vh - 250px)', minHeight: 420 }}>
            <DataGrid
              rows={gridRows}
              getRowId={(r) => r.__pk}
              columns={columns}
              rowCount={rows.data?.total ?? 0}
              paginationMode="server"
              sortingMode="server"
              paginationModel={page}
              onPaginationModelChange={setPage}
              sortModel={sort}
              onSortModelChange={setSort}
              pageSizeOptions={[25, 50, 100, 200]}
              loading={rows.isFetching}
              density="compact"
              disableColumnFilter
              onRowClick={(p) => setSelected(String(p.id))}
              sx={{ '& .MuiDataGrid-row': { cursor: 'pointer' } }}
            />
          </Box>
        </Grid>
      </Grid>
      <Drawer anchor="right" open={!!selected} onClose={() => setSelected(null)} slotProps={{ paper: { sx: { width: { xs: '100%', md: 640 } } } }}>
        <Box sx={{ p: 2 }}>
          <Stack direction="row" sx={{ alignItems: 'center', mb: 2 }}>
            <Typography variant="h6" sx={{ flex: 1 }}>
              {table} · {selected}
            </Typography>
            {runId && (
              <Button size="small" onClick={() => navigate(`/runs/${runId}`)}>
                打开运行
              </Button>
            )}
            <IconButton onClick={() => setSelected(null)}>
              <CloseIcon />
            </IconButton>
          </Stack>
          {row.data && <JsonView value={row.data} maxHeight="calc(100vh - 120px)" />}
        </Box>
      </Drawer>
    </Box>
  );
}
