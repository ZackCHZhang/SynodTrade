"""Static SVG chart of cumulative returns: one line per pipeline, dashed lines for benchmarks.

The SVG is meant for GitHub, which shows it as an image (no scripts, no hover), so every
series has a legend entry and a direct label with its final return, and the numbers are
also in the benchmark README's table. Colours follow the light/dark preference of the viewer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from html import escape

from synodtrade_pipeline.benchmark.compute import PipelineCurve

# Categorical palette, light / dark steps (fixed order, never cycled).
SERIES = [
    ("#2a78d6", "#3987e5"),
    ("#eb6834", "#d95926"),
    ("#1baf7a", "#199e70"),
    ("#eda100", "#c98500"),
    ("#e87ba4", "#d55181"),
    ("#008300", "#008300"),
    ("#6250d6", "#9085e9"),
    ("#e34948", "#e66767"),
]
MAX_SERIES = len(SERIES)

W, H = 880, 400
LEFT, TOP, BOTTOM = 60, 64, 44
CHAR_PX = 7.4  # rough width of one 13px character, for layout
NICE_STEPS = [0.001, 0.002, 0.0025, 0.005, 0.01, 0.02, 0.025, 0.05, 0.1, 0.2, 0.25, 0.5, 1.0]


@dataclass(frozen=True, slots=True)
class Series:
    label: str
    points: list[tuple[date, float]]  # (day, cumulative return)
    benchmark: bool = False


def series_for(curves: list[PipelineCurve]) -> list[Series]:
    """Pipelines first, then each benchmark symbol once, indexed from its earliest pipeline."""
    out = [
        Series(c.pipeline, [(p.day, r) for p, r in zip(c.points, c.returns, strict=True)])
        for c in curves[:MAX_SERIES]
    ]
    seen: set[str] = set()
    for c in sorted(curves, key=lambda c: c.points[0].day):
        if c.benchmark in seen:
            continue
        pts = [
            (p.day, r) for p, r in zip(c.points, c.benchmark_returns, strict=True) if r is not None
        ]
        if pts:
            seen.add(c.benchmark)
            out.append(Series(c.benchmark, pts, benchmark=True))
    return out


def _ticks(lo: float, hi: float) -> list[float]:
    span = max(hi - lo, 0.002)
    step = next((s for s in NICE_STEPS if span / s <= 6), NICE_STEPS[-1])
    start = math.floor(lo / step) * step
    ticks = []
    v = start
    while v <= hi + step * 0.5:
        ticks.append(round(v, 6))
        v += step
    if ticks[-1] < hi:
        ticks.append(round(ticks[-1] + step, 6))
    return ticks


def _pct(v: float, step: float) -> str:
    digits = 0 if step >= 0.01 else 1
    return f"{v * 100:+.{digits}f}%" if v else "0%"


def _date_label(d: date, long_span: bool) -> str:
    return d.strftime("%b %Y") if long_span else d.strftime("%b %d").replace(" 0", " ")


def _spread(ys: list[float], gap: float, lo: float, hi: float) -> list[float]:
    """Move label positions apart (in order) so neighbours are at least `gap` px apart."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    placed = [ys[i] for i in order]
    for i in range(1, len(placed)):
        placed[i] = max(placed[i], placed[i - 1] + gap)
    overflow = placed[-1] - hi if placed else 0
    if overflow > 0:
        placed = [max(lo, y - overflow) for y in placed]
        for i in range(1, len(placed)):
            placed[i] = max(placed[i], placed[i - 1] + gap)
    out = [0.0] * len(ys)
    for i, y in zip(order, placed, strict=True):
        out[i] = y
    return out


def render_svg(curves: list[PipelineCurve], *, title: str = "Cumulative return") -> str:
    series = series_for(curves)
    days = sorted({d for s in series for d, _ in s.points})
    values = [v for s in series for _, v in s.points] + [0.0]
    ticks = _ticks(min(values), max(values))
    step = ticks[1] - ticks[0] if len(ticks) > 1 else 0.01
    y_lo, y_hi = ticks[0], ticks[-1]
    # room on the right for the longest "name +12.34%" end label
    right = 24 + CHAR_PX * max(len(s.label) + 8 for s in series)
    pw, ph = W - LEFT - right, H - TOP - BOTTOM
    index = {d: i for i, d in enumerate(days)}
    n = max(len(days) - 1, 1)

    def x(d: date) -> float:
        return LEFT + pw * index[d] / n

    def y(v: float) -> float:
        return TOP + ph * (1 - (v - y_lo) / (y_hi - y_lo))

    parts: list[str] = []
    # grid and y axis labels
    for t in ticks:
        cls = "zero" if abs(t) < 1e-12 else "grid"
        parts.append(
            f'<line class="{cls}" x1="{LEFT}" x2="{LEFT + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
        )
        parts.append(
            f'<text class="t2" x="{LEFT - 8}" y="{y(t) + 4:.1f}" text-anchor="end">'
            f"{_pct(t, step)}</text>"
        )
    # x axis labels: up to 6, evenly spaced over the sessions
    long_span = (days[-1] - days[0]).days > 200 if days else False
    count = min(6, len(days))
    picks = sorted({round(i * (len(days) - 1) / max(count - 1, 1)) for i in range(count)})
    for i in picks:
        d = days[i]
        anchor = "start" if i == 0 else "end" if i == len(days) - 1 else "middle"
        parts.append(
            f'<text class="t2" x="{x(d):.1f}" y="{TOP + ph + 22}" text-anchor="{anchor}">'
            f"{_date_label(d, long_span)}</text>"
        )
    # lines: benchmarks below pipelines
    slot = 0
    styled: list[tuple[Series, str]] = []
    for s in series:
        if s.benchmark:
            styled.append((s, "bench"))
        else:
            slot += 1
            styled.append((s, f"s{slot}"))
    for s, cls in sorted(styled, key=lambda sc: not sc[0].benchmark):
        pts = " ".join(f"{x(d):.1f},{y(v):.1f}" for d, v in s.points)
        if len(s.points) == 1:
            d, v = s.points[0]
            parts.append(f'<circle class="dot {cls}" cx="{x(d):.1f}" cy="{y(v):.1f}" r="4"/>')
        else:
            parts.append(f'<polyline class="line {cls}" points="{pts}"/>')
    # direct labels at the right end
    ends = [y(s.points[-1][1]) for s, _ in styled]
    label_ys = _spread(ends, 16, TOP + 6, TOP + ph)
    for (s, cls), ly in zip(styled, label_ys, strict=True):
        d, v = s.points[-1]
        parts.append(f'<circle class="dot {cls}" cx="{x(d):.1f}" cy="{y(v):.1f}" r="4"/>')
        parts.append(
            f'<text class="t1" x="{LEFT + pw + 12}" y="{ly + 4:.1f}">{escape(s.label)} '
            f'<tspan class="t2">{v * 100:+.2f}%</tspan></text>'
        )
    # legend
    lx = float(LEFT)
    legend: list[str] = []
    for s, cls in styled:
        legend.append(f'<line class="line {cls}" x1="{lx}" x2="{lx + 18}" y1="38" y2="38"/>')
        name = f"{s.label} (benchmark)" if s.benchmark else s.label
        legend.append(f'<text class="t1" x="{lx + 24}" y="42">{escape(name)}</text>')
        lx += 24 + CHAR_PX * len(name) + 22

    light = "".join(
        f".s{i + 1}{{stroke:{c[0]}}}.dot.s{i + 1}{{fill:{c[0]}}}" for i, c in enumerate(SERIES)
    )
    dark = "".join(
        f".s{i + 1}{{stroke:{c[1]}}}.dot.s{i + 1}{{fill:{c[1]}}}" for i, c in enumerate(SERIES)
    )
    style = (
        "text{font:13px -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif}"
        ".bg{fill:#fcfcfb;stroke:#e4e3df}.t1{fill:#0b0b0b}.t2{fill:#52514e}"
        ".title{font-weight:600;font-size:15px;fill:#0b0b0b}"
        ".grid{stroke:#e9e8e4;stroke-width:1}.zero{stroke:#a3a29d;stroke-width:1}"
        ".line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}"
        ".dot{stroke:#fcfcfb;stroke-width:2}"
        ".bench{stroke:#8a8984;stroke-dasharray:5 4}.dot.bench{fill:#8a8984;stroke-dasharray:none}"
        + light
        + "@media (prefers-color-scheme: dark){"
        ".bg{fill:#1a1a19;stroke:#2e2d2b}.t1,.title{fill:#f0efec}.t2{fill:#c3c2b7}"
        ".grid{stroke:#2e2d2b}.zero{stroke:#6b6a66}.dot{stroke:#1a1a19}"
        ".bench{stroke:#9b9a95}.dot.bench{fill:#9b9a95}" + dark + "}"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"'
        f' role="img" aria-label="{escape(title)}">\n'
        f"<style>{style}</style>\n"
        f'<rect class="bg" x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="8"/>\n'
        f'<text class="title" x="{LEFT}" y="22">{escape(title)}</text>\n'
        + "\n".join(legend + parts)
        + "\n</svg>\n"
    )
