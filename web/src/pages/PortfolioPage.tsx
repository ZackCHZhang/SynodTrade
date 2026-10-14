import { Alert, Box, Card, CardContent, Chip, Grid, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material';
import { PieChart } from '@mui/x-charts';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@tanstack/react-query';
import { Link as RouterLink } from 'react-router-dom';
import { api } from '../api/client';
import { ActionChip } from '../components/StatusChip';
import { Empty, PageHeader, Section } from '../components/common';
import { fmtNum, fmtPct, fmtTime } from '../lib/format';
import { t } from '../i18n';

const PALETTE = ['#1e88e5', '#43a047', '#fb8c00', '#8e24aa', '#00897b', '#e53935', '#5e35b1', '#6d4c41', '#3949ab', '#c0ca33'];

function PipelineLedger({ p }: { p: any }) {
  if (p.error) return <Alert severity="error">{p.name}: {p.error}</Alert>;
  const slices = [
    ...p.positions.map((x: any, i: number) => ({ id: x.symbol, value: x.market_value ?? x.cost_basis, label: x.symbol, color: PALETTE[i % PALETTE.length] })),
    { id: '__cash', value: Math.max(p.cash, 0), label: t('Cash'), color: '#b0bec5' },
  ].filter((s) => s.value > 0);
  const pnlColor = (v: number | null) => (v === null ? undefined : v >= 0 ? 'success.main' : 'error.main');
  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent>
        <Stack direction="row" sx={{ alignItems: 'center', gap: 1, mb: 1 }}>
          <Typography variant="h6" component={RouterLink} to={`/configs/pipelines/${p.name}`} sx={{ color: 'inherit', textDecoration: 'none' }}>
            {p.name}
          </Typography>
          <Chip size="small" variant="outlined" label={p.mode} />
          <Chip size="small" variant="outlined" label={p.account} />
        </Stack>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, sm: 7 }}>
            <Table size="small">
              <TableBody>
                <TableRow>
                  <TableCell>{t('NAV')}</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 600 }}>
                    {fmtNum(p.nav)} {p.currency}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>{t('vs. capital cap')}</TableCell>
                  <TableCell align="right" sx={{ color: pnlColor(p.return_pct), fontWeight: 600 }}>
                    {fmtPct(p.return_pct)}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>{t('Cash / available')}</TableCell>
                  <TableCell align="right">
                    {fmtNum(p.cash)} / {fmtNum(p.available_cash)}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>{t('Reserved by open orders')}</TableCell>
                  <TableCell align="right">{fmtNum(p.reserved_cash)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>{t('Realized P&L / commissions')}</TableCell>
                  <TableCell align="right">
                    {fmtNum(p.realized_pnl)} / {fmtNum(p.commissions)}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>{t('Capital cap')}</TableCell>
                  <TableCell align="right">{fmtNum(p.max_capital)}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </Grid>
          <Grid size={{ xs: 12, sm: 5 }}>
            {slices.length ? (
              <PieChart height={180} series={[{ data: slices, innerRadius: 40, paddingAngle: 1, cornerRadius: 3 }]} hideLegend />
            ) : (
              <Empty>{t('No positions')}</Empty>
            )}
          </Grid>
        </Grid>
        {p.positions.length > 0 && (
          <Table size="small" sx={{ mt: 1 }}>
            <TableHead>
              <TableRow>
                <TableCell>{t('Symbol')}</TableCell>
                <TableCell align="right">{t('Quantity')}</TableCell>
                <TableCell align="right">{t('Avg cost')}</TableCell>
                <TableCell align="right">{t('Price')}</TableCell>
                <TableCell align="right">{t('Market value')}</TableCell>
                <TableCell align="right">{t('Unrealized P&L')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {p.positions.map((x: any) => (
                <TableRow key={x.symbol}>
                  <TableCell sx={{ fontWeight: 600 }}>
                    <RouterLink to={`/market?symbol=${x.symbol}`} style={{ color: 'inherit' }}>
                      {x.symbol}
                    </RouterLink>
                  </TableCell>
                  <TableCell align="right">{x.qty}</TableCell>
                  <TableCell align="right">{fmtNum(x.avg_cost)}</TableCell>
                  <TableCell align="right">{fmtNum(x.last_price)}</TableCell>
                  <TableCell align="right">{fmtNum(x.market_value)}</TableCell>
                  <TableCell align="right" sx={{ color: pnlColor(x.unrealized_pnl) }}>
                    {fmtNum(x.unrealized_pnl)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

export function PortfolioPage() {
  const portfolio = useQuery({ queryKey: ['portfolio'], queryFn: api.portfolio, refetchInterval: 15_000 });
  const d = portfolio.data;
  const orderCols: GridColDef[] = [
    { field: 'created_at', headerName: t('Time'), width: 160, valueFormatter: (v) => fmtTime(v as string, true) },
    { field: 'pipeline_name', headerName: t('Pipeline'), width: 150 },
    { field: 'symbol', headerName: t('Symbol'), width: 80 },
    { field: 'action', headerName: t('Action'), width: 120, renderCell: (p) => <ActionChip action={p.value} /> },
    { field: 'side', headerName: t('Side'), width: 70 },
    { field: 'quantity', headerName: t('Quantity'), width: 80, type: 'number' },
    { field: 'limit_price', headerName: t('Limit'), width: 90, type: 'number' },
    { field: 'status', headerName: t('Status'), width: 130, renderCell: (p) => <Chip size="small" label={p.value} color={p.value === 'filled' ? 'success' : p.value === 'rejected' ? 'error' : 'default'} /> },
    { field: 'filled_qty', headerName: t('Filled'), width: 80, type: 'number' },
    { field: 'avg_fill_price', headerName: t('Avg fill price'), width: 100, type: 'number' },
    { field: 'message', headerName: t('Message'), flex: 1, minWidth: 200 },
    { field: 'run_id', headerName: t('Run'), width: 100, renderCell: (p) => <RouterLink to={`/runs/${p.value}`}>{String(p.value).slice(0, 8)}</RouterLink> },
  ];
  return (
    <Box>
      <PageHeader
        title={t('Portfolio & account')}
        subtitle={
          <>
            {t("Each pipeline's virtual sub-ledger is derived from its own fills; order fills and IBKR account snapshots are updated by")}{' '}
            <RouterLink to="/account-sync">{t('Account sync')}</RouterLink> {t('(before runs + on a timer) and the data_update stage')}
          </>
        }
      />
      <Grid container spacing={2} sx={{ mb: 2 }}>
        {(d?.pipelines ?? []).map((p) => (
          <Grid key={p.name} size={{ xs: 12, lg: 6, xl: 4 }}>
            <PipelineLedger p={p} />
          </Grid>
        ))}
      </Grid>
      <Section title={t('IBKR account snapshots')}>
        {(d?.accounts ?? []).map((a) =>
          a.error ? (
            <Alert key={a.name} severity="warning" sx={{ mb: 1 }}>
              {a.name}: {a.error}
            </Alert>
          ) : (
            <Box key={a.name} sx={{ mb: 2 }}>
              <Typography variant="subtitle2">
                {a.name} · {a.account_id}
                {a.snapshot && (
                  <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                    {fmtTime(a.snapshot.ts, true)}
                  </Typography>
                )}
              </Typography>
              {a.snapshot ? (
                <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap', my: 1 }}>
                  <Chip label={`${t('NAV')} ${fmtNum(a.snapshot.nav)} ${a.snapshot.currency}`} />
                  <Chip label={`${t('Cash')} ${fmtNum(a.snapshot.cash)}`} />
                  <Chip label={`${t('Buying power')} ${fmtNum(a.snapshot.buying_power)}`} />
                  {a.snapshot.available_funds !== null && <Chip label={`${t('Available funds')} ${fmtNum(a.snapshot.available_funds)}`} />}
                  {a.positions.map((x: any) => (
                    <Chip key={x.symbol} variant="outlined" label={`${x.symbol} ${x.qty} @ ${fmtNum(x.avg_cost)}`} />
                  ))}
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {t('No snapshot')}
                </Typography>
              )}
            </Box>
          ),
        )}
      </Section>
      <Section title={t('Recent orders')}>
        <Box sx={{ height: 420 }}>
          <DataGrid rows={d?.orders ?? []} columns={orderCols} density="compact" loading={portfolio.isLoading} disableRowSelectionOnClick />
        </Box>
      </Section>
    </Box>
  );
}
