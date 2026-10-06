import { Alert, Box, Button, Checkbox, Chip, FormControlLabel, IconButton, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Tooltip, Typography } from '@mui/material';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlineOutlined';
import PushPinIcon from '@mui/icons-material/PushPin';
import PushPinOutlinedIcon from '@mui/icons-material/PushPinOutlined';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { api, type WatchlistEntry } from '../api/client';
import { Empty, PageHeader, Section } from '../components/common';
import { fmtNum, fmtTime } from '../lib/format';

function AddForm({ pipeline }: { pipeline: string }) {
  const qc = useQueryClient();
  const [symbol, setSymbol] = useState('');
  const [note, setNote] = useState('');
  const [pinned, setPinned] = useState(false);
  const add = useMutation({
    mutationFn: () => api.watchlistAdd(pipeline, { symbol: symbol.trim().toUpperCase(), pinned, note: note.trim() || null }),
    onSuccess: () => {
      setSymbol('');
      setNote('');
      setPinned(false);
      qc.invalidateQueries({ queryKey: ['watchlists'] });
    },
  });
  return (
    <Box>
      <Stack direction={{ xs: 'column', sm: 'row' }} sx={{ gap: 1, alignItems: { sm: 'center' } }}>
        <TextField size="small" label="股票代码" value={symbol} onChange={(e) => setSymbol(e.target.value)} sx={{ width: { sm: 130 } }} />
        <TextField size="small" label="备注（可选）" value={note} onChange={(e) => setNote(e.target.value)} sx={{ flex: 1 }} />
        <FormControlLabel control={<Checkbox checked={pinned} onChange={(e) => setPinned(e.target.checked)} />} label="固定（不会过期）" />
        <Button variant="contained" disabled={!symbol.trim() || add.isPending} onClick={() => add.mutate()}>
          加入
        </Button>
      </Stack>
      {add.error && <Alert severity="error" sx={{ mt: 1 }}>{String((add.error as Error).message)}</Alert>}
    </Box>
  );
}

function EntryRow({ pipeline, e }: { pipeline: string; e: WatchlistEntry }) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ['watchlists'] });
  const remove = useMutation({ mutationFn: () => api.watchlistRemove(pipeline, e.symbol), onSuccess: refresh });
  const pin = useMutation({ mutationFn: () => api.watchlistAdd(pipeline, { symbol: e.symbol, pinned: !e.pinned, note: e.note }), onSuccess: refresh });
  return (
    <TableRow sx={{ opacity: e.active ? 1 : 0.5 }}>
      <TableCell sx={{ fontWeight: 600 }}>
        <RouterLink to={`/market?symbol=${e.symbol}`} style={{ color: 'inherit' }}>
          {e.symbol}
        </RouterLink>
        {e.pinned && <Chip size="small" label="固定" sx={{ ml: 1 }} />}
      </TableCell>
      <TableCell>{fmtTime(e.added_at)}</TableCell>
      <TableCell>{e.last_selected_at ? fmtTime(e.last_selected_at) : '手动加入'}</TableCell>
      <TableCell align="right">{e.times_selected}</TableCell>
      <TableCell align="right">{e.last_score === null ? '—' : fmtNum(e.last_score)}</TableCell>
      <TableCell sx={{ maxWidth: 420 }}>
        <Typography variant="body2" sx={{ whiteSpace: 'normal' }}>
          {e.active ? e.last_reason ?? e.note ?? '' : `已移出：${e.removed_reason ?? ''}（${fmtTime(e.removed_at)}）`}
        </Typography>
      </TableCell>
      <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
        {e.active && (
          <>
            <Tooltip title={e.pinned ? '取消固定' : '固定（不会过期）'}>
              <IconButton size="small" onClick={() => pin.mutate()} disabled={pin.isPending}>
                {e.pinned ? <PushPinIcon fontSize="small" /> : <PushPinOutlinedIcon fontSize="small" />}
              </IconButton>
            </Tooltip>
            <Tooltip title="移出关注列表">
              <IconButton size="small" onClick={() => remove.mutate()} disabled={remove.isPending}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </>
        )}
      </TableCell>
    </TableRow>
  );
}

export function WatchlistPage() {
  const lists = useQuery({ queryKey: ['watchlists'], queryFn: api.watchlists, refetchInterval: 30_000 });
  return (
    <Box>
      <PageHeader
        title="关注列表"
        subtitle="选股阶段每天把选出的前几名加入；超过设定天数没再被选中就自动移出（固定的和已持仓的不会）。列表里的股票都会进入行情、舆情、决策和风控。"
      />
      {lists.error && <Alert severity="error">{String((lists.error as Error).message)}</Alert>}
      {(lists.data ?? []).map((p) => {
        const active = p.entries.filter((e) => e.active);
        return (
          <Section
            key={p.pipeline}
            title={
              <Stack direction="row" sx={{ alignItems: 'center', gap: 1 }}>
                <span>{p.pipeline}</span>
                <Chip size="small" label={`${active.length} 只`} />
              </Stack>
            }
          >
            <AddForm pipeline={p.pipeline} />
            {p.entries.length ? (
              <Table size="small" sx={{ mt: 2 }}>
                <TableHead>
                  <TableRow>
                    <TableCell>股票</TableCell>
                    <TableCell>加入时间</TableCell>
                    <TableCell>最近被选中</TableCell>
                    <TableCell align="right">被选次数</TableCell>
                    <TableCell align="right">最近得分</TableCell>
                    <TableCell>理由 / 备注</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {p.entries.map((e) => (
                    <EntryRow key={e.symbol} pipeline={p.pipeline} e={e} />
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Empty>还没有关注的股票</Empty>
            )}
          </Section>
        );
      })}
    </Box>
  );
}
