import asyncio
import io
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml
from sqlalchemy import func, select

from quant_core.config import ConfigError, ConfigStore
from quant_core.logging import configure_logging
from quant_core.models import OrderStatus, RunMode
from quant_core.safety import LiveTradingNotAllowedError
from quant_database import Database, PipelineRun, Repositories, RunStatus
from quant_database.models import (
    AgentInstanceRow,
    AggregatedDecisionRow,
    Base,
    DecisionRow,
    FillRow,
    LLMCallRow,
    OrderRow,
    PipelineRunRow,
    RiskAssessmentRow,
    SelectionResultRow,
    SentimentResultRow,
    StockSelectionRow,
)
from quant_market_data import FakeMarketDataProvider
from quant_pipeline import PipelineBusyError, PipelineRunner, RunOptions, select_stages
from quant_pipeline.offline import offline_market_data, schema_reply
from quant_pipeline.runner import wants_fundamentals
from quant_sentiment.sources import FakeSentimentSource
from quant_trading import SimulatedBroker

AS_OF = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)
ENV = {"IBKR_ACCOUNT": "DU1234567", "ANTHROPIC_API_KEY": "test-key"}
Fakes = Callable[..., dict[str, Any]]
RUN_TABLES: list[type[Base]] = [
    AgentInstanceRow,
    SentimentResultRow,
    DecisionRow,
    AggregatedDecisionRow,
    RiskAssessmentRow,
    OrderRow,
    LLMCallRow,
]


async def count(db: Database, table: type[Base], **where: Any) -> int:
    stmt = select(func.count()).select_from(table)
    for column, value in where.items():
        stmt = stmt.where(getattr(table, column) == value)
    async with db.transaction() as s:
        return int((await s.execute(stmt)).scalar_one())


def runner(store: ConfigStore, db: Database, overrides: dict[str, Any]) -> PipelineRunner:
    return PipelineRunner(store, db, overrides=overrides, env=ENV)


# ------------------------------------------------------------------ the full dry run


async def test_full_dry_run_end_to_end(store: ConfigStore, db: Database, fakes: Fakes) -> None:
    overrides = fakes()
    report = await runner(store, db, overrides).run(
        "long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF)
    )
    assert report.ok, report.errors
    assert report.mode is RunMode.DRY_RUN  # config says paper; --dry-run wins
    run_id = report.run_id
    summary = report.summary
    assert list(summary["stages"]) == ["data_update", "sentiment", "decision", "risk", "trading"]
    assert all(s["status"] == "ok" for s in summary["stages"].values())

    # sentiment: 2 agents x 1 symbol with posts; decision: 3 instances x 4 symbols
    assert summary["sentiment_results"] == 2
    assert summary["decisions"] == 12
    assert set(summary["final_decisions"].values()) == {"buy"}
    # risk: 4 buys of 15% of the (shrinking) cash are all within the default limits
    assert set(summary["risk"].values()) == {"buy"}
    assert set(summary["orders"].values()) == {"filled"}

    # every record of the run is in the database and carries the run_id
    run = await Repositories.create(db).runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.SUCCEEDED
    assert run.mode is RunMode.DRY_RUN
    assert len(run.config_hash) == 64
    assert run.config["stages_run"] == ["data_update", "sentiment", "decision", "risk", "trading"]
    assert set(run.config["agents"]) == {
        "retail_mood",
        "event_extractor",
        "value_investor",
        "trend_follower",
        "conservative_risk_officer",
    }
    assert run.summary == summary
    assert await count(db, AgentInstanceRow, run_id=run_id) == 2 + 3 + 1
    assert await count(db, SentimentResultRow, run_id=run_id) == 2
    assert await count(db, DecisionRow, run_id=run_id) == 12
    assert await count(db, AggregatedDecisionRow, run_id=run_id) == 4
    # rules + risk officer + final, per symbol
    assert await count(db, RiskAssessmentRow, run_id=run_id) == 4 * 3
    assert await count(db, OrderRow, run_id=run_id) == 4
    assert await count(db, FillRow) == 4
    assert await count(db, LLMCallRow, run_id=run_id) == 2 + 12 + 4
    for table in RUN_TABLES:
        assert await count(db, table) == await count(db, table, run_id=run_id), table

    ledger = await Repositories.create(db).ledger.get_state("long_term_stocks", Decimal(5000))
    assert set(ledger.positions) == {"AAPL", "MSFT", "GOOGL", "NVDA"}
    assert ledger.cash < Decimal(5000)
    # the market data provider was connected by the stage and disconnected by the runner
    assert not overrides["market_data"].connected
    assert overrides["sentiment_sources"]["reddit"].closed


async def test_rerun_same_day_is_blocked_by_risk_not_duplicated(
    store: ConfigStore, db: Database, fakes: Fakes
) -> None:
    broker = SimulatedBroker()
    await runner(store, db, fakes(broker=broker)).run(
        "long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF)
    )
    second = await runner(store, db, fakes(broker=broker)).run(
        "long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF + timedelta(minutes=30))
    )
    assert second.ok
    assert set(second.summary["risk"].values()) == {"hold"}  # one order per symbol per day
    assert broker.submit_count == 4


# ------------------------------------------------------------------ failure policy


async def test_skippable_stage_failure_continues(
    store: ConfigStore, db: Database, fakes: Fakes
) -> None:
    broken = {n: FakeSentimentSource(n, fail=True) for n in ("reddit", "stocktwits", "ibkr_news")}
    report = await runner(store, db, fakes(sources=broken)).run(
        "long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF)
    )
    assert report.ok  # sentiment is on_error: skip in the pipeline config
    assert report.summary["stages"]["sentiment"]["status"] == "failed_skipped"
    assert report.summary["stages"]["trading"]["status"] == "ok"
    [error] = report.errors
    assert (error.stage, error.skipped) == ("sentiment", True)


async def test_critical_failure_aborts_before_trading(
    store: ConfigStore, db: Database, fakes: Fakes
) -> None:
    broker = SimulatedBroker()
    failing = FakeMarketDataProvider(fail_symbols=["AAPL"])
    report = await runner(store, db, fakes(market_data=failing, broker=broker)).run(
        "long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF)
    )
    assert report.status is RunStatus.FAILED
    assert list(report.summary["stages"]) == ["data_update"]  # nothing after the failure
    assert broker.submit_count == 0
    run = await Repositories.create(db).runs.get_run(report.run_id)
    assert run is not None
    assert run.status is RunStatus.FAILED
    assert run.error is not None
    assert "data_update" in run.error


async def test_setup_failure_is_recorded(store: ConfigStore, db: Database) -> None:
    # no LLM override and no API key in the environment: fail fast, before any stage
    plain = PipelineRunner(store, db, env={"IBKR_ACCOUNT": "DU1"})
    report = await plain.run("long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF))
    assert report.status is RunStatus.FAILED
    assert report.errors[0].stage == "setup"
    assert "ANTHROPIC_API_KEY" in report.errors[0].message
    assert report.summary["stages"] == {}


async def test_broker_mode_mismatch_fails_the_run(
    store: ConfigStore, db: Database, fakes: Fakes
) -> None:
    # config mode is paper; a dry-run (simulated) broker must not be used for it
    report = await runner(store, db, fakes()).run("long_term_stocks", RunOptions(as_of=AS_OF))
    assert report.status is RunStatus.FAILED
    assert report.summary["stages"]["trading"]["status"] == "failed"
    assert "broker simulated is for mode dry_run" in report.errors[-1].message


# ------------------------------------------------------------------ options and guards


async def test_stage_subset(store: ConfigStore, db: Database, fakes: Fakes) -> None:
    overrides = fakes()
    del overrides["broker"]  # not needed: no trading stage selected
    report = await runner(store, db, overrides).run(
        "long_term_stocks", RunOptions(stages=["data", "sentiment"], as_of=AS_OF)
    )
    assert report.ok
    assert list(report.summary["stages"]) == ["data_update", "sentiment"]
    assert report.mode is RunMode.PAPER  # nothing traded, so paper mode is harmless here


def test_select_stages(store: ConfigStore) -> None:
    pipeline = store.pipeline("long_term_stocks")
    assert [s.type for s in select_stages(pipeline, None)][-1] == "trading"
    assert [s.type for s in select_stages(pipeline, ["trade", " decision"])] == [
        "decision",
        "trading",
    ]
    with pytest.raises(ConfigError, match="no enabled stages"):
        select_stages(pipeline, ["backtest"])
    demo = store.pipeline("demo_all_modules")
    assert [s.type for s in select_stages(demo, ["select", "data"])] == [
        "selection",
        "data_update",
    ]


async def test_selection_uses_the_shared_market_data_provider(
    store: ConfigStore, db: Database, fakes: Fakes
) -> None:
    """Outside offline mode the selection stage refreshes candidate bars through the same
    market data provider as data_update, and its candidate sources can be overridden."""
    from quant_selection import FakeCandidateSource

    symbols = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "V", "COST", "LLY"]
    provider = offline_market_data([*symbols, "AMD"], AS_OF)
    overrides = fakes(market_data=provider, llm=schema_reply)
    overrides["candidate_sources"] = {"ibkr_scanner": FakeCandidateSource("ibkr_scanner", ["AMD"])}
    overrides["llm"].set("deepseek", overrides["llm"].get("anthropic"))
    report = await runner(store, db, overrides).run(
        "demo_all_modules", RunOptions(dry_run=True, as_of=AS_OF, stages=["select", "data"])
    )
    assert report.ok, report.errors
    # the demo scans the market only (include_universe: false): the scanner's AMD
    assert report.summary["selection"]["candidates"] == 1
    assert report.summary["universe"] == ["AMD"]
    assert ("fetch_bars", "AMD") in provider.calls
    stored = await Repositories.create(db).bars.get_latest_bars("AMD", 5, as_of=AS_OF)
    assert len(stored) == 5  # the scanner's candidate got bars through the provider


async def test_concurrent_runs_are_refused(store: ConfigStore, db: Database, fakes: Fakes) -> None:
    repos = Repositories.create(db)
    now = datetime.now(UTC)
    await repos.runs.start_run(
        PipelineRun(
            run_id=uuid4(),
            pipeline_name="long_term_stocks",
            mode=RunMode.DRY_RUN,
            config_hash="0" * 64,
            config={},
            as_of=now,
            started_at=now - timedelta(minutes=5),
        )
    )
    with pytest.raises(PipelineBusyError, match="already running"):
        await runner(store, db, fakes()).run("long_term_stocks", RunOptions(dry_run=True))


async def test_stale_run_is_closed_and_ignored(
    store: ConfigStore, db: Database, fakes: Fakes
) -> None:
    repos = Repositories.create(db)
    stale = uuid4()
    long_ago = datetime.now(UTC) - timedelta(hours=10)
    await repos.runs.start_run(
        PipelineRun(
            run_id=stale,
            pipeline_name="long_term_stocks",
            mode=RunMode.DRY_RUN,
            config_hash="0" * 64,
            config={},
            as_of=long_ago,
            started_at=long_ago,
        )
    )
    report = await runner(store, db, fakes()).run(
        "long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF)
    )
    assert report.ok
    old = await repos.runs.get_run(stale)
    assert old is not None
    assert old.status is RunStatus.FAILED
    assert "stale" in (old.error or "")


async def test_live_config_needs_env_flag(configs: Path, db: Database, fakes: Fakes) -> None:
    path = configs / "pipelines" / "long_term_stocks.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["mode"] = "live"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    store = ConfigStore(configs, env=ENV)
    with pytest.raises(LiveTradingNotAllowedError):
        await runner(store, db, fakes()).run("long_term_stocks", RunOptions(as_of=AS_OF))
    async with db.transaction() as s:  # refused before anything was recorded
        assert (await s.execute(select(func.count()).select_from(PipelineRunRow))).scalar() == 0
    # an explicit --dry-run makes the same config safe to run
    report = await runner(store, db, fakes()).run(
        "long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF)
    )
    assert report.mode is RunMode.DRY_RUN


async def test_every_log_line_carries_the_run_id(
    store: ConfigStore, db: Database, fakes: Fakes
) -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    report = await runner(store, db, fakes()).run(
        "long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF)
    )
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(lines) > 5
    assert {line.get("run_id") for line in lines} == {str(report.run_id)}
    assert {line["event"] for line in lines} >= {"pipeline.start", "pipeline.finish"}


async def test_offline_mode(store: ConfigStore, db: Database) -> None:
    report = await PipelineRunner(store, db, env={}).run(
        "long_term_stocks", RunOptions(offline=True, as_of=AS_OF)
    )
    assert report.ok
    assert report.mode is RunMode.DRY_RUN
    assert report.summary["decisions"] == 12
    assert report.summary["orders"] == {}  # the neutral offline LLM holds everything


async def test_demo_pipeline_exercises_every_module(store: ConfigStore, db: Database) -> None:
    """configs/pipelines/demo_all_modules.yaml, offline with the bullish fake LLM."""
    config = store.pipeline("demo_all_modules")

    def agents(stage: str) -> int:  # agent counts are edited in the web UI: read them
        found = config.stage(stage)
        assert found is not None
        return sum(ref.count for ref in found.agents)

    n_sel, n_sent, instances, n_risk = (
        agents("selection"),
        agents("sentiment"),
        agents("decision"),
        agents("risk"),
    )
    report = await PipelineRunner(store, db, env={}).run(
        "demo_all_modules", RunOptions(offline=True, offline_llm="bullish", as_of=AS_OF)
    )
    assert report.ok, report.errors
    summary = report.summary
    assert {name: s["status"] for name, s in summary["stages"].items()} == {
        "selection": "ok",
        "data_update": "ok",
        "sentiment": "ok",
        "decision": "ok",
        "risk": "ok",
        "trading": "ok",
    }
    # only the offline scanner's NVDA, AMZN, GOOGL, META, JPM, XOM (include_universe: false)
    selection = summary["selection"]
    assert selection["candidates"] == 6
    selected = selection["selected"]
    assert len(selected) == 3  # top_n; the offline agents both pick the 3 first shown
    assert list(selection["scores"].values()) == [0.7, 0.6, 0.5]
    assert summary["universe"] == selected  # nothing held yet
    assert summary["sentiment_results"] == n_sent * 3  # every sentiment agent x 3 symbols
    assert summary["decisions"] == instances * 3  # every decision instance x 3 symbols
    assert summary["final_decisions"] == dict.fromkeys(selected, "buy")
    assert summary["risk"] == dict.fromkeys(selected, "buy")
    assert summary["orders"] == dict.fromkeys(selected, "dry_run")  # recorded, never sent

    run_id = report.run_id
    assert await count(db, StockSelectionRow, run_id=run_id) == 1
    assert await count(db, SelectionResultRow, run_id=run_id) == n_sel
    assert await count(db, AgentInstanceRow, run_id=run_id) == (n_sel + n_sent + instances + n_risk)
    assert await count(db, SentimentResultRow, run_id=run_id) == n_sent * 3
    assert await count(db, RiskAssessmentRow, run_id=run_id) == 3 * (
        2 + n_risk
    )  # rules, agents, final
    assert await count(db, OrderRow, run_id=run_id) == 3
    assert await count(db, FillRow) == 0  # dry run: nothing fills
    assert await count(db, LLMCallRow, run_id=run_id) == (
        n_sel + n_sent * 3 + instances * 3 + n_risk * 3
    )


async def test_offline_neutral_llm_never_trades_but_analyses(
    store: ConfigStore, db: Database
) -> None:
    report = await PipelineRunner(store, db, env={}).run(
        "demo_all_modules", RunOptions(offline=True, as_of=AS_OF)
    )
    assert report.ok
    assert report.summary["sentiment_results"] == 6  # synthetic posts are analysed
    assert set(report.summary["final_decisions"].values()) == {"hold"}
    assert report.summary["orders"] == {}


async def test_paper_flag_forces_paper_mode_never_live(
    store: ConfigStore, db: Database, fakes: Fakes
) -> None:
    # demo config says dry_run; --paper switches to paper, so a dry-run broker is refused
    report = await runner(store, db, fakes()).run(
        "demo_all_modules", RunOptions(paper=True, as_of=AS_OF, stages=["risk", "trading"])
    )
    assert report.mode is RunMode.PAPER
    with pytest.raises(ConfigError, match="either dry_run or paper"):
        await runner(store, db, fakes()).run(
            "demo_all_modules", RunOptions(paper=True, dry_run=True, as_of=AS_OF)
        )


async def test_stage_progress_events_are_logged(
    store: ConfigStore, db: Database, fakes: Fakes
) -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    await runner(store, db, fakes()).run("long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF))
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    starts = [line["stage"] for line in lines if line["event"] == "pipeline.stage_start"]
    done = [
        (line["stage"], line["status"]) for line in lines if line["event"] == "pipeline.stage_done"
    ]
    assert starts == ["data_update", "sentiment", "decision", "risk", "trading"]
    assert done == [(stage, "ok") for stage in starts]
    assert {line["total"] for line in lines if line["event"] == "pipeline.stage_start"} == {5}


class BlockingMarketData(FakeMarketDataProvider):
    """Hangs in connect() so the run can be cancelled mid-stage."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.disconnected = False

    async def connect(self) -> None:
        self.entered.set()
        await asyncio.Event().wait()

    async def disconnect(self) -> None:
        self.disconnected = True


async def test_cancelled_run_is_closed_and_marked_failed(
    store: ConfigStore, db: Database, fakes: Fakes
) -> None:
    market_data = BlockingMarketData()
    task = asyncio.create_task(
        runner(store, db, fakes(market_data=market_data)).run(
            "long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF)
        )
    )
    await asyncio.wait_for(market_data.entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert market_data.disconnected
    async with db.transaction() as s:
        row = (await s.execute(select(PipelineRunRow))).scalar_one()
    assert row.status == RunStatus.FAILED.value
    assert row.error == "cancelled before completion"
    assert row.ended_at is not None


# ------------------------------------------------------------------ data flow between runs


def edit_pipeline(configs: Path, name: str, change: Callable[[dict[str, Any]], None]) -> None:
    path = configs / "pipelines" / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


async def test_held_symbols_outside_the_universe_stay_tradable(
    configs: Path, store: ConfigStore, db: Database, fakes: Fakes
) -> None:
    broker = SimulatedBroker(commission=Decimal(1), clock=lambda: AS_OF + timedelta(hours=1))
    first = await runner(store, db, fakes(broker=broker)).run(
        "long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF)
    )
    universe = ["AAPL", "MSFT", "GOOGL", "NVDA"]
    assert first.ok
    assert set(first.summary["orders"]) == set(universe)

    edit_pipeline(configs, "long_term_stocks", lambda d: d.update(universe=["AAPL"]))
    second = await runner(store, db, fakes()).run(
        "long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF + timedelta(days=1))
    )
    assert second.ok, second.errors
    assert second.summary["universe"] == ["AAPL", "GOOGL", "MSFT", "NVDA"]
    assert set(second.summary["final_decisions"]) == set(universe)  # held ones get decisions


async def test_open_orders_are_reconciled_before_any_stage(
    configs: Path, store: ConfigStore, db: Database, fakes: Fakes
) -> None:
    def no_waiting(data: dict[str, Any]) -> None:
        trading = next(s for s in data["stages"] if s["type"] == "trading")
        trading["wait_for_fills"] = False

    edit_pipeline(configs, "long_term_stocks", no_waiting)
    broker = SimulatedBroker("never", clock=lambda: AS_OF + timedelta(hours=1))
    first = await runner(store, db, fakes(broker=broker)).run(
        "long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF)
    )
    assert set(first.summary["orders"].values()) == {"submitted"}
    # the orders fill at the broker after the run ended
    for order in broker.orders.values():
        fill = broker._fill(order.intent, order.intent.quantity, 1)
        order.result = order.result.model_copy(
            update={
                "status": OrderStatus.FILLED,
                "filled_qty": fill.qty,
                "avg_fill_price": fill.price,
                "fills": [fill],
            }
        )

    overrides = fakes(broker=broker)
    llm = overrides["llm"].get("anthropic")  # the runner closes the pool at the end
    second = await runner(store, db, overrides).run(
        "long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF + timedelta(days=1))
    )
    assert second.ok, second.errors
    prompts = [r.messages[0].content for r in llm.requests]
    decision_prompts = [p for p in prompts if "You decide on ONE action" in p]
    # the decision stage already saw the fills that the trading stage of run 2 reconciled
    assert decision_prompts
    assert all("Position [pos:" in p for p in decision_prompts)


async def test_offline_runs_use_fake_fundamentals(store: ConfigStore, db: Database) -> None:
    report = await PipelineRunner(store, db, env={}).run(
        "long_term_stocks", RunOptions(offline=True, as_of=AS_OF)
    )
    assert report.ok, report.errors
    stored = await Repositories.create(db).fundamentals.get_latest("AAPL", AS_OF)
    assert stored is not None
    assert stored.source == "fake"
    spy = await Repositories.create(db).bars.get_latest_bars("SPY", 5, as_of=AS_OF)
    assert spy  # the benchmark's bars were kept up to date


def test_wants_fundamentals(store: ConfigStore) -> None:
    assert wants_fundamentals(store.pipeline("long_term_stocks").stages)
    assert not wants_fundamentals(store.pipeline("etf_allocation").stages)


async def test_watchlist_entries_join_pipelines_without_selection(
    store: ConfigStore, db: Database, fakes: Fakes
) -> None:
    repos = Repositories.create(db)
    await repos.watchlist.add("long_term_stocks", "AMD", AS_OF - timedelta(days=1), pinned=True)
    provider = offline_market_data(["AAPL", "MSFT", "GOOGL", "NVDA", "AMD", "SPY"], AS_OF)
    report = await runner(store, db, fakes(market_data=provider)).run(
        "long_term_stocks", RunOptions(dry_run=True, as_of=AS_OF, stages=["data", "decision"])
    )
    assert report.ok, report.errors
    assert report.summary["universe"] == ["AAPL", "MSFT", "GOOGL", "NVDA", "AMD"]
    assert "AMD" in report.summary["final_decisions"]
