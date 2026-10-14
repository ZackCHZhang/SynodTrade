import { Chip, type ChipProps } from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import AutorenewIcon from '@mui/icons-material/Autorenew';
import BlockIcon from '@mui/icons-material/Block';
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutlined';
import { ACTION_COLOR } from '../lib/labels';
import { t } from '../i18n';

const spin = { animation: 'spin 1.2s linear infinite' };

const STATUS: Record<string, { label: string; color: ChipProps['color']; icon?: React.ReactElement }> = {
  running: { label: 'Running', color: 'info', icon: <AutorenewIcon sx={spin} /> },
  starting: { label: 'Starting', color: 'info', icon: <AutorenewIcon sx={spin} /> },
  succeeded: { label: 'Succeeded', color: 'success', icon: <CheckCircleIcon /> },
  ok: { label: 'Done', color: 'success', icon: <CheckCircleIcon /> },
  failed: { label: 'Failed', color: 'error', icon: <ErrorIcon /> },
  error: { label: 'Rejected', color: 'error', icon: <ErrorIcon /> },
  failed_skipped: { label: 'Failed (skipped)', color: 'warning', icon: <RemoveCircleOutlineIcon /> },
  cancelled: { label: 'Cancelled', color: 'default', icon: <BlockIcon /> },
  pending: { label: 'Pending', color: 'default' },
  skipped: { label: 'Not run', color: 'default' },
};

export function StatusChip({ status, size = 'small' }: { status: string; size?: ChipProps['size'] }) {
  const s = STATUS[status] ?? { label: status, color: 'default' as const };
  const outlined = status === 'skipped' || status === 'pending';
  return <Chip size={size} label={STATUS[status] ? t(s.label) : s.label} color={s.color} icon={s.icon} variant={outlined ? 'outlined' : 'filled'} />;
}

const MODE: Record<string, ChipProps['color']> = { dry_run: 'default', paper: 'info', live: 'error' };

export function ModeChip({ mode, offline }: { mode: string; offline?: boolean }) {
  return <Chip size="small" variant="outlined" color={MODE[mode] ?? 'default'} label={offline ? `${mode} · ${t('offline')}` : mode} />;
}

export function ActionChip({ action }: { action: string | null | undefined }) {
  if (!action) return null;
  const strong = action.startsWith('strong');
  return <Chip size="small" label={action} color={ACTION_COLOR[action] ?? 'default'} variant={strong ? 'filled' : 'outlined'} />;
}
