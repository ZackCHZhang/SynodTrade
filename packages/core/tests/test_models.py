from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from quant_core.models import (
    Action,
    Bar,
    Instrument,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    PipelineContext,
    Quote,
    RiskVerdict,
    RunMode,
    SentimentResult,
    StageError,
    Timeframe,
    Verdict,
)
from quant_core.timeutil import DISPLAY_TZ, EXCHANGE_TZ, to_utc, utcnow

D = Decimal
TS = datetime(2026, 9, 24, 13, 30, tzinfo=UTC)


def test_utcnow_is_aware() -> None:
    assert utcnow().tzinfo is UTC


def test_to_utc_rejects_naive() -> None:
    with pytest.raises(ValueError, match="naive"):
        to_utc(datetime(2026, 1, 1))  # noqa: DTZ001 - deliberately naive


def test_timezones() -> None:
    assert str(EXCHANGE_TZ) == "America/New_York"
    assert str(DISPLAY_TZ) == "Europe/Berlin"


def test_datetimes_are_normalised_to_utc() -> None:
    ny = datetime(2026, 9, 24, 9, 30, tzinfo=EXCHANGE_TZ)
    bar = Bar(
        symbol="aapl",
        timeframe=Timeframe.D1,
        ts=ny,
        open=D(1),
        high=D(2),
        low=D("0.5"),
        close=D("1.5"),
        volume=D(100),
    )
    assert bar.ts.tzinfo == UTC
    assert bar.ts == TS
    assert bar.symbol == "AAPL"


def test_naive_datetime_rejected_in_models() -> None:
    with pytest.raises(ValidationError):
        Quote(symbol="AAPL", ts=datetime(2026, 1, 1), bid=D(1), ask=D(2))  # noqa: DTZ001


def test_bar_ohlc_consistency() -> None:
    with pytest.raises(ValidationError, match="inconsistent OHLC"):
        Bar(
            symbol="X",
            timeframe=Timeframe.D1,
            ts=TS,
            open=D(10),
            high=D(9),
            low=D(8),
            close=D(9),
            volume=D(0),
        )


def test_models_are_frozen_and_strict() -> None:
    inst = Instrument(symbol="msft")
    with pytest.raises(ValidationError):
        inst.symbol = "X"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Instrument(symbol="X", unknown_field=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Instrument(symbol="  ")


def test_quote_derived_prices() -> None:
    q = Quote(symbol="X", ts=TS, bid=D("99.95"), ask=D("100.05"), last=D(100))
    assert q.mid == D(100)
    assert q.spread_bps == D(10)
    assert q.reference_price == D(100)

    last_only = Quote(symbol="X", ts=TS, last=D(42))
    assert last_only.mid is None
    assert last_only.spread_bps is None
    assert last_only.reference_price == D(42)

    with pytest.raises(ValidationError, match="crossed"):
        Quote(symbol="X", ts=TS, bid=D(101), ask=D(100))


def test_decimal_money_is_exact() -> None:
    q = Quote(symbol="X", ts=TS, bid=D("0.1"), ask=D("0.2"))
    assert q.mid == D("0.15")
    assert isinstance(q.bid, Decimal)


def test_confidence_and_sentiment_bounds() -> None:
    common = {
        "run_id": uuid4(),
        "instance_id": uuid4(),
        "agent_id": "retail_mood",
        "prompt_version": "v1",
        "symbol": "AAPL",
        "summary": "s",
    }
    SentimentResult(**common, sentiment=-1.0, confidence=1.0)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        SentimentResult(**common, sentiment=1.5, confidence=0.5)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        SentimentResult(**common, sentiment=0.0, confidence=1.2)  # type: ignore[arg-type]


# ------------------------------------------------------------------ RiskVerdict


def _verdict(verdict: Verdict, original: Action, adjusted: Action) -> RiskVerdict:
    return RiskVerdict(
        run_id=uuid4(),
        symbol="AAPL",
        source="rules",
        verdict=verdict,
        original_action=original,
        adjusted_action=adjusted,
        reason="test",
    )


def test_risk_verdict_valid_combinations() -> None:
    _verdict(Verdict.APPROVE, Action.BUY, Action.BUY)
    _verdict(Verdict.REDUCE, Action.STRONG_BUY, Action.BUY)
    _verdict(Verdict.REDUCE, Action.STRONG_SELL, Action.SELL)
    _verdict(Verdict.REDUCE, Action.BUY, Action.HOLD)
    _verdict(Verdict.REJECT, Action.STRONG_SELL, Action.HOLD)
    _verdict(Verdict.APPROVE, Action.HOLD, Action.HOLD)


@pytest.mark.parametrize(
    ("verdict", "original", "adjusted", "message"),
    [
        (Verdict.REDUCE, Action.BUY, Action.STRONG_BUY, "may not change"),  # enlarging
        (Verdict.REDUCE, Action.BUY, Action.SELL, "may not change"),  # reversing
        (Verdict.REDUCE, Action.HOLD, Action.BUY, "may not change"),  # creating a trade
        (Verdict.APPROVE, Action.BUY, Action.HOLD, "approve must keep"),
        (Verdict.REJECT, Action.STRONG_BUY, Action.BUY, "reject must set"),
        (Verdict.REDUCE, Action.BUY, Action.BUY, "reduce must change"),
    ],
)
def test_risk_verdict_cannot_increase_risk(
    verdict: Verdict, original: Action, adjusted: Action, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _verdict(verdict, original, adjusted)


# ------------------------------------------------------------------ orders


def _intent(**kw: object) -> OrderIntent:
    args: dict[str, object] = {
        "client_order_id": "abc",
        "run_id": uuid4(),
        "pipeline_name": "p",
        "symbol": "AAPL",
        "action": Action.BUY,
        "side": OrderSide.BUY,
        "quantity": D(10),
        "order_type": OrderType.LIMIT,
        "limit_price": D("100.05"),
        "estimated_notional": D("1000.5"),
    }
    args.update(kw)
    return OrderIntent(**args)  # type: ignore[arg-type]


def test_order_intent_valid() -> None:
    assert _intent().side is OrderSide.BUY
    market = _intent(
        action=Action.SELL, side=OrderSide.SELL, order_type=OrderType.MARKET, limit_price=None
    )
    assert market.limit_price is None


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"action": Action.HOLD}, "hold does not produce"),
        ({"side": OrderSide.SELL}, "must be a buy order"),
        ({"limit_price": None}, "limit_price is required"),
        ({"order_type": OrderType.MARKET}, "limit_price is required"),
        ({"quantity": D(0)}, "greater than 0"),
    ],
)
def test_order_intent_invalid(kw: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _intent(**kw)


def test_order_status_terminal() -> None:
    assert OrderStatus.FILLED.is_terminal
    assert OrderStatus.DRY_RUN.is_terminal
    assert not OrderStatus.SUBMITTED.is_terminal
    assert not OrderStatus.PARTIALLY_FILLED.is_terminal


# ------------------------------------------------------------------ context


def test_pipeline_context_defaults_and_abort_flag() -> None:
    ctx = PipelineContext(pipeline_name="p", mode=RunMode.DRY_RUN, universe=["AAPL"])
    assert ctx.run_id is not None
    assert ctx.as_of.tzinfo == UTC
    assert not ctx.aborted

    ctx.errors.append(StageError(stage="sentiment", error_type="X", message="m", skipped=True))
    assert not ctx.aborted
    ctx.errors.append(StageError(stage="decision", error_type="X", message="m", skipped=False))
    assert ctx.aborted


def test_pipeline_context_validates_assignment() -> None:
    ctx = PipelineContext(pipeline_name="p", mode=RunMode.PAPER, universe=[])
    other_tz = timezone(timedelta(hours=2))
    ctx.as_of = datetime(2026, 1, 1, 12, tzinfo=other_tz)
    assert ctx.as_of.hour == 10
    assert ctx.as_of.tzinfo == UTC
