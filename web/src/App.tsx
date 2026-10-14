import {
  AppBar,
  Box,
  Button,
  Chip,
  CssBaseline,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  ListSubheader,
  Menu,
  MenuItem,
  ThemeProvider,
  Toolbar,
  Tooltip,
  Typography,
  createTheme,
  useMediaQuery,
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import DashboardIcon from '@mui/icons-material/Dashboard';
import PlaylistPlayIcon from '@mui/icons-material/PlaylistPlay';
import ScheduleIcon from '@mui/icons-material/Schedule';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import DescriptionIcon from '@mui/icons-material/Description';
import ShieldIcon from '@mui/icons-material/Shield';
import AccountBalanceIcon from '@mui/icons-material/AccountBalance';
import CloudIcon from '@mui/icons-material/Cloud';
import EventIcon from '@mui/icons-material/Event';
import PieChartIcon from '@mui/icons-material/PieChart';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import StorageIcon from '@mui/icons-material/Storage';
import VisibilityIcon from '@mui/icons-material/Visibility';
import DarkModeIcon from '@mui/icons-material/DarkMode';
import LightModeIcon from '@mui/icons-material/LightMode';
import ReportProblemIcon from '@mui/icons-material/ReportProblem';
import SyncIcon from '@mui/icons-material/Sync';
import TranslateIcon from '@mui/icons-material/Translate';
import GitHubIcon from '@mui/icons-material/GitHub';
import { enUS as coreEnUS, zhCN as coreZhCN } from '@mui/material/locale';
import { enUS as gridEnUS, zhCN as gridZhCN } from '@mui/x-data-grid/locales';
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import {
  Outlet,
  Link as RouterLink,
  createBrowserRouter,
  isRouteErrorResponse,
  useLocation,
  useRouteError,
} from 'react-router-dom';
import { api } from './api/client';
import { fmtTime } from './lib/format';
import { AccountSyncPage } from './pages/AccountSyncPage';
import { ConfigEditPage, ConfigListPage } from './pages/ConfigsPage';
import { Dashboard } from './pages/Dashboard';
import { DataPage } from './pages/DataPage';
import { MarketPage } from './pages/MarketPage';
import { PortfolioPage } from './pages/PortfolioPage';
import { RunDetailPage } from './pages/RunDetailPage';
import { RunsPage } from './pages/RunsPage';
import { SchedulerPage } from './pages/SchedulerPage';
import { WatchlistPage } from './pages/WatchlistPage';
import { LANGS, locale, t, useLang } from './i18n';

const DRAWER = 232;
// AGPL-3.0 section 13: users interacting with the console over a network can get its source here.
// If you run a modified version for others, point this at your modified source.
const SOURCE_URL = 'https://github.com/ZackCHZhang/ROOT';

const NAV: { section?: string; items: { to: string; label: string; icon: React.ReactNode }[] }[] = [
  {
    items: [
      { to: '/', label: 'Overview', icon: <DashboardIcon /> },
      { to: '/runs', label: 'Runs', icon: <PlaylistPlayIcon /> },
      { to: '/scheduler', label: 'Scheduler', icon: <ScheduleIcon /> },
      { to: '/account-sync', label: 'Account sync', icon: <SyncIcon /> },
    ],
  },
  {
    section: 'Configuration',
    items: [
      { to: '/configs/pipelines', label: 'Pipelines', icon: <AccountTreeIcon /> },
      { to: '/configs/agents', label: 'Agents', icon: <SmartToyIcon /> },
      { to: '/configs/prompts', label: 'Prompt templates', icon: <DescriptionIcon /> },
      { to: '/configs/risk', label: 'Risk rules', icon: <ShieldIcon /> },
      { to: '/configs/accounts', label: 'Accounts', icon: <AccountBalanceIcon /> },
      { to: '/configs/llm_providers', label: 'LLM providers', icon: <CloudIcon /> },
      { to: '/configs/schedules', label: 'Schedules', icon: <EventIcon /> },
      { to: '/configs/account_sync', label: 'Sync settings', icon: <SyncIcon /> },
    ],
  },
  {
    section: 'Data',
    items: [
      { to: '/portfolio', label: 'Portfolio & account', icon: <PieChartIcon /> },
      { to: '/watchlist', label: 'Watchlist', icon: <VisibilityIcon /> },
      { to: '/market', label: 'Market', icon: <ShowChartIcon /> },
      { to: '/data', label: 'Database', icon: <StorageIcon /> },
    ],
  },
];

function readMode(): 'light' | 'dark' {
  try {
    const v = localStorage.getItem('quant-theme');
    if (v === 'light' || v === 'dark') return v;
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function Layout() {
  const [mode, setMode] = useState<'light' | 'dark'>(readMode);
  const [open, setOpen] = useState(false);
  const { lang, setLang } = useLang();
  const [langAnchor, setLangAnchor] = useState<HTMLElement | null>(null);
  const location = useLocation();
  const theme = useMemo(
    () =>
      createTheme(
        {
        palette: { mode, primary: { main: mode === 'dark' ? '#64b5f6' : '#1565c0' }, background: mode === 'dark' ? { default: '#0f1214', paper: '#161a1d' } : { default: '#f6f7f9' } },
        shape: { borderRadius: 8 },
        typography: { fontFamily: '"Inter", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif', fontSize: 13.5 },
        components: {
          MuiCard: { defaultProps: { elevation: 0 } },
          MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { textTransform: 'none' } } },
          MuiTab: { styleOverrides: { root: { textTransform: 'none' } } },
        },
        },
        lang === 'zh' ? coreZhCN : coreEnUS,
        lang === 'zh' ? gridZhCN : gridEnUS,
      ),
    [mode, lang],
  );
  const wide = useMediaQuery(theme.breakpoints.up('md'));
  const overview = useQuery({ queryKey: ['overview'], queryFn: api.overview, refetchInterval: 10_000 });
  const kill = overview.data?.kill_switch.active;
  const lastSync = overview.data?.account_sync?.latest.reduce<{ status: string; finished_at: string } | null>(
    (worst, s) => (!worst || s.status !== 'ok' ? s : worst),
    null,
  );
  const syncChip = lastSync && (
    <Tooltip title={`${t('Account sync')}: ${t(lastSync.status === 'ok' ? 'Succeeded' : lastSync.status === 'partial' ? 'Partially succeeded' : 'Failed')} · ${fmtTime(lastSync.finished_at, true)}`}>
      <Chip
        size="small"
        variant="outlined"
        color={lastSync.status === 'ok' ? 'success' : lastSync.status === 'partial' ? 'warning' : 'error'}
        icon={<SyncIcon />}
        label={`${t('Synced')} ${new Date(lastSync.finished_at).toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit', hour12: false })}`}
        component={RouterLink}
        to="/account-sync"
        clickable
        sx={{ mr: 1, display: { xs: 'none', sm: 'inline-flex' } }}
      />
    </Tooltip>
  );
  const active = (to: string) => (to === '/' ? location.pathname === '/' : location.pathname.startsWith(to));

  const nav = (
    <Box sx={{ overflow: 'auto' }}>
      {NAV.map((group, i) => (
        <List key={i} dense subheader={group.section ? <ListSubheader sx={{ bgcolor: 'transparent', lineHeight: '32px' }}>{t(group.section)}</ListSubheader> : undefined}>
          {group.items.map((item) => (
            <ListItemButton
              key={item.to}
              component={RouterLink}
              to={item.to}
              selected={active(item.to)}
              onClick={() => setOpen(false)}
              sx={{ mx: 1, borderRadius: 1.5 }}
            >
              <ListItemIcon sx={{ minWidth: 36 }}>{item.icon}</ListItemIcon>
              <ListItemText primary={t(item.label)} />
            </ListItemButton>
          ))}
          {i < NAV.length - 1 && <Divider sx={{ mt: 1 }} />}
        </List>
      ))}
    </Box>
  );

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <style>{'@keyframes spin { from { transform: rotate(0deg) } to { transform: rotate(360deg) } }'}</style>
      <Box sx={{ display: 'flex' }}>
        <AppBar position="fixed" color="inherit" elevation={0} sx={{ zIndex: (t) => t.zIndex.drawer + 1, borderBottom: 1, borderColor: 'divider' }}>
          <Toolbar variant="dense">
            {!wide && (
              <IconButton edge="start" onClick={() => setOpen(!open)} sx={{ mr: 1 }}>
                <MenuIcon />
              </IconButton>
            )}
            <ShowChartIcon color="primary" sx={{ mr: 1 }} />
            <Typography variant="h6" sx={{ fontWeight: 700, flex: 1, fontSize: 17 }} noWrap>
              {t('Quant Console')}
            </Typography>
            {kill && <Chip color="error" icon={<ReportProblemIcon />} label={t('Kill switch on')} sx={{ mr: 1 }} component={RouterLink} to="/" clickable />}
            {overview.data?.scheduler.running && <Chip size="small" color="success" variant="outlined" icon={<ScheduleIcon />} label={t('Scheduling')} sx={{ mr: 1 }} />}
            {syncChip}
            <Tooltip title={t('Source code (AGPL-3.0)')}>
              <IconButton component="a" href={SOURCE_URL} target="_blank" rel="noopener noreferrer">
                <GitHubIcon />
              </IconButton>
            </Tooltip>
            <Tooltip title={t('Language')}>
              <IconButton onClick={(e) => setLangAnchor(e.currentTarget)}>
                <TranslateIcon />
              </IconButton>
            </Tooltip>
            <Menu anchorEl={langAnchor} open={!!langAnchor} onClose={() => setLangAnchor(null)}>
              {LANGS.map((l) => (
                <MenuItem
                  key={l.code}
                  selected={l.code === lang}
                  onClick={() => {
                    setLangAnchor(null);
                    setLang(l.code);
                  }}
                >
                  {l.label}
                </MenuItem>
              ))}
            </Menu>
            <Tooltip title={t(mode === 'dark' ? 'Light' : 'Dark')}>
              <IconButton
                onClick={() => {
                  const next = mode === 'dark' ? 'light' : 'dark';
                  setMode(next);
                  try {
                    localStorage.setItem('quant-theme', next);
                  } catch {
                    /* ignore */
                  }
                }}
              >
                {mode === 'dark' ? <LightModeIcon /> : <DarkModeIcon />}
              </IconButton>
            </Tooltip>
          </Toolbar>
        </AppBar>
        <Drawer
          variant={wide ? 'permanent' : 'temporary'}
          open={wide || open}
          onClose={() => setOpen(false)}
          sx={{ width: DRAWER, flexShrink: 0, '& .MuiDrawer-paper': { width: DRAWER, boxSizing: 'border-box' } }}
        >
          <Toolbar variant="dense" />
          {nav}
        </Drawer>
        <Box component="main" sx={{ flexGrow: 1, minWidth: 0, p: { xs: 2, md: 3 } }}>
          <Toolbar variant="dense" />
          <Outlet />
        </Box>
      </Box>
    </ThemeProvider>
  );
}

/** Shown instead of a blank page when a page throws: the error, and a way back. */
function RouteError() {
  const error = useRouteError();
  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : String(error);
  return (
    <Box sx={{ p: 3, maxWidth: 720 }}>
      <Typography variant="h6" gutterBottom>
        {t('Something went wrong on this page')}
      </Typography>
      <Typography variant="body2" sx={{ fontFamily: 'monospace', mb: 2, whiteSpace: 'pre-wrap' }}>
        {message}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t('If the code was just updated, the page and the backend may be out of sync: restart quant-web serve and reload the page.')}
      </Typography>
      <Button variant="outlined" onClick={() => window.location.assign('/')}>
        {t('Back to overview')}
      </Button>
    </Box>
  );
}

function NotFound() {
  return <Typography>{t('Page not found')}</Typography>;
}

export const router = createBrowserRouter([
  {
    element: <Layout />,
    errorElement: <RouteError />,
    children: [
      { path: '/', element: <Dashboard /> },
      { path: '/runs', element: <RunsPage /> },
      { path: '/runs/:runId', element: <RunDetailPage /> },
      { path: '/scheduler', element: <SchedulerPage /> },
      { path: '/account-sync', element: <AccountSyncPage /> },
      { path: '/configs/:kind', element: <ConfigListPage /> },
      { path: '/configs/:kind/:name', element: <ConfigEditPage /> },
      { path: '/portfolio', element: <PortfolioPage /> },
      { path: '/watchlist', element: <WatchlistPage /> },
      { path: '/market', element: <MarketPage /> },
      { path: '/data', element: <DataPage /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);
