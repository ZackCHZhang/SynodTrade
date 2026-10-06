"""The orchestrator: every indicator runs, nothing raises, missing fields are explained."""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from structlog.testing import capture_logs

from quant_core.indicators import (
    FIELDS,
    INDICATORS,
    BarSeries,
    Indicator,
    TechnicalSnapshot,
    WarningReason,
    compute_indicators,
    indicator_rows,
    unavailable_notes,
)
from quant_core.indicators import snapshot as snapshot_module
from quant_core.models import Bar, Timeframe

INDICATOR_FIELDS = {f for ind in INDICATORS for f in ind.fields}


def random_walk(n: int, seed: int = 7) -> list[Bar]:
    rng = random.Random(seed)
    start = datetime(2025, 1, 1, 5, 0, tzinfo=UTC)
    close, bars = 100.0, []
    for i in range(n):
        open_ = close * (1 + rng.gauss(0, 0.005))
        close = open_ * (1 + rng.gauss(0, 0.015))
        high = max(open_, close) * (1 + abs(rng.gauss(0, 0.005)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, 0.005)))
        bars.append(
            Bar(
                symbol="TEST",
                timeframe=Timeframe.D1,
                ts=start + timedelta(days=i),
                open=Decimal(f"{open_:.4f}"),
                high=Decimal(f"{high:.4f}"),
                low=Decimal(f"{low:.4f}"),
                close=Decimal(f"{close:.4f}"),
                volume=Decimal(rng.randint(500_000, 2_000_000)),
            )
        )
    return bars


def test_every_snapshot_field_has_an_indicator_and_a_label() -> None:
    snapshot_fields = set(TechnicalSnapshot.model_fields) - {
        "bars_used", "last_bar_ts", "last_close", "warnings"
    }  # fmt: skip
    assert snapshot_fields == INDICATOR_FIELDS
    assert set(FIELDS) == INDICATOR_FIELDS | {"last_close"}
    names = [ind.name for ind in INDICATORS]
    assert len(names) == len(set(names))


def test_full_history_computes_everything() -> None:
    with capture_logs() as logs:
        snap = compute_indicators(random_walk(300))
    assert snap.warnings == ()
    assert logs == []
    assert all(getattr(snap, f) is not None for f in INDICATOR_FIELDS)
    assert snap.bars_used == 300
    assert len(indicator_rows(snap)) == len(FIELDS)


def test_no_bars_warns_instead_of_raising() -> None:
    with capture_logs() as logs:
        snap = compute_indicators([])
    assert snap.bars_used == 0
    assert all(getattr(snap, f) is None for f in INDICATOR_FIELDS)
    missing = {f for w in snap.warnings for f in w.fields}
    assert missing == INDICATOR_FIELDS
    assert {w.reason for w in snap.warnings} == {WarningReason.INSUFFICIENT_DATA}
    [event] = logs
    assert event["event"] == "indicators.unavailable"
    assert event["log_level"] == "warning"


def test_short_history_lists_exactly_what_is_missing() -> None:
    with capture_logs() as logs:
        snap = compute_indicators(random_walk(60))
    assert snap.atr_14 is not None
    assert snap.adx_14 is not None
    assert snap.sma_200 is None
    by_field = {f: w for w in snap.warnings for f in w.fields}
    assert by_field["sma_200"].needed_bars == 200
    assert by_field["sma_200"].available_bars == 60
    assert by_field["return_60d"].needed_bars == 61
    assert by_field["return_250d"].needed_bars == 251
    assert by_field["gap_freq_2atr_60d"].needed_bars == 75
    assert "sma_20" not in by_field
    assert "sma_200, price_vs_sma_200: needs 200 completed bars, only 60 available" in " ".join(
        unavailable_notes(snap)
    )
    [event] = logs
    assert event["symbol"] == "TEST"
    assert event["bars"] == 60


def test_warn_false_does_not_log() -> None:
    with capture_logs() as logs:
        snap = compute_indicators(random_walk(30), warn=False)
    assert snap.warnings  # still reported on the snapshot
    assert logs == []


def test_degenerate_data_is_reported_not_raised() -> None:
    bars = [
        Bar(
            symbol="FLAT",
            timeframe=Timeframe.D1,
            ts=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=i),
            open=Decimal(10),
            high=Decimal(10),
            low=Decimal(10),
            close=Decimal(10),
            volume=Decimal(0),
        )
        for i in range(300)
    ]
    snap = compute_indicators(bars, warn=False)
    degenerate = {
        f for w in snap.warnings if w.reason is WarningReason.DEGENERATE_DATA for f in w.fields
    }
    assert {"zscore_20", "adx_14", "vwap_20d", "volume_ratio_20d", "amihud_illiquidity_20d"} <= (
        degenerate
    )
    assert snap.atr_14 == 0.0  # well defined: no range at all
    assert snap.return_1d == 0.0


def test_a_failing_indicator_does_not_stop_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_: BarSeries) -> dict[str, float | None]:
        raise ZeroDivisionError("division by zero")

    broken = Indicator(name="broken", fields={"atr_14": 1}, compute=boom)
    others = tuple(i for i in INDICATORS if i.name != "atr")
    monkeypatch.setattr(snapshot_module, "INDICATORS", (broken, *others))
    snap = compute_indicators(random_walk(300), warn=False)
    assert snap.atr_14 is None
    assert snap.rsi_14 is not None
    [warning] = snap.warnings
    assert warning.reason is WarningReason.ERROR
    assert warning.indicator == "broken"
    assert "ZeroDivisionError" in warning.message()
