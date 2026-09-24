import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from quant_core.config import ConfigStore, LLMModelConfig
from quant_core.llm import FakeLLMClient, LLMError
from quant_core.models import Action, RiskVerdict, Verdict
from quant_risk import (
    AlwaysOpenClock,
    CombineMethod,
    ExchangeCalendarClock,
    RiskAgent,
    bounded_output,
    combine,
    trading_day_start,
    trading_week_start,
)

A = Action
Inputs = Callable[..., dict[str, Any]]
MODEL = LLMModelConfig(provider="anthropic", name="claude-opus-5")


def reply(verdict: str, adjusted: str, reason: str = "because") -> str:
    return json.dumps({"verdict": verdict, "adjusted_action": adjusted, "reason": reason})


def agent(store: ConfigStore, llm: FakeLLMClient, on_failure: str = "reject") -> RiskAgent:
    a = RiskAgent(
        store.agent("conservative_risk_officer"), llm, model=MODEL, prompt_root=store.agents_dir
    )
    a.on_failure = on_failure  # type: ignore[assignment]
    return a


async def review(a: RiskAgent, inputs: dict[str, Any], proposed: Action = A.BUY) -> RiskVerdict:
    return await a.review(
        inputs, proposed=proposed, symbol="AAPL", run_id=uuid4(), decision_id=uuid4()
    )


# ------------------------------------------------------------------ bounded output


@pytest.mark.parametrize(
    ("proposed", "verdict", "adjusted", "ok"),
    [
        (A.STRONG_BUY, "approve", "strong_buy", True),
        (A.STRONG_BUY, "reduce", "buy", True),
        (A.STRONG_BUY, "reduce", "hold", True),
        (A.BUY, "approve", "strong_buy", False),  # enlarging
        (A.BUY, "reduce", "sell", False),  # reversing
        (A.SELL, "reduce", "strong_sell", False),
        (A.BUY, "reject", "strong_buy", True),  # reject always means HOLD
    ],
)
def test_bounded_output(proposed: Action, verdict: str, adjusted: str, ok: bool) -> None:
    model = bounded_output(proposed)
    raw = reply(verdict, adjusted)
    if ok:
        out = model.model_validate_json(raw)
        assert out.effective() is (A.HOLD if verdict == "reject" else A(adjusted))
    else:
        with pytest.raises(ValidationError, match="never enlarge"):
            model.model_validate_json(raw)


# ------------------------------------------------------------------ agent


async def test_review_reduce(store: ConfigStore, risk_inputs: Inputs) -> None:
    llm = FakeLLMClient([reply("reduce", "buy", "volatility is high")])
    verdict = await review(agent(store, llm), risk_inputs(), proposed=A.STRONG_BUY)
    assert (verdict.verdict, verdict.adjusted_action) == (Verdict.REDUCE, A.BUY)
    assert verdict.original_action is A.STRONG_BUY
    assert verdict.source == "conservative_risk_officer"
    assert verdict.instance_id is not None
    assert verdict.reason == "volatility is high"
    prompt = llm.requests[0].messages[0].content
    assert 'the proposed action is "strong_buy"' in prompt
    assert "never enlarge" in prompt
    assert "clean uptrend" in prompt
    assert "order value 3000.00 > limit 2000" in prompt


async def test_attempt_to_increase_is_repaired(store: ConfigStore, risk_inputs: Inputs) -> None:
    llm = FakeLLMClient([reply("approve", "strong_buy"), reply("approve", "buy")])
    verdict = await review(agent(store, llm), risk_inputs(), proposed=A.BUY)
    assert verdict.adjusted_action is A.BUY
    assert len(llm.requests) == 2
    assert "never enlarge" in llm.requests[1].messages[-1].content  # the repair message
    assert len(verdict.llm_call_ids) == 2


async def test_reject_verdict_means_hold(store: ConfigStore, risk_inputs: Inputs) -> None:
    llm = FakeLLMClient([reply("reject", "buy", "hype")])
    verdict = await review(agent(store, llm), risk_inputs())
    assert (verdict.verdict, verdict.adjusted_action) == (Verdict.REJECT, A.HOLD)


@pytest.mark.parametrize(
    ("script", "on_failure", "expected"),
    [
        ([reply("approve", "strong_sell")] * 3, "reject", A.HOLD),  # never valid -> fallback
        ([LLMError("HTTP 401")], "reject", A.HOLD),
        ([LLMError("HTTP 401")], "approve", A.BUY),
    ],
)
async def test_failure_policy(
    store: ConfigStore, risk_inputs: Inputs, script: list[Any], on_failure: str, expected: Action
) -> None:
    verdict = await review(agent(store, FakeLLMClient(script), on_failure), risk_inputs())
    assert verdict.adjusted_action is expected
    assert "risk agent unavailable" in verdict.reason


async def test_prompt_without_order_or_hits(store: ConfigStore, risk_inputs: Inputs) -> None:
    llm = FakeLLMClient([reply("approve", "sell")])
    inputs = risk_inputs(
        order=None,
        rule_hits=[],
        decisions=[],
        sentiment=[{"agent": "retail_mood", "sentiment": "-0.30", "summary": "gloom"}],
    )
    await review(agent(store, llm), inputs, proposed=A.SELL)
    prompt = llm.requests[0].messages[0].content
    assert "No order would result" in prompt
    assert "all rules passed" in prompt
    assert "gloom" in prompt


# ------------------------------------------------------------------ combine


def verdict(adjusted: Action, proposed: Action = A.STRONG_BUY) -> RiskVerdict:
    from quant_risk import verdict_between

    return RiskVerdict(
        run_id=uuid4(),
        symbol="AAPL",
        source="x",
        verdict=verdict_between(proposed, adjusted),
        original_action=proposed,
        adjusted_action=adjusted,
        reason="r",
    )


def test_combine() -> None:
    three = [verdict(A.STRONG_BUY), verdict(A.BUY), verdict(A.HOLD)]
    assert combine(A.STRONG_BUY, three, CombineMethod.MOST_CONSERVATIVE) is A.HOLD
    assert combine(A.STRONG_BUY, three, CombineMethod.MEDIAN) is A.BUY
    two = [verdict(A.STRONG_BUY), verdict(A.BUY)]
    assert combine(A.STRONG_BUY, two, CombineMethod.MEDIAN) is A.BUY  # lower median
    assert combine(A.SELL, [], CombineMethod.MOST_CONSERVATIVE) is A.SELL


# ------------------------------------------------------------------ clock


def test_trading_day_and_week_start() -> None:
    summer = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)  # Thursday, EDT (UTC-4)
    assert trading_day_start(summer) == datetime(2026, 9, 24, 4, 0, tzinfo=UTC)
    assert trading_week_start(summer) == datetime(2026, 9, 21, 4, 0, tzinfo=UTC)
    winter = datetime(2026, 12, 2, 3, 0, tzinfo=UTC)  # still Tuesday Dec 1 in New York (EST)
    assert trading_day_start(winter) == datetime(2026, 12, 1, 5, 0, tzinfo=UTC)
    assert trading_week_start(winter) == datetime(2026, 11, 30, 5, 0, tzinfo=UTC)


def test_exchange_calendar_clock() -> None:
    clock = ExchangeCalendarClock("XNYS")
    assert clock.is_open(datetime(2026, 9, 24, 14, 0, tzinfo=UTC))  # Thursday 10:00 NY
    assert not clock.is_open(datetime(2026, 9, 24, 21, 0, tzinfo=UTC))  # after the close
    assert not clock.is_open(datetime(2026, 9, 26, 15, 0, tzinfo=UTC))  # Saturday
    assert not clock.is_open(datetime(2026, 11, 26, 15, 0, tzinfo=UTC))  # Thanksgiving
    assert AlwaysOpenClock().is_open(datetime(2026, 9, 26, 15, 0, tzinfo=UTC))
