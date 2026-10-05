export function fmtTime(iso: string | null | undefined, withSeconds = false): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: withSeconds ? '2-digit' : undefined,
    hour12: false,
  });
}

export function fmtDuration(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) return '—';
  const ms = (end ? new Date(end) : new Date()).getTime() - new Date(start).getTime();
  return fmtSeconds(ms / 1000);
}

export function fmtSeconds(s: number | null | undefined): string {
  if (s === null || s === undefined || Number.isNaN(s)) return '—';
  if (s < 1) return `${Math.round(s * 1000)} ms`;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  return `${m} 分 ${Math.round(s % 60)} 秒`;
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(digits)}%`;
}

export function fmtCompact(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  return Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 2 }).format(v);
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : '—';
}

export function sma(values: number[], n: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  values.forEach((v, i) => {
    sum += v;
    if (i >= n) sum -= values[i - n];
    out.push(i >= n - 1 ? sum / n : null);
  });
  return out;
}
