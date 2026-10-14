import {
  Alert,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  FormGroup,
  FormLabel,
  MenuItem,
  Radio,
  RadioGroup,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, type RunRequest } from '../api/client';
import { useConfigs } from '../api/hooks';
import { stageLabel } from '../lib/labels';
import { t } from '../i18n';

export function RunDialog({ open, onClose, pipeline: fixed }: { open: boolean; onClose: () => void; pipeline?: string }) {
  const { data: configs } = useConfigs();
  const pipelines = configs?.pipelines ?? [];
  const [pipeline, setPipeline] = useState(fixed ?? '');
  const [mode, setMode] = useState<RunRequest['mode']>('dry_run');
  const [offline, setOffline] = useState(false);
  const [offlineLlm, setOfflineLlm] = useState<'neutral' | 'bullish'>('neutral');
  const [stages, setStages] = useState<string[] | null>(null);
  const [asOf, setAsOf] = useState('');
  const navigate = useNavigate();
  const qc = useQueryClient();

  useEffect(() => {
    if (open) {
      setPipeline(fixed ?? pipelines[0]?.name ?? '');
      setStages(null);
    }
  }, [open, fixed]); // eslint-disable-line react-hooks/exhaustive-deps

  const entry = pipelines.find((p) => p.name === pipeline);
  const allStages = entry?.stages ?? [];
  const start = useMutation({
    mutationFn: () =>
      api.startJob({
        pipeline,
        mode,
        offline,
        offline_llm: offlineLlm,
        stages: stages && stages.length < allStages.length ? stages : null,
        as_of: asOf ? new Date(asOf).toISOString() : null,
      }),
    onSuccess: (job) => {
      qc.invalidateQueries({ queryKey: ['runs'] });
      qc.invalidateQueries({ queryKey: ['overview'] });
      if (job.status !== 'error' && job.run_id) {
        onClose();
        navigate(`/runs/${job.run_id}`);
      } else if (job.status !== 'error') {
        onClose();
        navigate('/runs');
      }
    },
  });
  const job = start.data;
  const effectiveMode = offline ? 'dry_run' : mode === 'config' ? entry?.mode ?? '?' : mode;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t('Run pipeline')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2.5} sx={{ mt: 1 }}>
          <TextField select label={t('Pipeline')} value={pipeline} onChange={(e) => setPipeline(e.target.value)} disabled={!!fixed} size="small">
            {pipelines.map((p) => (
              <MenuItem key={p.name} value={p.name}>
                {p.name}
                <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                  {t('Config mode {mode}', { mode: p.mode })}
                </Typography>
              </MenuItem>
            ))}
          </TextField>

          <FormControlLabel
            control={<Switch checked={offline} onChange={(e) => setOffline(e.target.checked)} />}
            label={t('Offline trial run (fake market data, fake sentiment, fake LLM; no gateway or API keys needed, forces dry_run; results go to the offline sandbox database)')}
          />
          {offline ? (
            <TextField select size="small" label={t('Offline LLM style')} value={offlineLlm} onChange={(e) => setOfflineLlm(e.target.value as any)}>
              <MenuItem value="neutral">{t('neutral: always hold')}</MenuItem>
              <MenuItem value="bullish">{t('bullish: leans to buy (demonstrates the full order flow)')}</MenuItem>
            </TextField>
          ) : (
            <div>
              <FormLabel>{t('Run mode')}</FormLabel>
              <RadioGroup value={mode} onChange={(e) => setMode(e.target.value as RunRequest['mode'])}>
                <FormControlLabel value="dry_run" control={<Radio size="small" />} label={t('dry_run: real data and LLM, orders recorded but not placed')} />
                <FormControlLabel value="paper" control={<Radio size="small" />} label={t('paper: place orders on the IBKR paper account')} />
                <FormControlLabel value="config" control={<Radio size="small" />} label={t('From config ({mode})', { mode: entry?.mode ?? '—' })} />
              </RadioGroup>
            </div>
          )}
          {effectiveMode === 'live' && <Alert severity="error">{t('Live mode! It only runs if the server sets QUANT_ALLOW_LIVE=1, and orders use real money.')}</Alert>}
          {effectiveMode === 'paper' && <Alert severity="info">{t('Real (simulated) orders will be sent to the paper account; TWS / IB Gateway must be online.')}</Alert>}

          <div>
            <FormLabel>{t('Stages (none selected = all enabled stages)')}</FormLabel>
            <FormGroup row>
              {allStages.map((s) => (
                <FormControlLabel
                  key={s}
                  control={
                    <Checkbox
                      size="small"
                      checked={stages === null || stages.includes(s)}
                      onChange={(e) => {
                        const cur = stages ?? allStages;
                        setStages(e.target.checked ? [...cur, s] : cur.filter((x) => x !== s));
                      }}
                    />
                  }
                  label={stageLabel(s)}
                />
              ))}
            </FormGroup>
          </div>

          <TextField
            type="datetime-local"
            size="small"
            label={t('as_of (optional, replay a point in time; local time)')}
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
          />

          {start.error && <Alert severity="error">{String((start.error as Error).message)}</Alert>}
          {job?.status === 'error' && <Alert severity="error">{t('Run rejected: {error}', { error: job.error })}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('Close')}</Button>
        <Button
          variant="contained"
          startIcon={<PlayArrowIcon />}
          disabled={!pipeline || start.isPending || (stages !== null && stages.length === 0)}
          onClick={() => start.mutate()}
          color={effectiveMode === 'live' ? 'error' : 'primary'}
        >
          {start.isPending ? t('Starting…') : t('Start')}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
