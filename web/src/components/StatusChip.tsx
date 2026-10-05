import { Chip, type ChipProps } from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import AutorenewIcon from '@mui/icons-material/Autorenew';
import BlockIcon from '@mui/icons-material/Block';
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutlined';
import { ACTION_COLOR } from '../lib/labels';

const spin = { animation: 'spin 1.2s linear infinite' };

const STATUS: Record<string, { label: string; color: ChipProps['color']; icon?: React.ReactElement }> = {
  running: { label: '运行中', color: 'info', icon: <AutorenewIcon sx={spin} /> },
  starting: { label: '启动中', color: 'info', icon: <AutorenewIcon sx={spin} /> },
  succeeded: { label: '成功', color: 'success', icon: <CheckCircleIcon /> },
  ok: { label: '完成', color: 'success', icon: <CheckCircleIcon /> },
  failed: { label: '失败', color: 'error', icon: <ErrorIcon /> },
  error: { label: '被拒绝', color: 'error', icon: <ErrorIcon /> },
  failed_skipped: { label: '失败（跳过）', color: 'warning', icon: <RemoveCircleOutlineIcon /> },
  cancelled: { label: '已取消', color: 'default', icon: <BlockIcon /> },
  pending: { label: '等待', color: 'default' },
  skipped: { label: '未执行', color: 'default' },
};

export function StatusChip({ status, size = 'small' }: { status: string; size?: ChipProps['size'] }) {
  const s = STATUS[status] ?? { label: status, color: 'default' as const };
  const outlined = status === 'skipped' || status === 'pending';
  return <Chip size={size} label={s.label} color={s.color} icon={s.icon} variant={outlined ? 'outlined' : 'filled'} />;
}

const MODE: Record<string, ChipProps['color']> = { dry_run: 'default', paper: 'info', live: 'error' };

export function ModeChip({ mode, offline }: { mode: string; offline?: boolean }) {
  return <Chip size="small" variant="outlined" color={MODE[mode] ?? 'default'} label={offline ? `${mode} · 离线` : mode} />;
}

export function ActionChip({ action }: { action: string | null | undefined }) {
  if (!action) return null;
  const strong = action.startsWith('strong');
  return <Chip size="small" label={action} color={ACTION_COLOR[action] ?? 'default'} variant={strong ? 'filled' : 'outlined'} />;
}
