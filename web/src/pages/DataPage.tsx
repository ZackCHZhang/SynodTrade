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
import { locale, t } from '../i18n';

const TABLE_LABEL: Record<string, string> = {
  instruments: 'Instruments',
  market_bars: 'Bars',
  quote_snapshots: 'Quote snapshots',
  account_snapshots: 'Account snapshots',
  position_snapshots: 'Position snapshots',
  pipeline_runs: 'Pipeline runs',
  agent_instances: 'Agent instances',
  llm_calls: 'LLM calls',
  selection_results: 'Selection results (agent)',
  stock_selections: 'Selection results (aggregated)',
  sentiment_items: 'Raw sentiment items',
  sentiment_results: 'Sentiment results',
  decisions: 'Decisions (agent)',
  aggregated_decisions: 'Decisions (aggregated)',
  risk_assessments: 'Risk assessments',
  orders: 'Orders',
  fills: 'Fills',
  system_flags: 'System flags',
};

const OPS: [string, string][] = [
  ['eq', '='],
  ['ne', '≠'],
  ['contains', 'contains'],
  ['gt', '>'],
  ['gte', '≥'],
  ['lt', '<'],
  ['lte', '≤'],
  ['is_null', 'is empty'],
  ['not_null', 'is not empty'],
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
        description: `${c.kind}${c.primary_key ? ` · ${t('primary key')}` : ''}${c.foreign_key ? ` · → ${c.foreign_key}` : ''}`,
      })),
    [info],
  );
  const pk = rows.data?.primary_key ?? 'id';
  const gridRows = (rows.data?.rows ?? []).map((r) => ({ __pk: String(r.cells[pk]), ...r.cells }));
  const runId = row.data?.run_id ?? (table === 'pipeline_runs' ? row.data?.run_id : null);

  return (
    <Box>
      <PageHeader
        title={t('Database')}
        subtitle={t('Raw data of every table (read-only). Click a row to see its full content.')}
        actions={
          meta?.offline_db && (
            <ToggleButtonGroup size="small" exclusive value={db} onChange={(_, v) => v && setParams({ table, db: v })}>
              <ToggleButton value="main">{t('Main database')}</ToggleButton>
              <ToggleButton value="offline">{t('Offline sandbox')}</ToggleButton>
            </ToggleButtonGroup>
          )
        }
      />
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 3, lg: 2.4 }}>
          <Paper variant="outlined">
            <List dense disablePadding sx={{ maxHeight: 'calc(100vh - 180px)', overflow: 'auto' }}>
              {(tables.data ?? []).map((tb) => (
                <ListItemButton key={tb.name} selected={tb.name === table} onClick={() => setParams({ table: tb.name, db })}>
                  <ListItemText
                    primary={TABLE_LABEL[tb.name] ? t(TABLE_LABEL[tb.name]) : tb.name}
                    secondary={tb.name}
                    slotProps={{ secondary: { sx: { fontFamily: 'monospace', fontSize: 11 } } }}
                  />
                  <Chip size="small" label={tb.rows.toLocaleString(locale())} variant="outlined" />
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
                label={`${f.column} ${t(OPS.find((o) => o[0] === f.op)?.[1] ?? f.op)} ${f.value ?? ''}`}
                onDelete={() => setFilters(filters.filter((_, j) => j !== i))}
                color="primary"
                variant="outlined"
              />
            ))}
            <TextField select size="small" label={t('Column')} value={draft.column} onChange={(e) => setDraft({ ...draft, column: e.target.value })} sx={{ minWidth: 150 }}>
              {(info?.columns ?? []).map((c) => (
                <MenuItem key={c.name} value={c.name}>
                  {c.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField select size="small" label={t('Condition')} value={draft.op} onChange={(e) => setDraft({ ...draft, op: e.target.value })} sx={{ width: 100 }}>
              {OPS.map(([v, l]) => (
                <MenuItem key={v} value={v}>
                  {t(l)}
                </MenuItem>
              ))}
            </TextField>
            {!['is_null', 'not_null'].includes(draft.op) && (
              <TextField size="small" label={t('Value')} value={draft.value} onChange={(e) => setDraft({ ...draft, value: e.target.value })} sx={{ width: 200 }} />
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
              {t('Add filter')}
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
                {t('Open run')}
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
