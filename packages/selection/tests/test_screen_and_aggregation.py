"""Pre-screen, pick validation and aggregation (pure functions)."""

from collections.abc import Callable
from uuid import uuid4

import pytest
from pydantic import ValidationError

from synodtrade_core.indicators import compute_indicators
from synodtrade_core.models import Bar, Candidate, SelectionPick, SelectionResult
from synodtrade_selection import (
    CandidateProfile,
    PickOutput,
    ScreenOptions,
    SelectionAgent,
    SelectionAggregation,
    SelectionMethod,
    aggregate_selection,
    avg_dollar_volume,
    candidate_inputs,
    screen,
)

MakeBars = Callable[..., list[Bar]]


def profile(
    make_bars: MakeBars, symbol: str, closes: list[float], volume: int = 1_000_000
) -> CandidateProfile:
    bars = make_bars(symbol, closes, volume=volume)
    return CandidateProfile(
        symbol=symbol,
        candidates=[Candidate(symbol=symbol, source="static", rank=0)],
        indicators=compute_indicators(bars),
        avg_dollar_volume=avg_dollar_volume(bars),
    )


def test_avg_dollar_volume(make_bars: MakeBars) -> None:
    bars = make_bars("AAPL", [10.0] * 30 + [20.0] * 10, volume=100)
    # last 20 bars: 10 x 10*100 + 10 x 20*100
    assert avg_dollar_volume(bars) == pytest.approx(1500.0)
    assert avg_dollar_volume([]) is None


def test_screen_filters_and_orders_by_liquidity(make_bars: MakeBars) -> None:
    profiles = [
        profile(make_bars, "SHORT", [50.0] * 10),
        profile(make_bars, "PENNY", [2.0] * 100),
        profile(make_bars, "THIN", [50.0] * 100, volume=1000),
        profile(make_bars, "WILD", [50.0 if i % 2 else 80.0 for i in range(100)]),
        profile(make_bars, "BIG", [100.0] * 100, volume=5_000_000),
        profile(make_bars, "MID", [50.0] * 100),
        profile(make_bars, "SMALL", [20.0] * 100),
    ]
    kept, rejected = screen(profiles, ScreenOptions(max_volatility=1.0, max_candidates=2))
    assert [p.symbol for p in kept] == ["BIG", "MID"]  # most liquid first, capped at 2
    assert rejected["SHORT"].startswith("only 10 completed bars")
    assert rejected["PENNY"].startswith("price 2.00 < 5")
    assert rejected["THIN"].startswith("avg dollar volume 50,000 < 5,000,000")
    assert rejected["WILD"].startswith("volatility")
    assert rejected["SMALL"] == "beyond max_candidates (2)"


def test_screen_max_price_and_disabled_filters(make_bars: MakeBars) -> None:
    profiles = [profile(make_bars, "PRICY", [900.0] * 80), profile(make_bars, "OK", [9.0] * 80)]
    kept, rejected = screen(profiles, ScreenOptions(max_price=500, min_avg_dollar_volume=None))
    assert [p.symbol for p in kept] == ["OK"]
    assert rejected == {"PRICY": "price 900.00 > 500"}
    no_adv = CandidateProfile(
        symbol="X", candidates=[], indicators=profiles[1].indicators, avg_dollar_volume=None
    )
    assert screen([no_adv], ScreenOptions())[1]["X"].startswith("avg dollar volume n/a")


def test_candidate_inputs_are_preformatted(make_bars: MakeBars) -> None:
    p = profile(make_bars, "AAPL", [100.0 + i for i in range(300)], volume=2_000_000)
    p.held = True
    p.candidates.append(Candidate(symbol="AAPL", source="ibkr_scanner", note="MOST_ACTIVE #3"))
    inputs = candidate_inputs(p)
    assert inputs["id"] == "cand:AAPL"
    assert inputs["held"] is True
    assert inputs["sources"] == "static, ibkr_scanner"
    assert inputs["notes"] == "MOST_ACTIVE #3"
    assert inputs["last_close"] == "399.00"
    assert inputs["avg_dollar_volume"] == "$779.0M"
    assert inputs["return_20d"].startswith("+")
    empty = CandidateProfile(
        symbol="NEW", candidates=[], indicators=compute_indicators([]), avg_dollar_volume=512
    )
    shown = candidate_inputs(empty)
    assert (shown["last_close"], shown["rsi_14"], shown["return_20d"]) == ("n/a", "n/a", "n/a")
    assert shown["avg_dollar_volume"] == "$512"
    assert (
        candidate_inputs(profile(make_bars, "K", [10.0] * 30, volume=200))["avg_dollar_volume"]
        == "$2.0K"
    )


def test_pick_validation() -> None:
    raw = [
        PickOutput(symbol="msft", score=0.4, reason="b"),
        PickOutput(symbol="cand:AAPL", score=0.9, reason="a"),
        PickOutput(symbol="TSLA", score=1.0, reason="not a candidate"),
        PickOutput(symbol="MSFT", score=1.0, reason="duplicate"),
        PickOutput(symbol="NVDA", score=0.4, reason="c"),
    ]
    picks, unknown = SelectionAgent._valid_picks(raw, {"AAPL", "MSFT", "NVDA"}, max_picks=2)
    assert [(p.symbol, p.score) for p in picks] == [("AAPL", 0.9), ("MSFT", 0.4)]
    assert unknown == ["TSLA"]
    with pytest.raises(ValidationError):
        PickOutput(symbol="AAPL", score=1.5, reason="x")


def result(picks: dict[str, float], error: str | None = None) -> SelectionResult:
    return SelectionResult(
        run_id=uuid4(),
        pipeline_name="p",
        instance_id=uuid4(),
        agent_id="a",
        prompt_version="v1",
        picks=[SelectionPick(symbol=s, score=v, reason="r") for s, v in picks.items()],
        error=error,
    )


CANDIDATES = ["AAPL", "MSFT", "NVDA", "JPM"]


def test_weighted_score() -> None:
    votes = [
        (result({"AAPL": 0.9, "MSFT": 0.5}), 1.0),
        (result({"MSFT": 0.8, "NVDA": 0.6}), 1.0),
        (result({}, error="timeout"), 5.0),  # failed agents do not vote
    ]
    selected, scores = aggregate_selection(votes, CANDIDATES, SelectionAggregation(top_n=2))
    assert scores == {"AAPL": 0.45, "MSFT": 0.65, "NVDA": 0.3, "JPM": 0.0}
    assert selected == ["MSFT", "AAPL"]


def test_approval_and_min_score() -> None:
    votes = [
        (result({"AAPL": 0.9, "MSFT": 0.2}), 2.0),
        (result({"MSFT": 0.3, "NVDA": 0.9}), 1.0),
    ]
    options = SelectionAggregation(method=SelectionMethod.APPROVAL, top_n=5, min_score=0.5)
    selected, scores = aggregate_selection(votes, CANDIDATES, options)
    assert scores["MSFT"] == 1.0
    assert scores["AAPL"] == pytest.approx(2 / 3, abs=1e-6)
    assert scores["NVDA"] == pytest.approx(1 / 3, abs=1e-6)
    assert selected == ["MSFT", "AAPL"]  # NVDA below min_score, JPM never picked
    assert options.describe() == "approval(top_n=5, min_score=0.5)"


def test_ties_break_on_the_other_measure_then_symbol() -> None:
    votes = [(result({"NVDA": 0.5, "AAPL": 0.5}), 1.0), (result({"NVDA": 0.0}), 1.0)]
    selected, _ = aggregate_selection(votes, CANDIDATES, SelectionAggregation())
    # both score 0.25; NVDA was picked by more agents
    assert selected == ["NVDA", "AAPL"]
    votes = [(result({"MSFT": 0.5, "AAPL": 0.5}), 1.0)]
    assert aggregate_selection(votes, CANDIDATES, SelectionAggregation())[0] == ["AAPL", "MSFT"]


def test_no_answers_selects_nothing() -> None:
    selected, scores = aggregate_selection(
        [(result({}, error="x"), 1.0)], CANDIDATES, SelectionAggregation()
    )
    assert selected == []
    assert set(scores.values()) == {0.0}
