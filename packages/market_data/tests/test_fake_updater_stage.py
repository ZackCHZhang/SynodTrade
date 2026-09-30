import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from quant_core.config import AccountConfig, StageConfig
from quant_core.models import (
    AccountSnapshot,
    PipelineContext,
    Position,
    Quote,
    RunMode,
    Timeframe,
)
from quant_core.registry import STAGES
from quant_core.services import Services
from quant_database import Repositories
from quant_market_data import (
    AccountData,
    DataUpdateError,
    DataUpdater,
    DataUpdateStage,
    FakeMarketDataProvider,
    MarketDataError,
    build_data_update_stage,
    generate_daily_bars,
)

D = Decimal
NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)  # Thursday, during the session
START = date(2025, 9, 1)


def provider(**kw: object) -> FakeMarketDataProvider:
    bars = generate_daily_bars("AAPL", START, 280) + generate_daily_bars(
        "MSFT", START, 280, start_price=D(400)
    )
    return FakeMarketDataProvider(bars, **kw)  # type: ignore[arg-type]


def ctx(universe: list[str], as_of: datetime = NOW) -> PipelineContext:
    return PipelineContext(pipeline_name="p", mode=RunMode.DRY_RUN, universe=universe, as_of=as_of)


# ------------------------------------------------------------------ fake provider


def test_generated_bars_are_deterministic_weekday_and_valid() -> None:
    a = generate_daily_bars("AAPL", START, 30)
    assert a == generate_daily_bars("AAPL", START, 30)
    assert a != generate_daily_bars("MSFT", START, 30)
    assert len(a) == 30
    assert all(b.ts.astimezone(UTC).weekday() < 5 for b in a)
    assert all(b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high for b in a)
    assert all(b.close == b.close.quantize(D("0.01")) for b in a)
    assert generate_daily_bars("X", START, 3, seed=1) == generate_daily_bars("Y", START, 3, seed=1)[
        :0
    ] + [b.model_copy(update={"symbol": "X"}) for b in generate_daily_bars("Y", START, 3, seed=1)]


async def test_fake_provider_basics() -> None:
    fake = provider(fail_symbols=["NVDA"], healthy=False)
    await fake.connect()
    assert fake.connected
    assert not await fake.is_healthy()
    aapl = await fake.resolve_instrument("aapl")
    assert aapl.con_id is not None
    assert aapl == await fake.resolve_instrument("AAPL")
    with pytest.raises(MarketDataError, match="NVDA"):
        await fake.resolve_instrument("NVDA")
    quotes = await fake.fetch_quotes([aapl])
    assert quotes[0].last == generate_daily_bars("AAPL", START, 280)[-1].close
    account = await fake.fetch_account("DU1")
    assert account.account.nav == D(100_000)
    await fake.disconnect()
    assert ("fetch_quotes", "AAPL") in fake.calls


async def test_fake_provider_from_fixture_dir(tmp_path: Path) -> None:
    (tmp_path / "bars").mkdir()
    (tmp_path / "bars" / "SPY_1d.csv").write_text(
        "ts,open,high,low,close,volume\n"
        "2026-09-22T04:00:00+00:00,500,505,498,503,1000\n"
        "2026-09-23T04:00:00+00:00,503,510,501,509.5,1200\n",
        encoding="utf-8",
    )
    (tmp_path / "quotes.json").write_text(
        json.dumps([{"symbol": "SPY", "ts": "2026-09-24T14:00:00Z", "bid": "509", "ask": "509.2"}]),
        encoding="utf-8",
    )
    (tmp_path / "account.json").write_text(
        json.dumps(
            {
                "account": {
                    "account_id": "DU1",
                    "ts": "2026-09-24T14:00:00Z",
                    "nav": "1000",
                    "cash": "500",
                    "buying_power": "1000",
                },
                "positions": [
                    {
                        "account_id": "DU1",
                        "symbol": "SPY",
                        "qty": "1",
                        "avg_cost": "480",
                        "ts": "2026-09-24T14:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fake = FakeMarketDataProvider.from_fixture_dir(tmp_path)
    spy = await fake.resolve_instrument("SPY")
    bars = await fake.fetch_bars(spy, Timeframe.D1, NOW - timedelta(days=10), NOW)
    assert [b.close for b in bars] == [D(503), D("509.5")]
    assert (await fake.fetch_quotes([spy]))[0].mid == D("509.1")
    assert (await fake.fetch_account("DU1")).positions[0].qty == D(1)


# ------------------------------------------------------------------ updater


async def test_initial_update_then_incremental(repos: Repositories) -> None:
    fake = provider()
    updater = DataUpdater(fake, repos)
    report = await updater.update(
        ["AAPL", "msft"],
        timeframes=[Timeframe.D1],
        lookback=timedelta(days=365),
        now=NOW,
        account_id="DU1",
    )
    in_window = [
        b
        for b in generate_daily_bars("AAPL", START, 280)
        if NOW - timedelta(days=365) <= b.ts < NOW
    ]
    assert report.ok
    assert report.bars_written["AAPL/1d"] == len(in_window)
    assert report.quotes_written == 2
    assert report.positions_written == 0
    stored = await repos.bars.get_latest_bars("AAPL", 500, as_of=NOW)
    # today's bar (ts = today 00:00 New York) is still forming, so it is hidden until complete
    assert in_window[-1].ts.date() == NOW.date()
    assert stored == in_window[:-1]
    assert (await repos.instruments.get("MSFT")) is not None
    assert await repos.accounts.get_latest_account("DU1") is not None

    fake.calls.clear()
    again = await updater.update(
        ["AAPL"],
        timeframes=[Timeframe.D1],
        lookback=timedelta(days=365),
        now=NOW + timedelta(hours=1),
    )
    assert again.bars_written["AAPL/1d"] == 1  # only the last (possibly partial) bar re-fetched
    assert ("resolve_instrument", "AAPL") not in fake.calls  # con_id cached in the database


async def test_one_failing_symbol_does_not_stop_the_rest(repos: Repositories) -> None:
    updater = DataUpdater(provider(fail_symbols=["NVDA"]), repos)
    report = await updater.update(
        ["NVDA", "AAPL"], timeframes=[Timeframe.D1], lookback=timedelta(days=30), now=NOW
    )
    assert not report.ok
    assert "NVDA" in report.errors
    assert report.bars_written["AAPL/1d"] > 0
    assert report.positions_written is None


async def test_refresh_bars_for_selection(repos: Repositories) -> None:
    """Bars only (no quotes/account), for any symbols; implements core's BarsRefresher."""
    from quant_core.interfaces import BarsRefresher

    fake = provider(fail_symbols=["MSFT"])
    updater = DataUpdater(fake, repos)
    assert isinstance(updater, BarsRefresher)
    errors = await updater.refresh_bars(
        ["AAPL", "MSFT", "NOPE"], timeframe=Timeframe.D1, lookback=timedelta(days=400), now=NOW
    )
    assert fake.connected
    assert set(errors) == {"MSFT"}  # NOPE: no error, just no bars (the screen rejects it)
    assert await repos.bars.get_latest_bars("NOPE", 5, as_of=NOW) == []
    assert errors["MSFT"].startswith("MarketDataError")
    assert len(await repos.bars.get_latest_bars("AAPL", 500, as_of=NOW)) > 200
    assert not [c for c in fake.calls if c[0] in ("fetch_quotes", "fetch_account")]


async def test_quote_and_account_errors_are_reported(
    repos: Repositories, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = provider(fail_symbols=["DU1"])

    async def broken_quotes(*_: object) -> list[Quote]:
        raise MarketDataError("no market data permissions")

    monkeypatch.setattr(fake, "fetch_quotes", broken_quotes)
    report = await DataUpdater(fake, repos).update(
        ["AAPL"],
        timeframes=[Timeframe.D1],
        lookback=timedelta(days=5),
        now=NOW,
        account_id="DU1",
    )
    assert set(report.errors) == {"quotes", "account"}


async def test_account_snapshot_with_positions(repos: Repositories) -> None:
    snap = AccountSnapshot(account_id="DU1", ts=NOW, nav=D(10), cash=D(5), buying_power=D(5))
    pos = Position(account_id="DU1", symbol="AAPL", qty=D(2), avg_cost=D(1), ts=NOW)
    fake = provider(account=AccountData(snap, [pos]))
    report = await DataUpdater(fake, repos).update(
        [], timeframes=[Timeframe.D1], lookback=timedelta(days=5), now=NOW, account_id="DU1"
    )
    assert report.positions_written == 1
    assert await repos.accounts.get_latest_positions("DU1", as_of=NOW) == [pos]


# ------------------------------------------------------------------ stage


async def test_stage_runs_and_returns_context(repos: Repositories) -> None:
    config = StageConfig.model_validate(
        {"type": "data_update", "timeframes": ["1d"], "lookback_days": 60}
    )
    services = Services(
        repos=repos,
        market_data=provider(),
        account=AccountConfig(name="ibkr_main", account_id="DU1", port=4002, client_id=1),
    )
    stage = build_data_update_stage(config, services)
    assert stage.name == "data_update"
    assert stage.options.lookback_days == 60
    context = ctx(["AAPL"])
    assert await stage.run(context) is context
    assert services.get("market_data", FakeMarketDataProvider).connected
    assert await repos.accounts.get_latest_account("DU1") is not None


async def test_stage_fails_on_errors_by_default(repos: Repositories) -> None:
    services = Services(repos=repos, market_data=provider(fail_symbols=["NVDA"]))
    stage = build_data_update_stage(StageConfig(type="data_update"), services)
    with pytest.raises(DataUpdateError, match="NVDA"):
        await stage.run(ctx(["AAPL", "NVDA"]))

    lenient = build_data_update_stage(
        StageConfig.model_validate(
            {"type": "data_update", "fail_on_error": False, "account": False}
        ),
        services,
    )
    assert isinstance(lenient, DataUpdateStage)
    await lenient.run(ctx(["AAPL", "NVDA"]))


def test_stage_is_registered_as_entry_point() -> None:
    assert STAGES.get("data_update") is build_data_update_stage
