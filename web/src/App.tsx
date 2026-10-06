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
import { ConfigEditPage, ConfigListPage } from './pages/ConfigsPage';
import { Dashboard } from './pages/Dashboard';
import { DataPage } from './pages/DataPage';
import { MarketPage } from './pages/MarketPage';
import { PortfolioPage } from './pages/PortfolioPage';
import { RunDetailPage } from './pages/RunDetailPage';
import { RunsPage } from './pages/RunsPage';
import { SchedulerPage } from './pages/SchedulerPage';
import { WatchlistPage } from './pages/WatchlistPage';

const DRAWER = 232;

const NAV: { section?: string; items: { to: string; label: string; icon: React.ReactNode }[] }[] = [
  {
    items: [
      { to: '/', label: '总览', icon: <DashboardIcon /> },
      { to: '/runs', label: '运行记录', icon: <PlaylistPlayIcon /> },
      { to: '/scheduler', label: '调度器', icon: <ScheduleIcon /> },
    ],
  },
  {
    section: '配置',
    items: [
      { to: '/configs/pipelines', label: '流水线', icon: <AccountTreeIcon /> },
      { to: '/configs/agents', label: 'Agent', icon: <SmartToyIcon /> },
      { to: '/configs/prompts', label: '提示词模板', icon: <DescriptionIcon /> },
      { to: '/configs/risk', label: '风控规则', icon: <ShieldIcon /> },
      { to: '/configs/accounts', label: '账户', icon: <AccountBalanceIcon /> },
      { to: '/configs/llm_providers', label: 'LLM 供应商', icon: <CloudIcon /> },
      { to: '/configs/schedules', label: '调度配置', icon: <EventIcon /> },
    ],
  },
  {
    section: '数据',
    items: [
      { to: '/portfolio', label: '持仓与账户', icon: <PieChartIcon /> },
      { to: '/watchlist', label: '关注列表', icon: <VisibilityIcon /> },
      { to: '/market', label: '行情', icon: <ShowChartIcon /> },
      { to: '/data', label: '数据库', icon: <StorageIcon /> },
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
  const location = useLocation();
  const theme = useMemo(
    () =>
      createTheme({
        palette: { mode, primary: { main: mode === 'dark' ? '#64b5f6' : '#1565c0' }, background: mode === 'dark' ? { default: '#0f1214', paper: '#161a1d' } : { default: '#f6f7f9' } },
        shape: { borderRadius: 8 },
        typography: { fontFamily: '"Inter", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif', fontSize: 13.5 },
        components: {
          MuiCard: { defaultProps: { elevation: 0 } },
          MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { textTransform: 'none' } } },
          MuiTab: { styleOverrides: { root: { textTransform: 'none' } } },
        },
      }),
    [mode],
  );
  const wide = useMediaQuery(theme.breakpoints.up('md'));
  const overview = useQuery({ queryKey: ['overview'], queryFn: api.overview, refetchInterval: 10_000 });
  const kill = overview.data?.kill_switch.active;
  const active = (to: string) => (to === '/' ? location.pathname === '/' : location.pathname.startsWith(to));

  const nav = (
    <Box sx={{ overflow: 'auto' }}>
      {NAV.map((group, i) => (
        <List key={i} dense subheader={group.section ? <ListSubheader sx={{ bgcolor: 'transparent', lineHeight: '32px' }}>{group.section}</ListSubheader> : undefined}>
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
              <ListItemText primary={item.label} />
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
              Quant 控制台
            </Typography>
            {kill && <Chip color="error" icon={<ReportProblemIcon />} label="熔断已开启" sx={{ mr: 1 }} component={RouterLink} to="/" clickable />}
            {overview.data?.scheduler.running && <Chip size="small" color="success" variant="outlined" icon={<ScheduleIcon />} label="调度中" sx={{ mr: 1 }} />}
            <Tooltip title={mode === 'dark' ? '浅色' : '深色'}>
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
        页面出错了
      </Typography>
      <Typography variant="body2" sx={{ fontFamily: 'monospace', mb: 2, whiteSpace: 'pre-wrap' }}>
        {message}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        如果刚更新过代码，可能是网页和后台服务的版本不一致：请重启 quant-web serve 后刷新页面。
      </Typography>
      <Button variant="outlined" onClick={() => window.location.assign('/')}>
        回到总览
      </Button>
    </Box>
  );
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
      { path: '/configs/:kind', element: <ConfigListPage /> },
      { path: '/configs/:kind/:name', element: <ConfigEditPage /> },
      { path: '/portfolio', element: <PortfolioPage /> },
      { path: '/watchlist', element: <WatchlistPage /> },
      { path: '/market', element: <MarketPage /> },
      { path: '/data', element: <DataPage /> },
      { path: '*', element: <Typography>页面不存在</Typography> },
    ],
  },
]);
