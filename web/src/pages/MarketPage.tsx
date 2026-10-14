import {
  Autocomplete,
  Box,
  Card,
  CardContent,
  Grid,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { BarChart, LineChart } from '@mui/x-charts';
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { ActionChip } from '../components/StatusChip';
import { Empty, PageHeader, Section, StatCard } from '../components/common';
import { fmtCompact, fmtNum, fmtPct, fmtTime, sma } from '../lib/format';
import { t } from '../i18n';

export function MarketPage() {
  const [params, setParams] = useSearchParams();
  const instruments = useQuery({ queryKey: ['instruments'], queryFn: api.instruments });
  const symbols = (instruments.data ?? []).filter((i) => Object.keys(i.timeframes).length).map((i) => i.symbol);
  const symbol = params.get('symbol') ?? symbols[0] ?? '';
  const inst = instruments.data?.find((i) => i.symbol === symbol);
  const timeframes = Object.keys(inst?.timeframes ?? {});
  const timeframe = params.get('tf') ?? (timeframes.includes('1d') ? '1d' : timeframes[0] ?? '1d');
  const limit = Number(params.get('n') ?? 260);
  const set = (patch: Record<string, string>) => setParams({ symbol, tf: timeframe, n: String(limit), ...patch });

  const bars = useQuery({ queryKey: ['bars', symbol, timeframe, limit], queryFn: () => api.bars(symbol, timeframe, limit), enabled: !!symbol });
  const decisions = useQuery({
    queryKey: ['rows', 'aggregated_decisions', symbol],
    queryFn: () => api.rows('aggregated_decisions', { offset: 0, limit: 20, sort: 'created_at', desc: true, filters: [{ column: 'symbol', op: 'eq', value: symbol }] }),
    enabled: !!symbol,
  });

  const data = bars.data?.bars ?? [];
  const chart = useMemo(() => {
    const closes = data.map((b) => b.close);
    return {
      x: data.map((b) => new Date(b.ts)),
      close: closes,
      sma20: sma(closes, 20),
      sma50: sma(closes, 50),
      sma200: sma(closes, 200),
      volume: data.map((b) => b.volume),
    };
  }, [data]);
  const last = data[data.length - 1];
  const prev = data[data.length - 2];
  const back20 = data[data.length - 21];
  const high = data.length ? Math.max(...data.slice(-252).map((b) => b.high)) : null;
  const low = data.length ? Math.min(...data.slice(-252).map((b) => b.low)) : null;

  return (
    <Box>
      <PageHeader
        title={t('Market')}
        subtitle={t('Bars and quote snapshots in the database (written by the data_update / selection stages)')}
        actions={
          <>
            <Autocomplete
              size="small"
              options={symbols}
              value={symbol || null}
              onChange={(_, v) => v && set({ symbol: v })}
              renderInput={(p) => <TextField {...p} label={t('Symbol')} />}
              sx={{ width: 160 }}
            />
            <TextField select size="small" label={t('Timeframe')} value={timeframe} onChange={(e) => set({ tf: e.target.value })} sx={{ width: 90 }}>
              {(timeframes.length ? timeframes : ['1d']).map((tf) => (
                <MenuItem key={tf} value={tf}>
                  {tf}
                </MenuItem>
              ))}
            </TextField>
            <TextField select size="small" label={t('Bar count')} value={limit} onChange={(e) => set({ n: e.target.value })} sx={{ width: 100 }}>
              {[60, 120, 260, 500, 1000].map((n) => (
                <MenuItem key={n} value={n}>
                  {n}
                </MenuItem>
              ))}
            </TextField>
          </>
        }
      />
      {!symbols.length && !instruments.isLoading ? (
        <Empty>{t('No bars in the database yet. Run a pipeline with a data_update stage once.')}</Empty>
      ) : (
        <>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid size={{ xs: 6, md: 3 }}>
              <StatCard label={t('Last close')} value={fmtNum(last?.close)} hint={last ? fmtTime(last.ts) : undefined} />
            </Grid>
            <Grid size={{ xs: 6, md: 3 }}>
              <StatCard
                label={t('Bar change')}
                value={last && prev ? fmtPct(last.close / prev.close - 1) : '—'}
                color={last && prev ? (last.close >= prev.close ? '#2e7d32' : '#c62828') : undefined}
              />
            </Grid>
            <Grid size={{ xs: 6, md: 3 }}>
              <StatCard label={t('20-bar return')} value={last && back20 ? fmtPct(last.close / back20.close - 1) : '—'} />
            </Grid>
            <Grid size={{ xs: 6, md: 3 }}>
              <StatCard label={t('High / low (252 bars)')} value={`${fmtNum(high)} / ${fmtNum(low)}`} hint={inst?.timeframes[timeframe] ? t('{n|bar|bars} total', { n: inst.timeframes[timeframe].bars }) : undefined} />
            </Grid>
          </Grid>
          <Card variant="outlined" sx={{ mb: 2 }}>
            <CardContent>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                {t('{symbol} close and moving averages', { symbol })}
              </Typography>
              {data.length ? (
                <>
                  <LineChart
                    height={360}
                    xAxis={[{ data: chart.x, scaleType: 'time', valueFormatter: (d: Date) => d.toLocaleDateString('zh-CN') }]}
                    yAxis={[{ width: 64 }]}
                    series={[
                      { data: chart.close, label: t('Close price'), showMark: false, color: '#1e88e5' },
                      { data: chart.sma20, label: 'SMA 20', showMark: false, color: '#fb8c00', connectNulls: false },
                      { data: chart.sma50, label: 'SMA 50', showMark: false, color: '#43a047' },
                      { data: chart.sma200, label: 'SMA 200', showMark: false, color: '#8e24aa' },
                    ]}
                    grid={{ horizontal: true }}
                  />
                  <BarChart
                    height={140}
                    xAxis={[{ data: chart.x.map((d) => d.toLocaleDateString('zh-CN')), scaleType: 'band', tickLabelInterval: (_v: any, i: number) => i % Math.ceil(data.length / 8) === 0 }]}
                    yAxis={[{ width: 64, valueFormatter: (v: number) => fmtCompact(v) }]}
                    series={[{ data: chart.volume, label: t('Volume'), color: '#90a4ae' }]}
                    hideLegend
                  />
                </>
              ) : (
                <Empty>{bars.isLoading ? t('Loading…') : t('No data')}</Empty>
              )}
            </CardContent>
          </Card>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, md: 6 }}>
              <Section title={t('Recent final decisions')}>
                {decisions.data?.rows.length ? (
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>{t('Time')}</TableCell>
                        <TableCell>{t('Action')}</TableCell>
                        <TableCell>{t('Method')}</TableCell>
                        <TableCell>{t('Run')}</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {decisions.data.rows.map((r) => (
                        <TableRow key={r.cells.id}>
                          <TableCell>{fmtTime(r.cells.created_at)}</TableCell>
                          <TableCell>
                            <ActionChip action={r.cells.final_action} />
                          </TableCell>
                          <TableCell>{r.cells.method}</TableCell>
                          <TableCell>
                            <RouterLink to={`/runs/${r.cells.run_id}`}>{String(r.cells.run_id).slice(0, 8)}</RouterLink>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <Empty>{t('No decisions')}</Empty>
                )}
              </Section>
            </Grid>
            <Grid size={{ xs: 12, md: 6 }}>
              <Section title={t('Recent quote snapshots')}>
                {bars.data?.quotes.length ? (
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>{t('Time')}</TableCell>
                        <TableCell>{t('Bid')}</TableCell>
                        <TableCell>{t('Ask')}</TableCell>
                        <TableCell>{t('Last')}</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {bars.data.quotes.map((q, i) => (
                        <TableRow key={i}>
                          <TableCell>{fmtTime(q.ts, true)}</TableCell>
                          <TableCell>{fmtNum(q.bid)}</TableCell>
                          <TableCell>{fmtNum(q.ask)}</TableCell>
                          <TableCell>{fmtNum(q.last)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <Empty>{t('No quote snapshots')}</Empty>
                )}
              </Section>
            </Grid>
          </Grid>
          <Stack sx={{ mt: 1 }}>
            <Typography variant="caption" color="text.secondary">
              {t('Moving averages are computed in the browser from the bars shown; they are hidden when there are too few bars.')}
            </Typography>
          </Stack>
        </>
      )}
    </Box>
  );
}
