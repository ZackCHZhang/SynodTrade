import { Alert, Box, Button, Card, CardContent, Chip, LinearProgress, MenuItem, Stack, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import { DataGrid, type GridColDef, type GridPaginationModel } from '@mui/x-data-grid';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { api, type Job, type RunLight } from '../api/client';
import { useConfigNames, useMeta } from '../api/hooks';
import { RunDialog } from '../components/RunDialog';
import { ModeChip, StatusChip } from '../components/StatusChip';
import { PageHeader } from '../components/common';
import { fmtDuration, fmtTime, shortId } from '../lib/format';
import { STAGE_INFO, stageLabel } from '../lib/labels';

export function StageDots({ run }: { run: RunLight }) {
  const stages = run.stages_run ?? [];
  const timings = run.summary?.stages ?? {};
  return (
    <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center', height: '100%' }}>
      {stages.map((s) => {
        const st = timings[s]?.status ?? (run.status === 'running' ? 'pending' : 'skipped');
        const color = st === 'ok' ? STAGE_INFO[s]?.color ?? '#43a047' : st === 'failed' ? '#e53935' : st === 'failed_skipped' ? '#fb8c00' : 'transparent';
        return (
          <Box
            key={s}
            title={`${stageLabel(s)}: ${st}`}
            sx={{ width: 14, height: 14, borderRadius: '50%', bgcolor: color, border: '2px solid', borderColor: STAGE_INFO[s]?.color ?? 'grey.500' }}
          />
        );
      })}
    </Stack>
  );
}

export function ActiveJobs({ jobs }: { jobs: Job[] }) {
  const qc = useQueryClient();
  const cancel = useMutation({ mutationFn: api.cancelJob, onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }) });
  const active = jobs.filter((j) => j.status === 'starting' || j.status === 'running');
  if (!active.length) return null;
  return (
    <Stack spacing={1} sx={{ mb: 2 }}>
      {active.map((j) => (
        <Card key={j.id} variant="outlined" sx={{ borderColor: 'info.main' }}>
          <LinearProgress />
          <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
            <Stack direction="row" spacing={2} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
              <StatusChip status={j.status} />
              <Typography sx={{ fontWeight: 600 }}>{j.pipeline}</Typography>
              <ModeChip mode={j.request.offline ? 'dry_run' : j.request.mode} offline={j.request.offline} />
              <Typography variant="body2" color="text.secondary">
                已运行 {fmtDuration(j.created_at, null)}
              </Typography>
              <Box sx={{ flex: 1 }} />
              {j.run_id && (
                <Button size="small" component={RouterLink} to={`/runs/${j.run_id}`}>
                  查看进度
                </Button>
              )}
              <Button size="small" color="error" startIcon={<StopIcon />} onClick={() => cancel.mutate(j.id)}>
                取消
              </Button>
            </Stack>
          </CardContent>
        </Card>
      ))}
    </Stack>
  );
}

export function RunsPage() {
  const navigate = useNavigate();
  const pipelines = useConfigNames('pipelines');
  const [pipeline, setPipeline] = useState('');
  const [status, setStatus] = useState('');
  const [page, setPage] = useState<GridPaginationModel>({ page: 0, pageSize: 25 });
  const [running, setRunning] = useState(false);
  const [db, setDb] = useState<'main' | 'offline'>('main');
  const { data: meta } = useMeta();
  const runs = useQuery({
    queryKey: ['runs', pipeline, status, page, db],
    queryFn: () => api.runs({ pipeline, status, offset: page.page * page.pageSize, limit: page.pageSize, db }),
    refetchInterval: 4000,
    placeholderData: (prev) => prev,
  });
  const jobs = useQuery({ queryKey: ['jobs'], queryFn: api.jobs, refetchInterval: 2000 });
  const rejected = (jobs.data ?? []).filter((j) => j.status === 'error').slice(0, 3);

  const columns: GridColDef<RunLight>[] = [
    { field: 'status', headerName: '状态', width: 120, renderCell: (p) => <StatusChip status={p.row.live ? 'running' : p.value} /> },
    { field: 'pipeline_name', headerName: '流水线', width: 170 },
    { field: 'mode', headerName: '模式', width: 130, renderCell: (p) => <ModeChip mode={p.value} offline={p.row.offline} /> },
    { field: 'stages', headerName: '阶段', width: 150, sortable: false, renderCell: (p) => <StageDots run={p.row} /> },
    { field: 'started_at', headerName: '开始', width: 165, valueFormatter: (v) => fmtTime(v as string, true) },
    { field: 'duration', headerName: '耗时', width: 100, sortable: false, valueGetter: (_v, r) => fmtDuration(r.started_at, r.ended_at) },
    {
      field: 'orders',
      headerName: '决策 / 订单',
      flex: 1,
      minWidth: 220,
      sortable: false,
      renderCell: (p) => {
        const s = p.row.summary;
        if (!s) return null;
        const orders = Object.entries(s.orders ?? {});
        return (
          <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center', height: '100%', overflow: 'hidden' }}>
            {orders.length ? (
              orders.map(([sym, st]) => <Chip key={sym} size="small" label={`${sym} ${st}`} variant="outlined" />)
            ) : (
              <Typography variant="body2" color="text.secondary">
                {Object.keys(s.final_decisions ?? {}).length} 个决策，无订单
              </Typography>
            )}
          </Stack>
        );
      },
    },
    { field: 'error', headerName: '错误', flex: 1, minWidth: 160 },
    { field: 'run_id', headerName: 'Run', width: 100, valueFormatter: (v) => shortId(v as string) },
  ];

  return (
    <Box>
      <PageHeader
        title="运行记录"
        subtitle="数据库中所有流水线运行（含 CLI 和调度器启动的）；本服务内启动的运行可以实时查看日志"
        actions={
          <Button variant="contained" startIcon={<PlayArrowIcon />} onClick={() => setRunning(true)}>
            运行流水线
          </Button>
        }
      />
      <ActiveJobs jobs={jobs.data ?? []} />
      {rejected.map((j) => (
        <Alert key={j.id} severity="error" sx={{ mb: 1 }}>
          {fmtTime(j.created_at, true)} {j.pipeline}：{j.error}
        </Alert>
      ))}
      <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
        <TextField select size="small" label="流水线" value={pipeline} onChange={(e) => setPipeline(e.target.value)} sx={{ minWidth: 200 }}>
          <MenuItem value="">全部</MenuItem>
          {pipelines.map((p) => (
            <MenuItem key={p} value={p}>
              {p}
            </MenuItem>
          ))}
        </TextField>
        <TextField select size="small" label="状态" value={status} onChange={(e) => setStatus(e.target.value)} sx={{ minWidth: 140 }}>
          <MenuItem value="">全部</MenuItem>
          <MenuItem value="running">运行中</MenuItem>
          <MenuItem value="succeeded">成功</MenuItem>
          <MenuItem value="failed">失败</MenuItem>
        </TextField>
        {meta?.offline_db && (
          <ToggleButtonGroup
            size="small"
            exclusive
            value={db}
            onChange={(_, v) => {
              if (v) {
                setDb(v);
                setPage({ ...page, page: 0 });
              }
            }}
          >
            <ToggleButton value="main">正式数据库</ToggleButton>
            <ToggleButton value="offline">离线沙盒</ToggleButton>
          </ToggleButtonGroup>
        )}
      </Stack>
      <Box sx={{ height: 'calc(100vh - 280px)', minHeight: 400 }}>
        <DataGrid
          rows={runs.data?.runs ?? []}
          getRowId={(r) => r.run_id}
          columns={columns}
          rowCount={runs.data?.total ?? 0}
          paginationMode="server"
          paginationModel={page}
          onPaginationModelChange={setPage}
          pageSizeOptions={[25, 50, 100]}
          loading={runs.isLoading}
          density="compact"
          disableRowSelectionOnClick
          onRowClick={(p) => navigate(`/runs/${p.id}`)}
          sx={{ '& .MuiDataGrid-row': { cursor: 'pointer' } }}
        />
      </Box>
      <RunDialog open={running} onClose={() => setRunning(false)} />
    </Box>
  );
}
