"""Sentiment analysis agent: one call per (agent instance, symbol) over a batch of posts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from quant_core.agent import Agent
from quant_core.logging import get_logger
from quant_core.models import SentimentItem, SentimentResult

log = get_logger(__name__)


class SentimentOutput(BaseModel):
    """What the LLM must return (validated; bounds enforced client-side)."""

    sentiment: float = Field(
        ge=-1.0, le=1.0, description="-1 very bearish, 0 neutral, 1 very bullish"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="How reliable this read is; few or low-quality posts -> low"
    )
    summary: str = Field(max_length=800, description="At most three sentences")
    key_events: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Concrete events or catalysts mentioned (earnings, guidance, lawsuits...)",
    )
    item_ids: list[str] = Field(
        default_factory=list, description="ids of the posts that most influenced the judgement"
    )


class SentimentAgent(Agent[SentimentOutput]):
    """Sentiment agent. The LLM (provider client + model) is chosen when instantiating it:

        agent = SentimentAgent(
            store.agent("retail_mood"),                      # persona + prompt only
            pool.get("deepseek"),                            # provider client
            model=LLMModelConfig(provider="deepseek", name="deepseek-chat"),
            prompt_root=store.agents_dir,
        )

    In a pipeline, each agent reference sets it instead:
    `{ agent: retail_mood, count: 1, model: { provider: deepseek, name: deepseek-chat } }`.
    """

    output_model = SentimentOutput

    def fallback_output(self, inputs: Mapping[str, Any], error: str) -> SentimentOutput:
        # Neutral with zero confidence: downstream treats it as "no information".
        return SentimentOutput(
            sentiment=0.0, confidence=0.0, summary=f"sentiment unavailable: {error[:300]}"
        )

    async def analyze(
        self,
        symbol: str,
        items: Sequence[SentimentItem],
        *,
        run_id: UUID,
        as_of: datetime,
        lookback_hours: int,
    ) -> SentimentResult:
        inputs = {
            "symbol": symbol,
            "as_of": as_of.isoformat(timespec="minutes"),
            "lookback_hours": lookback_hours,
            "instructions": self.config.params.get("instructions", ""),
            "items": [
                {
                    "id": i.external_id,
                    "source": i.source,
                    "created_at": i.created_at.isoformat(timespec="minutes"),
                    "score": i.score,
                    "text": i.text,
                }
                for i in items
            ],
        }
        result = await self.invoke(inputs, run_id=run_id)
        out = result.output
        known = {i.external_id for i in items}
        cited = [i for i in out.item_ids if i in known]
        if len(cited) != len(out.item_ids):
            log.warning(
                "sentiment.unknown_item_ids",
                agent=self.agent_id,
                symbol=symbol,
                unknown=sorted(set(out.item_ids) - known),
            )
        return SentimentResult(
            run_id=run_id,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            prompt_version=self.prompt_version,
            symbol=symbol,
            sentiment=out.sentiment,
            confidence=out.confidence,
            summary=out.summary,
            key_events=out.key_events,
            item_ids=cited,
            llm_call_ids=result.call_ids,
            error=result.error,
        )
