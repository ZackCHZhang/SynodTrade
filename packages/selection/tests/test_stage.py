"""The selection stage end to end: SQLite, fake LLM, fake candidate sources and bars."""

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from quant_core.config import ConfigStore, PipelineConfig, StageConfig
from quant_core.llm import FakeLLMClient, LLMClientPool, LLMRequest
from quant_core.models import (
    Action,
    Bar,
    Fill,
    OrderIntent,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    PipelineContext,
    RunMode,
    Timeframe,
)
from quant_core.services import Services
from quant_database import Repositories
from quant_selection import (
    CandidateSourceError,
    FakeCandidateSource,
    SelectionError,
    SelectionStage,
    build_selection_stage,
)

NewRun = Callable[..., Any]
NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)  # as in conftest (not importable in tests)
PIPELINE = "stock_picker"


def bars_from_closes(symbol: str, closes: Sequence[float], volume: int = 1_000_000) -> list[Bar]:
    start = datetime(2025, 9, 1, 4, 0, tzinfo=UTC)
    return [
        Bar(
            symbol=symbol,
            timeframe=Timeframe.D1,
            ts=start + timedelta(days=i),
            open=Decimal(str(c)),
            high=Decimal(str(c)) + 1,
            low=Decimal(str(c)) - 1,
            close=Decimal(str(c)),
            volume=Decimal(volume),
        )
        for i, c in enumerate(closes)
    ]


UP = [100.0 + i * 0.5 for i in range(300)]
DOWN = [300.0 - i * 0.5 for i in range(300)]
FLAT = [50.0 + (i % 3) for i in range(300)]
BARS = {
    "AAPL": bars_from_closes("AAPL", UP),
    "MSFT": bars_from_closes("MSFT", DOWN),
    "NVDA": bars_from_closes("NVDA", UP, volume=3_000_000),
    "JPM": bars_from_closes("JPM", FLAT),
    "AMD": bars_from_closes("AMD", UP),
    "PENNY": bars_from_closes("PENNY", [2.0] * 300),
    "XOM": bars_from_closes("XOM", FLAT),
}


class FakeBars:
    """BarsRefresher writing the prepared bars; symbols without bars fail."""

    def __init__(self, repos: Repositories, bars: dict[str, list[Bar]]) -> None:
        self._repos = repos
        self._bars = bars
        self.calls: list[list[str]] = []

    async def refresh_bars(
        self, symbols: Sequence[str], *, timeframe: Timeframe, lookback: timedelta, now: datetime
    ) -> dict[str, str]:
        self.calls.append(list(symbols))
        errors = {}
        for s in symbols:
            if s in self._bars:
                await self._repos.bars.upsert(self._bars[s])
            else:
                errors[s] = "MarketDataError: unknown symbol"
        return errors


def picks_reply(request: LLMRequest) -> str:
    if "momentum" in (request.system or ""):
        picks = [("AAPL", 0.9), ("NVDA", 0.8), ("TSLA", 1.0)]  # TSLA is not a candidate
    else:
        picks = [("JPM", 0.7), ("AAPL", 0.6)]
    return json.dumps(
        {
            "picks": [{"symbol": s, "score": v, "reason": "numbers"} for s, v in picks],
            "summary": "chosen",
        }
    )


def pipeline_config(universe: list[str]) -> PipelineConfig:
    return PipelineConfig.model_validate(
        {
            "name": PIPELINE,
            "account": "ibkr_main",
            "universe": universe,
            "budget": {"max_capital": 10000},
            "stages": [{"type": "selection"}],
        }
    )


def stage_config(**overrides: Any) -> StageConfig:
    return StageConfig.model_validate(
        {
            "type": "selection",
            "sources": [
                {"type": "static", "symbols": ["NVDA", "JPM", "GHOST", "PENNY"]},
                {"type": "ibkr_scanner", "scan_code": "MOST_ACTIVE"},
            ],
            "agents": [
                {
                    "agent": "momentum_screener",
                    "count": 2,
                    "model": {"provider": "deepseek", "name": "deepseek-chat"},
                },
                {
                    "agent": "defensive_screener",
                    "weight": 0.5,
                    "model": {"provider": "anthropic", "name": "claude-sonnet-5-5"},
                },
            ],
            "aggregation": {"top_n": 2},
            "max_picks_per_agent": 5,
            **overrides,
        }
    )


def build(
    repos: Repositories,
    store: ConfigStore,
    llm: FakeLLMClient,
    *,
    config: StageConfig | None = None,
    universe: list[str] | None = None,
    scanner: FakeCandidateSource | None = None,
    anthropic: FakeLLMClient | None = None,
) -> tuple[SelectionStage, FakeBars]:
    pool = LLMClientPool({}, env={})
    pool.set("deepseek", llm)
    pool.set("anthropic", anthropic or llm)
    bars = FakeBars(repos, BARS)
    services = Services(
        repos=repos,
        config_store=store,
        llm=pool,
        pipeline=pipeline_config(["AAPL", "MSFT"] if universe is None else universe),
        bars_refresher=bars,
        candidate_sources={
            "ibkr_scanner": scanner or FakeCandidateSource("ibkr_scanner", ["AMD", "NVDA"])
        },
    )
    stage = build_selection_stage(config or stage_config(), services)
    return stage, bars


async def hold(repos: Repositories, new_run: NewRun, symbol: str) -> None:
    """The pipeline's sub-ledger holds 3 shares of `symbol`."""
    run = await new_run(NOW - timedelta(days=10))
    intent = OrderIntent(
        client_order_id=f"seed-{symbol}",
        run_id=run,
        pipeline_name=PIPELINE,
        symbol=symbol,
        action=Action.BUY,
        side=OrderSide.BUY,
        quantity=Decimal(3),
        order_type=OrderType.LIMIT,
        limit_price=Decimal(50),
        estimated_notional=Decimal(150),
    )
    await repos.orders.create(intent, created_at=NOW - timedelta(days=10))
    await repos.orders.apply_result(
        OrderResult(
            client_order_id=intent.client_order_id,
            status=OrderStatus.FILLED,
            filled_qty=Decimal(3),
            fills=[
                Fill(
                    exec_id=f"e-{symbol}",
                    client_order_id=intent.client_order_id,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    qty=Decimal(3),
                    price=Decimal(50),
                    ts=NOW - timedelta(days=10),
                )
            ],
        )
    )


def context(run_id: UUID, as_of: datetime = NOW) -> PipelineContext:
    return PipelineContext(
        run_id=run_id,
        pipeline_name=PIPELINE,
        mode=RunMode.DRY_RUN,
        universe=["AAPL", "MSFT"],
        as_of=as_of,
    )


async def test_end_to_end(repos: Repositories, store: ConfigStore, new_run: NewRun) -> None:
    await hold(repos, new_run, "XOM")
    deepseek, claude = FakeLLMClient(default=picks_reply), FakeLLMClient(default=picks_reply)
    stage, bars = build(repos, store, deepseek, anthropic=claude)
    run_id = await new_run()
    ctx = await stage.run(context(run_id))

    # candidates: universe, then static, then scanner; duplicates merged, order kept
    assert bars.calls == [["AAPL", "MSFT", "NVDA", "JPM", "GHOST", "PENNY", "AMD"]]
    selection = ctx.selection
    assert selection is not None
    # weights 1, 1, 0.5 (total 2.5): AAPL (0.9 + 0.9 + 0.3) / 2.5, NVDA 1.6 / 2.5
    assert selection.selected == ["AAPL", "NVDA"]
    assert selection.scores["AAPL"] == pytest.approx(0.84)
    assert selection.scores["NVDA"] == pytest.approx(0.64)
    assert selection.scores["JPM"] == pytest.approx(0.14)
    assert selection.holdings == ["XOM"]
    assert ctx.universe == ["AAPL", "NVDA", "XOM"]  # held XOM stays tradable
    assert selection.method == "weighted_score(top_n=2, min_score=0.0)"
    # most liquid first: NVDA trades 3x the volume
    assert selection.candidates[0] == "NVDA"
    assert set(selection.candidates) == {"AAPL", "MSFT", "NVDA", "JPM", "AMD"}
    assert selection.rejected["PENNY"].startswith("price 2.00")
    assert selection.rejected["GHOST"] == (
        "only 0 completed bars (< 60); data update failed: MarketDataError: unknown symbol"
    )
    assert selection.created_at == NOW

    # the model was chosen per agent reference
    assert len(deepseek.requests) == 2
    assert len(claude.requests) == 1
    assert {r.model for r in deepseek.requests} == {"deepseek-chat"}
    assert claude.requests[0].model == "claude-sonnet-5-5"
    prompt = claude.requests[0].messages[0].content
    assert "Pick AT MOST 5 stocks" in prompt
    assert "- [cand:NVDA] NVDA (from static, ibkr_scanner: offline)" in prompt
    assert "- [cand:AAPL] AAPL (from universe)" in prompt
    assert "PENNY" not in prompt
    assert "GHOST" not in prompt
    assert "## Current holdings of the strategy\nXOM" in prompt
    assert "None (first selection)." in prompt

    results = ctx.selection_results
    momentum = next(r for r in results if r.agent_id == "momentum_screener")
    assert [p.symbol for p in momentum.picks] == ["AAPL", "NVDA"]  # unknown TSLA dropped
    assert momentum.created_at == NOW
    assert momentum.error is None
    assert momentum.candidates == selection.candidates

    stored = await repos.selection.get_by_run(run_id)
    assert stored == selection
    assert len(await repos.selection.get_results_by_run(run_id)) == 3
    instances = await repos.runs.get_agent_instances(run_id)
    assert sorted(i.agent_id for i in instances) == [
        "defensive_screener",
        "momentum_screener",
        "momentum_screener",
    ]
    assert len(await repos.llm_calls.get_by_run(run_id)) == 3

    # the next selection sees this one; an earlier as_of does not
    later = FakeLLMClient(default=picks_reply)
    stage2, _ = build(repos, store, later)
    await stage2.run(context(await new_run(NOW + timedelta(days=7)), NOW + timedelta(days=7)))
    assert "2026-09-24: AAPL, NVDA" in later.requests[0].messages[0].content
    assert await repos.selection.get_latest(PIPELINE, as_of=NOW - timedelta(days=1)) is None
    latest = await repos.selection.get_latest(PIPELINE, as_of=NOW + timedelta(days=30))
    assert latest is not None
    assert latest.created_at == NOW + timedelta(days=7)


@pytest.mark.parametrize(
    ("fallback", "with_previous", "expected"),
    [
        ("previous", True, (["AAPL"], "fallback_previous")),
        ("previous", False, ([], "fallback_holdings")),
        ("holdings", True, ([], "fallback_holdings")),
    ],
)
async def test_every_agent_failed(
    repos: Repositories,
    store: ConfigStore,
    new_run: NewRun,
    fallback: str,
    with_previous: bool,
    expected: tuple[list[str], str],
) -> None:
    await hold(repos, new_run, "XOM")
    if with_previous:
        good = FakeLLMClient(default=picks_reply)
        stage, _ = build(repos, store, good, config=stage_config(aggregation={"top_n": 1}))
        await stage.run(context(await new_run(NOW - timedelta(days=7)), NOW - timedelta(days=7)))

    broken = FakeLLMClient(default="not json")
    stage, _ = build(repos, store, broken, config=stage_config(fallback=fallback))
    ctx = await stage.run(context(await new_run()))
    assert ctx.selection is not None
    assert (ctx.selection.selected, ctx.selection.method) == expected
    assert ctx.universe == [*expected[0], "XOM"]
    assert all(r.error is not None and r.picks == [] for r in ctx.selection_results)


async def test_fallback_fail(repos: Repositories, store: ConfigStore, new_run: NewRun) -> None:
    stage, _ = build(
        repos, store, FakeLLMClient(default="not json"), config=stage_config(fallback="fail")
    )
    with pytest.raises(SelectionError, match="every selection agent failed"):
        await stage.run(context(await new_run()))


async def test_partial_source_failure_and_total_failure(
    repos: Repositories, store: ConfigStore, new_run: NewRun
) -> None:
    llm = FakeLLMClient(default=picks_reply)
    broken = FakeCandidateSource("ibkr_scanner", fail=True)
    stage, bars = build(repos, store, llm, scanner=broken)
    ctx = await stage.run(context(await new_run()))
    assert "AMD" not in bars.calls[0]  # the scanner failed; the others still count
    assert ctx.selection is not None
    assert ctx.selection.selected == ["AAPL", "NVDA"]

    config = stage_config(include_universe=False, sources=[{"type": "ibkr_scanner"}])
    stage, _ = build(repos, store, llm, config=config, scanner=broken)
    with pytest.raises(CandidateSourceError, match="every candidate source failed"):
        await stage.run(context(await new_run()))


async def test_nothing_passes_the_screen(
    repos: Repositories, store: ConfigStore, new_run: NewRun
) -> None:
    await hold(repos, new_run, "XOM")
    llm = FakeLLMClient(default=picks_reply)
    config = stage_config(screen={"min_price": 10_000})
    stage, _ = build(repos, store, llm, config=config)
    ctx = await stage.run(context(await new_run()))
    assert llm.requests == []  # no candidates: the agents are not asked
    assert ctx.selection is not None
    assert (ctx.selection.selected, ctx.selection.candidates) == ([], [])
    assert ctx.universe == ["XOM"]


async def test_options(repos: Repositories, store: ConfigStore, new_run: NewRun) -> None:
    await hold(repos, new_run, "XOM")
    llm = FakeLLMClient(default=picks_reply)
    config = stage_config(keep_holdings=False, refresh_bars=False, max_raw_candidates=3, sources=[])
    for bars in BARS.values():
        await repos.bars.upsert(bars)
    stage, refresher = build(repos, store, llm, config=config, universe=["AAPL", "MSFT", "JPM"])
    ctx = await stage.run(context(await new_run()))
    assert refresher.calls == []  # bars already stored, no refresh requested
    assert ctx.universe == ["AAPL", "JPM"]  # XOM held but keep_holdings is off
    assert ctx.selection is not None
    assert ctx.selection.holdings == []

    capped = stage_config(max_raw_candidates=2)
    stage, refresher = build(repos, store, llm, config=capped)
    await stage.run(context(await new_run()))
    assert refresher.calls == [["AAPL", "MSFT"]]


async def test_stage_needs_agents(repos: Repositories, store: ConfigStore) -> None:
    with pytest.raises(SelectionError, match="at least one selection agent"):
        build(repos, store, FakeLLMClient(), config=stage_config(agents=[]))


async def test_wrong_agent_role_is_rejected(repos: Repositories, store: ConfigStore) -> None:
    config = stage_config(
        agents=[{"agent": "value_investor", "model": {"provider": "deepseek", "name": "x"}}]
    )
    with pytest.raises(Exception, match="expected selection"):
        build(repos, store, FakeLLMClient(), config=config)


async def test_scanner_from_registry_is_closed(repos: Repositories, store: ConfigStore) -> None:
    pool = LLMClientPool({}, env={})
    pool.set("deepseek", FakeLLMClient())
    pool.set("anthropic", FakeLLMClient())
    services = Services(
        repos=repos, config_store=store, llm=pool, pipeline=pipeline_config(["AAPL"])
    )
    stage = build_selection_stage(stage_config(), services)
    assert [s.name for s in stage.sources] == ["universe", "static", "ibkr_scanner"]
    await stage.aclose()  # never connected: nothing to do
