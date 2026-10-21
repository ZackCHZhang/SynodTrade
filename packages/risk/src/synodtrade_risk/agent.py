"""Layer 2: risk agents (LLM). They review what the hard rules let through and may only
keep it, move it toward HOLD, or reject it.

"Only reduce risk" is enforced in code, not left to the prompt: every call validates the
reply against an output model bound to that call's proposed action, so an enlarged or
reversed action is a validation error (repair-retried, then the failure fallback). The
resulting `RiskVerdict` enforces the same invariant once more.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from synodtrade_core.agent import Agent
from synodtrade_core.models import Action, RiskVerdict, Verdict
from synodtrade_core.timeutil import utcnow
from synodtrade_risk.rules import verdict_between


class RiskAgentOutput(BaseModel):
    verdict: Verdict = Field(description="approve, reduce or reject the proposed action")
    adjusted_action: Action = Field(
        description="The action to execute: the proposed one (approve), a tier closer to "
        "hold (reduce), or hold (reject)"
    )
    reason: str = Field(max_length=1500, description="Concise justification")

    def effective(self) -> Action:
        return Action.HOLD if self.verdict is Verdict.REJECT else self.adjusted_action


def bounded_output(proposed: Action) -> type[RiskAgentOutput]:
    """An output model that rejects any adjustment which is not a reduction of `proposed`."""

    class RiskReview(RiskAgentOutput):
        @model_validator(mode="after")
        def _only_reduce(self) -> Self:
            if self.verdict is not Verdict.REJECT and not self.adjusted_action.is_reduction_of(
                proposed
            ):
                raise ValueError(
                    f"adjusted_action {self.adjusted_action.value!r} is not allowed: from the "
                    f"proposed {proposed.value!r} you may only keep it, move it toward 'hold', "
                    "or choose 'hold' (never enlarge it or reverse its direction)"
                )
            return self

    return RiskReview


class CombineMethod(StrEnum):
    MOST_CONSERVATIVE = "most_conservative"  # smallest position change wins
    MEDIAN = "median"  # lower median of the agents' actions (conservative on ties)


def combine(proposed: Action, verdicts: list[RiskVerdict], method: CombineMethod) -> Action:
    if not verdicts:
        return proposed
    actions = sorted((v.adjusted_action for v in verdicts), key=lambda a: abs(a.weight))
    if method is CombineMethod.MOST_CONSERVATIVE:
        return actions[0]
    return actions[(len(actions) - 1) // 2]


class RiskAgent(Agent[RiskAgentOutput]):
    """Risk officer. Like other agents, its LLM is chosen at instantiation (`model=...` or
    the pipeline agent reference's `model`)."""

    output_model = RiskAgentOutput
    # What an unavailable/invalid LLM means: "reject" blocks the trade (fail-safe),
    # "approve" lets the rule-checked action through.
    on_failure: Literal["reject", "approve"] = "reject"

    def fallback_output(self, inputs: Mapping[str, Any], error: str) -> RiskAgentOutput:
        proposed = Action(inputs["proposed_action"])
        if self.on_failure == "approve":
            return RiskAgentOutput(
                verdict=Verdict.APPROVE,
                adjusted_action=proposed,
                reason=f"risk agent unavailable, approved by policy: {error[:300]}",
            )
        return RiskAgentOutput(
            verdict=Verdict.REJECT,
            adjusted_action=Action.HOLD,
            reason=f"risk agent unavailable, rejected by policy: {error[:300]}",
        )

    async def review(
        self,
        inputs: Mapping[str, Any],
        *,
        proposed: Action,
        symbol: str,
        run_id: UUID,
        decision_id: UUID | None,
        as_of: datetime | None = None,
    ) -> RiskVerdict:
        result = await self.invoke(
            {
                **inputs,
                "proposed_action": proposed.value,
                "instructions": self.config.params.get("instructions", ""),
            },
            run_id=run_id,
            output_model=bounded_output(proposed),
        )
        adjusted = result.output.effective()
        return RiskVerdict(
            created_at=as_of or utcnow(),
            run_id=run_id,
            symbol=symbol,
            source=self.agent_id,
            instance_id=self.instance_id,
            decision_id=decision_id,
            verdict=verdict_between(proposed, adjusted),
            original_action=proposed,
            adjusted_action=adjusted,
            reason=result.output.reason,
            llm_call_ids=result.call_ids,
        )
