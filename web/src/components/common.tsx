import { Box, Button, Card, CardContent, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Typography } from '@mui/material';
import { toYaml } from '../lib/yamlDoc';
import { t } from '../i18n';

/** Read-only structured value, shown as YAML (more readable than JSON for nested data). */
export function JsonView({ value, maxHeight = 480, asJson = false }: { value: unknown; maxHeight?: number | string; asJson?: boolean }) {
  const text = asJson ? JSON.stringify(value, null, 2) : typeof value === 'string' ? value : toYaml(value);
  return (
    <Box
      component="pre"
      sx={{
        m: 0,
        p: 1.5,
        maxHeight,
        overflow: 'auto',
        fontSize: 12.5,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
        bgcolor: 'action.hover',
        borderRadius: 1,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}
    >
      {text}
    </Box>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      spacing={1}
      sx={{ mb: 2, alignItems: { sm: 'center' }, justifyContent: 'space-between' }}
    >
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="h5" sx={{ fontWeight: 600 }} noWrap>
          {title}
        </Typography>
        {subtitle && (
          <Typography variant="body2" color="text.secondary">
            {subtitle}
          </Typography>
        )}
      </Box>
      {actions && (
        <Stack direction="row" spacing={1} sx={{ flexShrink: 0, flexWrap: 'wrap', alignItems: 'center', rowGap: 1 }}>
          {actions}
        </Stack>
      )}
    </Stack>
  );
}

export function ConfirmDialog({
  open,
  title,
  children,
  confirmText,
  danger = false,
  onClose,
  onConfirm,
}: {
  open: boolean;
  title: string;
  children?: React.ReactNode;
  confirmText?: string;
  danger?: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>{children}</DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('Cancel')}</Button>
        <Button variant="contained" color={danger ? 'error' : 'primary'} onClick={onConfirm}>
          {confirmText ?? t('OK')}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export function StatCard({
  label,
  value,
  hint,
  color,
  icon,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  color?: string;
  icon?: React.ReactNode;
}) {
  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent>
        <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <Typography variant="body2" color="text.secondary">
            {label}
          </Typography>
          {icon && <Box sx={{ color: color ?? 'text.secondary', display: 'flex' }}>{icon}</Box>}
        </Stack>
        <Typography variant="h5" sx={{ fontWeight: 600, mt: 0.5, color, fontVariantNumeric: 'tabular-nums' }}>
          {value}
        </Typography>
        {hint && (
          <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.5 }}>
            {hint}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}

export function Section({ title, actions, children }: { title: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card variant="outlined" sx={{ mb: 2 }}>
      <CardContent>
        <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center', mb: 1.5, gap: 1, flexWrap: 'wrap' }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {title}
          </Typography>
          {actions}
        </Stack>
        {children}
      </CardContent>
    </Card>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
      {children}
    </Typography>
  );
}
