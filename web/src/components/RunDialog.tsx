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
      <DialogTitle>运行流水线</DialogTitle>
      <DialogContent>
        <Stack spacing={2.5} sx={{ mt: 1 }}>
          <TextField select label="流水线" value={pipeline} onChange={(e) => setPipeline(e.target.value)} disabled={!!fixed} size="small">
            {pipelines.map((p) => (
              <MenuItem key={p.name} value={p.name}>
                {p.name}
                <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                  配置模式 {p.mode}
                </Typography>
              </MenuItem>
            ))}
          </TextField>

          <FormControlLabel
            control={<Switch checked={offline} onChange={(e) => setOffline(e.target.checked)} />}
            label="离线试跑（假行情、假舆情、假 LLM；不需要网关和 API key，强制 dry_run；结果写入离线沙盒数据库）"
          />
          {offline ? (
            <TextField select size="small" label="离线 LLM 风格" value={offlineLlm} onChange={(e) => setOfflineLlm(e.target.value as any)}>
              <MenuItem value="neutral">neutral：一律 hold</MenuItem>
              <MenuItem value="bullish">bullish：倾向买入（用于演示完整下单链路）</MenuItem>
            </TextField>
          ) : (
            <div>
              <FormLabel>运行模式</FormLabel>
              <RadioGroup value={mode} onChange={(e) => setMode(e.target.value as RunRequest['mode'])}>
                <FormControlLabel value="dry_run" control={<Radio size="small" />} label="dry_run：真实数据和 LLM，只记录订单不下单" />
                <FormControlLabel value="paper" control={<Radio size="small" />} label="paper：向 IBKR 模拟账户下单" />
                <FormControlLabel value="config" control={<Radio size="small" />} label={`按配置（${entry?.mode ?? '—'}）`} />
              </RadioGroup>
            </div>
          )}
          {effectiveMode === 'live' && <Alert severity="error">实盘模式！只有服务器设置了 QUANT_ALLOW_LIVE=1 才会执行，订单会使用真实资金。</Alert>}
          {effectiveMode === 'paper' && <Alert severity="info">将向 paper 账户提交真实（模拟）订单，需要 TWS / IB Gateway 在线。</Alert>}

          <div>
            <FormLabel>阶段（不选 = 全部启用的阶段）</FormLabel>
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
            label="as_of（可选，回放某个时间点；本地时间）"
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
          />

          {start.error && <Alert severity="error">{String((start.error as Error).message)}</Alert>}
          {job?.status === 'error' && <Alert severity="error">运行被拒绝：{job.error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>关闭</Button>
        <Button
          variant="contained"
          startIcon={<PlayArrowIcon />}
          disabled={!pipeline || start.isPending || (stages !== null && stages.length === 0)}
          onClick={() => start.mutate()}
          color={effectiveMode === 'live' ? 'error' : 'primary'}
        >
          {start.isPending ? '启动中…' : '启动'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
