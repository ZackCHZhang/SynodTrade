"""Decision agent: one call per (agent instance, symbol)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from quant_core.agent import Agent
from quant_core.logging import get_logger
from quant_core.models import Action, Decision
from quant_decision.context import SymbolContext

log = get_logger(__name__)


class DecisionOutput(BaseModel):
    """What the LLM must return (validated; bounds enforced client-side)."""

    action: Action = Field(description="One of the five tiers")
    confidence: float = Field(ge=0.0, le=1.0, description="Conviction in this action, 0..1")
    reasoning: str = Field(max_length=2000, description="Concise justification")
    referenced_data_ids: list[str] = Field(
        default_factory=list, description="ids of the data points the decision relies on"
    )


class DecisionAgent(Agent[DecisionOutput]):
    """Decision agent. The LLM (provider client + model) is chosen when instantiating it:

        agent = DecisionAgent(
            store.agent("value_investor"),                  # persona + prompt only
            pool.get("deepseek"),                            # provider client
            model=LLMModelConfig(provider="deepseek", name="deepseek-chat"),
            prompt_root=store.agents_dir,
        )

    In a pipeline, each agent reference sets it instead:
    `{ agent: value_investor, count: 2, model: { provider: deepseek, name: deepseek-chat } }`.
    """

    output_model = DecisionOutput

    def fallback_output(self, inputs: Mapping[str, Any], error: str) -> DecisionOutput:
        return DecisionOutput(
            action=Action.HOLD, confidence=0.0, reasoning=f"decision unavailable: {error[:300]}"
        )

    async def decide(self, context: SymbolContext, *, run_id: UUID) -> Decision:
        inputs, shown_ids = context.to_inputs()
        inputs["instructions"] = self.config.params.get("instructions", "")
        result = await self.invoke(inputs, run_id=run_id)
        out = result.output
        cited = [i for i in out.referenced_data_ids if i in shown_ids]
        if len(cited) != len(out.referenced_data_ids):
            log.warning(
                "decision.unknown_data_ids",
                agent=self.agent_id,
                symbol=context.symbol,
                unknown=sorted(set(out.referenced_data_ids) - shown_ids),
            )
        return Decision(
            run_id=run_id,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            prompt_version=self.prompt_version,
            symbol=context.symbol,
            action=out.action,
            confidence=out.confidence,
            reasoning=out.reasoning,
            referenced_data_ids=cited,
            llm_call_ids=result.call_ids,
            error=result.error,
        )
