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
import { t } from '../i18n';

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
        <TextField size="small" label={t('Symbol')} value={symbol} onChange={(e) => setSymbol(e.target.value)} sx={{ width: { sm: 130 } }} />
        <TextField size="small" label={t('Note (optional)')} value={note} onChange={(e) => setNote(e.target.value)} sx={{ flex: 1 }} />
        <FormControlLabel control={<Checkbox checked={pinned} onChange={(e) => setPinned(e.target.checked)} />} label={t('Pinned (never expires)')} />
        <Button variant="contained" disabled={!symbol.trim() || add.isPending} onClick={() => add.mutate()}>
          {t('Add')}
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
        {e.pinned && <Chip size="small" label={t('Pinned')} sx={{ ml: 1 }} />}
      </TableCell>
      <TableCell>{fmtTime(e.added_at)}</TableCell>
      <TableCell>{e.last_selected_at ? fmtTime(e.last_selected_at) : t('Added manually')}</TableCell>
      <TableCell align="right">{e.times_selected}</TableCell>
      <TableCell align="right">{e.last_score === null ? '—' : fmtNum(e.last_score)}</TableCell>
      <TableCell sx={{ maxWidth: 420 }}>
        <Typography variant="body2" sx={{ whiteSpace: 'normal' }}>
          {e.active ? e.last_reason ?? e.note ?? '' : t('Removed: {reason} ({time})', { reason: e.removed_reason ?? '', time: fmtTime(e.removed_at) })}
        </Typography>
      </TableCell>
      <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
        {e.active && (
          <>
            <Tooltip title={e.pinned ? t('Unpin') : t('Pinned (never expires)')}>
              <IconButton size="small" onClick={() => pin.mutate()} disabled={pin.isPending}>
                {e.pinned ? <PushPinIcon fontSize="small" /> : <PushPinOutlinedIcon fontSize="small" />}
              </IconButton>
            </Tooltip>
            <Tooltip title={t('Remove from watchlist')}>
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
        title={t('Watchlist')}
        subtitle={t('The selection stage adds its top picks every day; symbols not picked again within the configured days are removed automatically (pinned and held ones stay). Every symbol here goes through market data, sentiment, decision and risk.')}
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
                <Chip size="small" label={t('{n|symbol|symbols}', { n: active.length })} />
              </Stack>
            }
          >
            <AddForm pipeline={p.pipeline} />
            {p.entries.length ? (
              <Table size="small" sx={{ mt: 2 }}>
                <TableHead>
                  <TableRow>
                    <TableCell>{t('Symbol')}</TableCell>
                    <TableCell>{t('Added')}</TableCell>
                    <TableCell>{t('Last picked')}</TableCell>
                    <TableCell align="right">{t('Times picked')}</TableCell>
                    <TableCell align="right">{t('Last score')}</TableCell>
                    <TableCell>{t('Reason / note')}</TableCell>
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
              <Empty>{t('No symbols on the watchlist yet')}</Empty>
            )}
          </Section>
        );
      })}
    </Box>
  );
}
