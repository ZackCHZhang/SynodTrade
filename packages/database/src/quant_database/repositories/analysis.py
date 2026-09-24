"""Sentiment items/results, decisions, aggregated decisions and risk assessments."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select

from quant_core.models import (
    AggregatedDecision,
    Decision,
    RiskVerdict,
    SentimentItem,
    SentimentResult,
)
from quant_database.models import (
    AggregatedDecisionRow,
    DecisionRow,
    RiskAssessmentRow,
    SentimentItemRow,
    SentimentResultRow,
)
from quant_database.repositories.base import (
    Repository,
    as_of_or_now,
    row_dict,
    table_of,
    upsert_insert,
    uuid_list,
)


class SentimentRepository(Repository):
    async def add_items(self, items: Sequence[SentimentItem]) -> int:
        """Insert raw posts, skipping ones already stored. Returns the number inserted."""
        if not items:
            return 0
        rows = [
            {**item.model_dump(exclude={"metadata"}), "metadata": item.metadata} for item in items
        ]
        stmt = (
            upsert_insert(self._db.dialect, table_of(SentimentItemRow))
            .on_conflict_do_nothing(index_elements=["source", "external_id", "symbol"])
            .returning(SentimentItemRow.id)
        )
        async with self._db.transaction() as s:
            inserted = (await s.execute(stmt, rows)).all()
        return len(inserted)

    async def get_items(
        self,
        symbol: str,
        since: datetime,
        *,
        as_of: datetime | None = None,
        limit: int | None = None,
        order_by: Literal["recent", "score"] = "recent",
    ) -> list[SentimentItem]:
        """Posts about `symbol` created in [since, as_of], most recent or highest score first."""
        order = (
            (SentimentItemRow.created_at.desc(), SentimentItemRow.id.desc())
            if order_by == "recent"
            else (SentimentItemRow.score.desc(), SentimentItemRow.created_at.desc())
        )
        stmt = (
            select(SentimentItemRow)
            .where(
                SentimentItemRow.symbol == symbol.upper(),
                SentimentItemRow.created_at >= since,
                SentimentItemRow.created_at <= as_of_or_now(as_of),
            )
            .order_by(*order)
            .limit(limit)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [
            SentimentItem.model_validate(
                {
                    k: getattr(r, "metadata_" if k == "metadata" else k)
                    for k in SentimentItem.model_fields
                }
            )
            for r in rows
        ]

    async def add_results(self, results: Sequence[SentimentResult]) -> None:
        async with self._db.transaction() as s:
            s.add_all(
                SentimentResultRow(
                    **r.model_dump(exclude={"item_ids", "llm_call_ids"}),
                    item_ids=list(r.item_ids),
                    llm_call_ids=uuid_list(r.llm_call_ids),
                )
                for r in results
            )

    async def get_sentiment(
        self, symbol: str, since: datetime, as_of: datetime | None = None
    ) -> list[SentimentResult]:
        stmt = (
            select(SentimentResultRow)
            .where(
                SentimentResultRow.symbol == symbol.upper(),
                SentimentResultRow.created_at >= since,
                SentimentResultRow.created_at <= as_of_or_now(as_of),
            )
            .order_by(SentimentResultRow.created_at)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [SentimentResult.model_validate(row_dict(r)) for r in rows]

    async def get_results_by_run(self, run_id: UUID) -> list[SentimentResult]:
        stmt = (
            select(SentimentResultRow)
            .where(SentimentResultRow.run_id == run_id)
            .order_by(SentimentResultRow.symbol, SentimentResultRow.agent_id)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [SentimentResult.model_validate(row_dict(r)) for r in rows]


class DecisionRepository(Repository):
    async def add_decisions(self, decisions: Sequence[Decision]) -> None:
        async with self._db.transaction() as s:
            s.add_all(
                DecisionRow(
                    **d.model_dump(exclude={"llm_call_ids", "action"}),
                    action=d.action.value,
                    llm_call_ids=uuid_list(d.llm_call_ids),
                )
                for d in decisions
            )

    async def add_aggregated(self, decisions: Sequence[AggregatedDecision]) -> None:
        async with self._db.transaction() as s:
            s.add_all(
                AggregatedDecisionRow(
                    **d.model_dump(exclude={"votes", "final_action"}),
                    final_action=d.final_action.value,
                    votes=[v.model_dump(mode="json") for v in d.votes],
                )
                for d in decisions
            )

    async def get_decisions_by_run(self, run_id: UUID) -> list[Decision]:
        stmt = (
            select(DecisionRow)
            .where(DecisionRow.run_id == run_id)
            .order_by(DecisionRow.symbol, DecisionRow.agent_id, DecisionRow.created_at)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [Decision.model_validate(row_dict(r)) for r in rows]

    async def get_aggregated_by_run(self, run_id: UUID) -> list[AggregatedDecision]:
        stmt = (
            select(AggregatedDecisionRow)
            .where(AggregatedDecisionRow.run_id == run_id)
            .order_by(AggregatedDecisionRow.symbol)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [AggregatedDecision.model_validate(row_dict(r)) for r in rows]

    async def get_recent_aggregated(
        self, symbol: str, limit: int, as_of: datetime | None = None
    ) -> list[AggregatedDecision]:
        """Past final decisions for a symbol, newest first (decision history for prompts)."""
        stmt = (
            select(AggregatedDecisionRow)
            .where(
                AggregatedDecisionRow.symbol == symbol.upper(),
                AggregatedDecisionRow.created_at <= as_of_or_now(as_of),
            )
            .order_by(AggregatedDecisionRow.created_at.desc())
            .limit(limit)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [AggregatedDecision.model_validate(row_dict(r)) for r in rows]


class RiskRepository(Repository):
    async def add_assessments(self, verdicts: Sequence[RiskVerdict]) -> None:
        async with self._db.transaction() as s:
            s.add_all(
                RiskAssessmentRow(
                    **v.model_dump(
                        exclude={
                            "rule_hits",
                            "llm_call_ids",
                            "verdict",
                            "original_action",
                            "adjusted_action",
                        }
                    ),
                    verdict=v.verdict.value,
                    original_action=v.original_action.value,
                    adjusted_action=v.adjusted_action.value,
                    rule_hits=[h.model_dump(mode="json") for h in v.rule_hits],
                    llm_call_ids=uuid_list(v.llm_call_ids),
                )
                for v in verdicts
            )

    async def get_by_run(self, run_id: UUID) -> list[RiskVerdict]:
        stmt = (
            select(RiskAssessmentRow)
            .where(RiskAssessmentRow.run_id == run_id)
            .order_by(RiskAssessmentRow.symbol, RiskAssessmentRow.created_at)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [RiskVerdict.model_validate(row_dict(r)) for r in rows]
