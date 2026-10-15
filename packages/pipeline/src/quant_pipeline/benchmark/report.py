"""Write the benchmark: data.json, equity.svg and README.md / README.zh-CN.md in one folder,
plus the summary between the `<!-- benchmark:start -->` / `<!-- benchmark:end -->` markers
of the repository READMEs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from quant_pipeline.benchmark.chart import render_svg
from quant_pipeline.benchmark.compute import (
    RECENT_SPEND_DAYS,
    LLMSpend,
    Metrics,
    PipelineCurve,
    compute_metrics,
)

MARKERS = re.compile(r"(<!-- benchmark:start -->)(.*?)(<!-- benchmark:end -->)", re.S)


@dataclass(frozen=True, slots=True)
class Text:
    """Every sentence of the generated pages, in one language."""

    switch: str
    title: str
    notice: str
    updated: str
    chart_alt: str
    summary: str
    cols: tuple[str, ...]
    details: str
    detail_rows: tuple[str, ...]
    method: str
    method_items: tuple[str, ...]
    reproduce: str
    reproduce_note: str
    empty: str
    root_note: str


EN = Text(
    switch="**English** | [简体中文](README.zh-CN.md)",
    title="Paper-trading benchmark",
    notice=(
        "These are **paper-trading** results from IBKR paper accounts, not real money. Fills are"
        " real paper fills, but paper trading ignores market impact and can fill orders a live"
        " account would not. Past results say nothing about future ones. Not investment advice."
    ),
    updated="Updated {generated} · data through {through}",
    chart_alt="Cumulative paper-trading return of each pipeline against its benchmark",
    summary="Summary",
    cols=(
        "Pipeline",
        "Model",
        "Since",
        "Return",
        "Benchmark",
        "Excess",
        "Max drawdown",
        "Sharpe",
        "LLM cost",
    ),
    details="Pipelines",
    detail_rows=(
        "Models",
        "Mode",
        "Sessions",
        "Starting capital",
        "First paper/live run",
        "Net asset value",
        "Fills (buys / sells)",
        "Sells at a profit",
        "Realised P&L",
        "Commissions",
        "Open positions",
        "Invested",
        "Volatility (annualised)",
        "CAGR",
        "Benchmark max drawdown",
        "LLM calls",
        "LLM tokens (in / out / cache read)",
        f"LLM cost (total / last {RECENT_SPEND_DAYS} days)",
    ),
    method="Methodology",
    method_items=(
        "Each pipeline trades a virtual sub-account that starts at its `budget.max_capital` on the"
        " day of its first paper or live run; the base day (0%) is the last session before it.",
        "Every session, the pipeline's fills up to that day are booked with the same arithmetic as"
        " the trading ledger (commissions included) and open positions are valued at that day's"
        " close (the last known close when a symbol has no bar).",
        "The benchmark is the pipeline's `benchmark` symbol (SPY by default), indexed to the same"
        " base day. Excess = return − benchmark return.",
        "Sharpe and volatility are annualised from daily returns (252 sessions, risk-free rate 0)"
        " and need at least 20 sessions; CAGR needs at least 60. A dash means not enough data.",
        "LLM cost is the pipeline's recorded token usage (every attempt, including retries) priced"
        " at the list prices in `configs/llm_providers.yaml`; a dash means a model has no price."
        " It is an estimate: providers may bill differently (routing, discounts, time of day).",
        "Dry-run and offline runs are never included.",
    ),
    reproduce="Reproduce",
    reproduce_note=(
        "Generated from the trading database with the command below. The daily series of every"
        " pipeline is in [`data.json`](data.json)."
    ),
    empty="No paper-trading results published yet.",
    root_note=(
        "Paper trading on IBKR · updated {generated} · [details, methodology and raw data]"
        "(benchmark/README.md)"
    ),
)

ZH = Text(
    switch="[English](README.md) | **简体中文**",
    title="模拟盘（paper）基准",
    notice=(
        "以下是 IBKR **模拟账户（paper）**的交易结果，不是真实资金。"
        "成交来自模拟账户的真实成交记录，但模拟盘不考虑市场冲击，有些订单在实盘中未必能成交。"
        "过去的结果不代表未来，不构成投资建议。"
    ),
    updated="更新于 {generated} · 数据截至 {through}",
    chart_alt="各流水线模拟盘累计收益与基准对比",
    summary="概览",
    cols=("流水线", "模型", "开始", "收益", "基准", "超额收益", "最大回撤", "夏普比率", "LLM 费用"),
    details="各流水线",
    detail_rows=(
        "模型",
        "模式",
        "交易日",
        "初始资金",
        "首次 paper/live 运行",
        "当前净值",
        "成交（买 / 卖）",
        "盈利卖出占比",
        "已实现盈亏",
        "佣金",
        "持仓数",
        "仓位占比",
        "波动率（年化）",
        "年化收益",
        "基准最大回撤",
        "LLM 调用次数",
        "LLM token（输入 / 输出 / 缓存命中）",
        f"LLM 费用（累计 / 最近 {RECENT_SPEND_DAYS} 天）",
    ),
    method="计算方法",
    method_items=(
        "每条流水线有一个虚拟子账户，从首次 paper 或 live 运行当天起，以 `budget.max_capital`"
        " 为初始资金；基准日（0%）是那之前的最后一个交易日。",
        "每个交易日，按与交易账本完全相同的方法（含佣金）记入截至当天的成交，持仓按当天收盘价估值"
        "（某只股票当天没有 K 线时用最近一次收盘价）。",
        "基准是流水线配置的 `benchmark`（默认 SPY），从同一个基准日开始计算。"
        "超额收益 = 收益 − 基准收益。",
        "夏普比率和波动率由日收益年化（每年 252 个交易日，无风险利率按 0），至少需要 20 个交易日；"
        "年化收益至少需要 60 个交易日。显示为短横线表示数据还不够。",
        "LLM 费用 = 流水线记录的 token 用量（含每次重试）× `configs/llm_providers.yaml` 里的标价；"
        "显示为短横线表示有模型没有配置价格。这是估算，实际账单可能因路由、折扣或时段而不同。",
        "dry-run 和离线运行永远不计入。",
    ),
    reproduce="复现",
    reproduce_note=(
        "用下面的命令从交易数据库生成。每条流水线的每日数据在 [`data.json`](data.json)。"
    ),
    empty="还没有发布模拟盘结果。",
    root_note=(
        "IBKR 模拟盘 · 更新于 {generated} · "
        "[详细数据、计算方法和原始数据](benchmark/README.zh-CN.md)"
    ),
)

COMMAND = "poetry run quant benchmark"

Rows = list[tuple[PipelineCurve, Metrics]]


def pct(v: float | None, signed: bool = True) -> str:
    if v is None:
        return "—"
    return f"{v * 100:+.2f}%" if signed else f"{v * 100:.2f}%"


def num(v: float | None, digits: int = 2) -> str:
    return "—" if v is None else f"{v:,.{digits}f}"


def usd(v: float | None) -> str:
    if v is None:
        return "—"
    return f"${v:,.2f}" if v >= 0.01 or v == 0 else f"${v:.4f}"


def tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def models_label(models: tuple[str, ...]) -> str:
    """Short model names (without a `vendor/` prefix); more than two are summarised."""
    if not models:
        return "—"
    short = [m.rsplit("/", 1)[-1] for m in models]
    return ", ".join(short) if len(short) <= 2 else f"{short[0]} +{len(short) - 1}"


def spend_cost(spend: LLMSpend | None) -> str:
    return usd(spend.cost) if spend is not None else "—"


def _summary_rows(rows: Rows, *, compact: bool) -> list[str]:
    """One row per pipeline; `compact` (the repository README) leaves out the start date."""
    out = []
    for c, m in rows:
        cells = [
            f"**{c.pipeline}**",
            models_label(c.models),
            *([] if compact else [c.points[0].day.isoformat()]),
            pct(m.total_return),
            f"{c.benchmark} {pct(m.benchmark_return)}",
            pct(m.excess_return),
            pct(m.max_drawdown),
            num(m.sharpe),
            spend_cost(c.llm_total),
        ]
        out.append("| " + " | ".join(cells) + " |")
    return out


def _table(cols: tuple[str, ...], rows: list[str], *, text_cols: int = 1) -> list[str]:
    """A Markdown table; the first `text_cols` columns are left-aligned, the rest right."""
    head = "| " + " | ".join(cols) + " |"
    align = "|" + "|".join(":--" if i < text_cols else "--:" for i in range(len(cols))) + "|"
    return [head, align, *rows]


def page(text: Text, rows: Rows, generated: str, through: str) -> str:
    lines = [f"# {text.title}", "", text.switch, "", "> [!IMPORTANT]", f"> {text.notice}", ""]
    if not rows:
        return "\n".join([*lines, text.empty, ""])
    lines += [
        f"<sub>{text.updated.format(generated=generated, through=through)}</sub>",
        "",
        f'<p align="center"><img src="equity.svg" alt="{text.chart_alt}" width="880"></p>',
        "",
        f"## {text.summary}",
        "",
        *_table(text.cols, _summary_rows(rows, compact=False), text_cols=2),
        "",
        f"## {text.details}",
        "",
    ]
    for c, m in rows:
        nav = c.points[-1].nav
        total = c.llm_total
        values = (
            ", ".join(f"`{m}`" for m in c.models) or "—",
            c.mode,
            str(m.days),
            f"{num(c.capital)}",
            c.started.strftime("%Y-%m-%d %H:%M UTC"),
            f"{num(nav)} ({pct(nav / c.capital - 1)})",
            f"{c.fills} ({c.buys} / {c.sells})",
            pct(m.win_rate, signed=False),
            num(c.realized_pnl),
            num(c.commissions),
            str(c.open_positions),
            pct(c.invested, signed=False),
            pct(m.volatility, signed=False),
            pct(m.cagr),
            pct(m.benchmark_max_drawdown),
            str(total.calls) if total else "—",
            (
                f"{tokens(total.input_tokens)} / {tokens(total.output_tokens)}"
                f" / {tokens(total.cache_read_tokens)}"
                if total
                else "—"
            ),
            f"{spend_cost(total)} / {spend_cost(c.llm_recent)}",
        )
        lines += [f"### {c.pipeline}", "", "| | |", "|:--|--:|"]
        lines += [f"| {k} | {v} |" for k, v in zip(text.detail_rows, values, strict=True)]
        lines.append("")
    lines += [f"## {text.method}", "", *(f"- {item}" for item in text.method_items), ""]
    lines += [f"## {text.reproduce}", "", text.reproduce_note, "", "```bash", COMMAND, "```", ""]
    return "\n".join(lines)


def root_section(text: Text, rows: list[tuple[PipelineCurve, Metrics]], generated: str) -> str:
    if not rows:
        return f"\n{text.empty}\n"
    readme = "README.md" if text is EN else "README.zh-CN.md"
    return "\n".join(
        [
            "",
            f'<p align="center"><a href="benchmark/{readme}"><img src="benchmark/equity.svg"'
            f' alt="{text.chart_alt}" width="880"></a></p>',
            "",
            *_table(
                (*text.cols[:2], *text.cols[3:]), _summary_rows(rows, compact=True), text_cols=2
            ),
            "",
            f"<sub>{text.root_note.format(generated=generated)}</sub>",
            "",
        ]
    )


def update_markers(path: Path, section: str) -> bool:
    """Replace the text between the benchmark markers; False if the file has no markers."""
    if not path.is_file():
        return False
    content = path.read_text(encoding="utf-8")
    if not MARKERS.search(content):
        return False
    updated = MARKERS.sub(lambda m: m.group(1) + section + m.group(3), content, count=1)
    path.write_text(updated, "utf-8")
    return True


def _spend_json(spend: LLMSpend | None) -> dict[str, object] | None:
    if spend is None:
        return None
    return {
        "calls": spend.calls,
        "input_tokens": spend.input_tokens,
        "output_tokens": spend.output_tokens,
        "cache_read_tokens": spend.cache_read_tokens,
        "cache_write_tokens": spend.cache_write_tokens,
        "cost_usd": None if spend.cost is None else round(spend.cost, 4),
        "unpriced": list(spend.unpriced),
    }


def data(rows: list[tuple[PipelineCurve, Metrics]], generated: str) -> dict[str, object]:
    return {
        "generated_at": generated,
        "kind": "paper-trading benchmark",
        "pipelines": [
            {
                "pipeline": c.pipeline,
                "mode": c.mode,
                "benchmark": c.benchmark,
                "capital": c.capital,
                "started": c.started.isoformat(),
                "models": list(c.models),
                "llm": {
                    "total": _spend_json(c.llm_total),
                    f"last_{RECENT_SPEND_DAYS}_days": _spend_json(c.llm_recent),
                },
                "metrics": {k: getattr(m, k) for k in m.__slots__},
                "stats": {
                    "fills": c.fills,
                    "buys": c.buys,
                    "sells": c.sells,
                    "winning_sells": c.winning_sells,
                    "realized_pnl": round(c.realized_pnl, 2),
                    "commissions": round(c.commissions, 2),
                    "open_positions": c.open_positions,
                    "invested": round(c.invested, 4),
                },
                "series": [
                    {
                        "date": p.day.isoformat(),
                        "nav": round(p.nav, 2),
                        "return": round(r, 6),
                        "benchmark_close": p.benchmark_close,
                        "benchmark_return": None if b is None else round(b, 6),
                    }
                    for p, r, b in zip(c.points, c.returns, c.benchmark_returns, strict=True)
                ],
            }
            for c, m in rows
        ],
    }


def write_benchmark(
    curves: list[PipelineCurve],
    out_dir: Path,
    *,
    readmes: list[Path] | None = None,
    now: datetime | None = None,
) -> list[Path]:
    """Write the benchmark folder and update the README markers; returns the files written."""
    rows = [(c, compute_metrics(c)) for c in curves]
    generated = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
    through = max((c.points[-1].day for c in curves), default=None)
    through_s = through.isoformat() if through else "—"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    files = {
        "README.md": page(EN, rows, generated, through_s),
        "README.zh-CN.md": page(ZH, rows, generated, through_s),
        "data.json": json.dumps(data(rows, generated), indent=1, ensure_ascii=False) + "\n",
    }
    if curves:
        files["equity.svg"] = render_svg(curves)
    for name, content in files.items():
        (out_dir / name).write_text(content, encoding="utf-8")
        written.append(out_dir / name)
    for readme in readmes or []:
        text = ZH if readme.name.endswith(".zh-CN.md") else EN
        if update_markers(readme, root_section(text, rows, generated)):
            written.append(readme)
    return written
