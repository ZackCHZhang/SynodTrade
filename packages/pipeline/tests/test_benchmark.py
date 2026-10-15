"""Paper-trading benchmark: equity curve from fills, metrics, SVG chart and report files."""

import asyncio
import json
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from typer.testing import CliRunner

from quant_core.config import ConfigStore
from quant_core.llm import LLMCallRecord, LLMUsage
from quant_core.models import (
    Action,
    Bar,
    Fill,
    OrderIntent,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    RunMode,
    Timeframe,
)
from quant_core.timeutil import EXCHANGE_TZ
from quant_database import Database, Repositories
from quant_database.records import PipelineRun
from quant_pipeline.benchmark import build_curves, compute_metrics, render_svg, write_benchmark
from quant_pipeline.cli import app

D = Decimal
PIPELINE = "long_term_stocks"  # max_capital 5000, benchmark SPY in the repo configs
FIRST_RUN = datetime(2026, 10, 5, 14, 0, tzinfo=UTC)  # Monday 10:00 New York
SPY = {
    date(2026, 10, 2): 500,
    date(2026, 10, 5): 505,
    date(2026, 10, 6): 510,
    date(2026, 10, 7): 495,
}
AAPL = {date(2026, 10, 5): 100, date(2026, 10, 6): 110, date(2026, 10, 7): 120}


def bar(symbol: str, day: date, close: float) -> Bar:
    c = D(str(close))
    return Bar(
        symbol=symbol,
        timeframe=Timeframe.D1,
        ts=datetime.combine(day, time(0), tzinfo=EXCHANGE_TZ),
        open=c,
        high=c,
        low=c,
        close=c,
        volume=D(1000),
    )


async def start_run(repos: Repositories, mode: RunMode, started: datetime = FIRST_RUN) -> UUID:
    run_id = uuid4()
    await repos.runs.start_run(
        PipelineRun(
            run_id=run_id,
            pipeline_name=PIPELINE,
            mode=mode,
            config_hash="0" * 64,
            config={"name": PIPELINE},
            as_of=started,
            started_at=started,
        )
    )
    return run_id


async def trade(
    repos: Repositories, run_id: UUID, coid: str, side: OrderSide, price: str, ts: datetime
) -> None:
    await repos.orders.create(
        OrderIntent(
            client_order_id=coid,
            run_id=run_id,
            pipeline_name=PIPELINE,
            symbol="AAPL",
            action=Action.BUY if side is OrderSide.BUY else Action.SELL,
            side=side,
            quantity=D(10),
            order_type=OrderType.LIMIT,
            limit_price=D(price),
            estimated_notional=D(10) * D(price),
        )
    )
    fill = Fill(
        exec_id=f"e-{coid}",
        client_order_id=coid,
        symbol="AAPL",
        side=side,
        qty=D(10),
        price=D(price),
        commission=D(1),
        ts=ts,
    )
    await repos.orders.apply_result(
        OrderResult(
            client_order_id=coid,
            status=OrderStatus.FILLED,
            filled_qty=D(10),
            avg_fill_price=D(price),
            fills=[fill],
        )
    )


async def seed(repositories: Repositories) -> None:
    """One paper run: buy 10 AAPL at 100 on Monday, sell them at 120 on Wednesday."""
    await repositories.bars.upsert([bar("SPY", d, c) for d, c in SPY.items()])
    await repositories.bars.upsert([bar("AAPL", d, c) for d, c in AAPL.items()])
    run_id = await start_run(repositories, RunMode.PAPER)
    await trade(repositories, run_id, "buy-1", OrderSide.BUY, "100", FIRST_RUN)
    await trade(
        repositories, run_id, "sell-1", OrderSide.SELL, "120", datetime(2026, 10, 7, 15, tzinfo=UTC)
    )


@pytest.fixture
async def repos(db: Database) -> Repositories:
    repositories = Repositories.create(db)
    await seed(repositories)
    return repositories


async def test_equity_curve_replays_fills_at_daily_closes(
    repos: Repositories, store: ConfigStore
) -> None:
    [curve] = await build_curves(repos, store, end=date(2026, 10, 7))

    assert curve.pipeline == PIPELINE
    assert curve.benchmark == "SPY"
    # base day = last session before the first run; then one point per SPY session
    assert [p.day for p in curve.points] == list(SPY)
    # Mon: 5000 - 1001 cash + 10 x 100; Tue: + 10 x 110; Wed: sold at 120 (commission 1)
    assert [p.nav for p in curve.points] == [5000, 4999, 5099, 5198]
    assert curve.returns[-1] == pytest.approx(0.0396)
    assert curve.benchmark_returns[-1] == pytest.approx(-0.01)
    assert (curve.fills, curve.buys, curve.sells, curve.winning_sells) == (2, 1, 1, 1)
    assert curve.realized_pnl == pytest.approx(198)
    assert curve.commissions == pytest.approx(2)
    assert curve.open_positions == 0


async def test_metrics(repos: Repositories, store: ConfigStore) -> None:
    [curve] = await build_curves(repos, store, end=date(2026, 10, 7))
    m = compute_metrics(curve)

    assert m.days == 3
    assert m.excess_return == pytest.approx(0.0496)
    assert m.max_drawdown == pytest.approx(4999 / 5000 - 1)
    assert m.benchmark_max_drawdown == pytest.approx(495 / 510 - 1)
    assert m.win_rate == 1
    # too few sessions for annualised figures
    assert m.sharpe is None
    assert m.volatility is None
    assert m.cagr is None


async def test_dry_run_only_pipelines_are_not_published(db: Database, store: ConfigStore) -> None:
    repos = Repositories.create(db)
    await start_run(repos, RunMode.DRY_RUN)
    assert await build_curves(repos, store) == []


async def test_write_benchmark_files_and_readme_markers(
    repos: Repositories, store: ConfigStore, tmp_path: Path
) -> None:
    curves = await build_curves(repos, store, end=date(2026, 10, 7))
    readme = tmp_path / "README.md"
    readme.write_text("# x\n<!-- benchmark:start -->old<!-- benchmark:end -->\ntail\n")
    zh = tmp_path / "README.zh-CN.md"
    zh.write_text("no markers here\n")

    written = write_benchmark(
        curves, tmp_path / "benchmark", readmes=[readme, zh], now=datetime(2026, 10, 8, tzinfo=UTC)
    )

    names = {p.name for p in written}
    assert {"README.md", "README.zh-CN.md", "data.json", "equity.svg"} <= names
    assert zh not in written
    assert zh.read_text() == "no markers here\n"
    root = readme.read_text()
    assert "old" not in root
    assert root.endswith("<!-- benchmark:end -->\ntail\n")
    row = (
        "| **long_term_stocks** | claude-opus-5 | +3.96% | SPY -1.00% | +4.96% | -0.02%"
        " | — | $0.00 |"
    )
    assert row in root
    assert "benchmark/equity.svg" in root

    page = (tmp_path / "benchmark" / "README.md").read_text()
    assert (
        "| **long_term_stocks** | claude-opus-5 | 2026-10-02 | +3.96% | SPY -1.00% | +4.96%"
        " | -0.02% | — | $0.00 |" in page
    )
    assert "| Models | `claude-opus-5` |" in page
    assert "Updated 2026-10-08 · data through 2026-10-07" in page
    assert "数据截至 2026-10-07" in (tmp_path / "benchmark" / "README.zh-CN.md").read_text()

    data = json.loads((tmp_path / "benchmark" / "data.json").read_text())
    [entry] = data["pipelines"]
    assert [p["nav"] for p in entry["series"]] == [5000, 4999, 5099, 5198]
    assert entry["metrics"]["win_rate"] == 1
    assert entry["models"] == ["claude-opus-5"]
    assert entry["llm"]["total"]["calls"] == 0

    svg = ET.fromstring((tmp_path / "benchmark" / "equity.svg").read_text())
    assert svg.tag.endswith("svg")
    texts = "".join(svg.itertext())
    for expected in ("long_term_stocks", "SPY (benchmark)", "+3.96%", "-1.00%"):
        assert expected in texts


async def test_fills_after_the_last_bar_still_book(repos: Repositories, store: ConfigStore) -> None:
    """Bars end on Wednesday but another buy fills on Thursday: it must not be dropped."""
    run_id = await start_run(repos, RunMode.PAPER, datetime(2026, 10, 8, 14, tzinfo=UTC))
    await trade(repos, run_id, "buy-2", OrderSide.BUY, "125", datetime(2026, 10, 8, 15, tzinfo=UTC))

    [curve] = await build_curves(repos, store, end=date(2026, 10, 8))

    assert curve.points[-1].day == date(2026, 10, 8)
    assert curve.bars_through == date(2026, 10, 7)
    assert curve.fills == 3
    # cash 5198 - 1251, plus 10 AAPL at the last known close (120)
    assert curve.points[-1].nav == pytest.approx(5198 - 1251 + 1200)
    assert curve.points[-1].benchmark_close == 495  # carried forward


def test_unknown_pipeline_is_a_usage_error(configs: Path, tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "--env-file",
            str(tmp_path / "missing.env"),
            "benchmark",
            "--db-url",
            f"sqlite+aiosqlite:///{tmp_path / 'x.db'}",
            "--configs",
            str(configs),
            "-p",
            "no_such_pipeline",
            "--out",
            str(tmp_path / "o"),
        ],
    )
    assert result.exit_code == 2
    assert "no_such_pipeline" in result.output


def test_empty_benchmark_says_so(tmp_path: Path) -> None:
    written = write_benchmark([], tmp_path)
    assert not (tmp_path / "equity.svg").exists()
    assert "No paper-trading results published yet." in (tmp_path / "README.md").read_text()
    assert {p.name for p in written} == {"README.md", "README.zh-CN.md", "data.json"}


async def test_svg_with_a_single_session(repos: Repositories, store: ConfigStore) -> None:
    [curve] = await build_curves(repos, store, end=date(2026, 10, 5))
    assert len(curve.points) == 2
    ET.fromstring(render_svg([curve]))


def test_cli(configs: Path, tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}"

    async def prepare() -> None:
        database = Database(url)
        await database.create_all()
        await seed(Repositories.create(database))
        await database.dispose()

    asyncio.run(prepare())
    out = tmp_path / "bench"
    result = CliRunner().invoke(
        app,
        [
            "--env-file",
            str(tmp_path / "missing.env"),
            "benchmark",
            "--db-url",
            url,
            "--configs",
            str(configs),
            "--out",
            str(out),
            "--end",
            "2026-10-07",
            "--readme",
            str(tmp_path / "none.md"),
        ],
        env={"IBKR_ACCOUNT": "DU1234567", "ANTHROPIC_API_KEY": "k"},
    )
    assert result.exit_code == 0, result.output
    assert (out / "equity.svg").exists()
    assert "wrote" in result.output


async def record_call(
    repos: Repositories, run_id: UUID, at: datetime, usage: LLMUsage | None, model: str
) -> None:
    await repos.llm_calls.record(
        LLMCallRecord(
            run_id=run_id,
            agent_id="trend_follower",
            provider="anthropic",
            model=model,
            attempt=1,
            request={},
            usage=usage,
            created_at=at,
        )
    )


async def test_llm_cost_per_pipeline(
    repos: Repositories, configs: Path, store: ConfigStore
) -> None:
    providers = configs / "llm_providers.yaml"
    providers.write_text(
        providers.read_text().replace(
            "    api_key_env: ANTHROPIC_API_KEY\n",
            "    api_key_env: ANTHROPIC_API_KEY\n"
            "    prices:\n"
            "      claude-opus-5: { input: 4, output: 20, cache_read: 0.2 }\n",
            1,
        )
    )
    paper = await start_run(repos, RunMode.PAPER)
    dry = await start_run(repos, RunMode.DRY_RUN)
    old = datetime(2026, 9, 20, 14, tzinfo=UTC)
    new = datetime(2026, 10, 6, 14, tzinfo=UTC)
    usage = LLMUsage(input_tokens=1_000_000, output_tokens=100_000, cache_read_input_tokens=500_000)
    await record_call(repos, paper, old, usage, "claude-opus-5")
    await record_call(repos, paper, new, usage, "claude-opus-5")
    await record_call(repos, paper, new, None, "claude-opus-5")  # failed call: no usage
    await record_call(repos, dry, new, usage, "claude-opus-5")  # dry runs never count

    [curve] = await build_curves(repos, store, end=date(2026, 10, 7))

    assert curve.models == ("claude-opus-5",)
    total, recent = curve.llm_total, curve.llm_recent
    assert total is not None
    assert recent is not None
    assert (total.calls, total.input_tokens, total.cache_read_tokens) == (3, 2_000_000, 1_000_000)
    # Anthropic input excludes cache reads: per call 1M x $4 + 0.1M x $20 + 0.5M x $0.2 = $6.10
    assert total.cost == pytest.approx(12.2)
    assert recent.calls == 2
    assert recent.cost == pytest.approx(6.1)

    written = write_benchmark([curve], configs.parent / "out")
    text = (configs.parent / "out" / "README.md").read_text()
    assert "| LLM cost (total / last 7 days) | $12.20 / $6.10 |" in text
    assert "| LLM tokens (in / out / cache read) | 2.00M / 200.0k / 1.00M |" in text
    assert written


async def test_unpriced_model_has_no_cost(repos: Repositories, store: ConfigStore) -> None:
    run_id = await start_run(repos, RunMode.PAPER)
    usage = LLMUsage(input_tokens=1000, output_tokens=10)
    await record_call(repos, run_id, FIRST_RUN, usage, "claude-opus-5")

    [curve] = await build_curves(repos, store, end=date(2026, 10, 7))

    assert curve.llm_total is not None
    assert curve.llm_total.cost is None
    assert curve.llm_total.unpriced == ("anthropic/claude-opus-5",)
