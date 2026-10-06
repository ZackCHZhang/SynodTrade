"""Sentiment items/results, decisions, aggregated decisions and risk assessments."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import select

from quant_core.models import (
    Action,
    AggregatedDecision,
    Decision,
    DecisionOutcome,
    RiskVerdict,
    SentimentItem,
    SentimentResult,
)
from quant_database.models import (
    AggregatedDecisionRow,
    DecisionRow,
    OrderRow,
    PipelineRunRow,
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

    async def get_latest_results(
        self, symbol: str, since: datetime, as_of: datetime | None = None
    ) -> list[SentimentResult]:
        """The newest successful analysis of each sentiment agent for `symbol` made in
        [since, as_of], from any run or pipeline (sentiment is about the stock, not about a
        strategy). Used when the current run has no sentiment of its own."""
        latest: dict[str, SentimentResult] = {}
        for result in await self.get_sentiment(symbol, since, as_of):
            if result.error is None:
                latest[result.agent_id] = result  # ascending by time: the last one wins
        return sorted(latest.values(), key=lambda r: r.agent_id)

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
        self,
        symbol: str,
        limit: int,
        as_of: datetime | None = None,
        *,
        pipeline_name: str | None = None,
        exclude_methods: Sequence[str] = (),
    ) -> list[AggregatedDecision]:
        """Past final decisions for a symbol, newest first (decision history for prompts).
        `pipeline_name` limits them to one strategy's runs."""
        stmt = (
            select(AggregatedDecisionRow)
            .where(
                AggregatedDecisionRow.symbol == symbol.upper(),
                AggregatedDecisionRow.created_at <= as_of_or_now(as_of),
            )
            .order_by(AggregatedDecisionRow.created_at.desc())
            .limit(limit)
        )
        if pipeline_name is not None:
            stmt = stmt.join(
                PipelineRunRow, PipelineRunRow.run_id == AggregatedDecisionRow.run_id
            ).where(PipelineRunRow.pipeline_name == pipeline_name)
        if exclude_methods:
            stmt = stmt.where(AggregatedDecisionRow.method.not_in(list(exclude_methods)))
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [AggregatedDecision.model_validate(row_dict(r)) for r in rows]

    async def get_outcomes(
        self, decisions: Sequence[AggregatedDecision]
    ) -> dict[UUID, DecisionOutcome]:
        """decision id -> what the risk layer and the broker made of it."""
        if not decisions:
            return {}
        ids = [d.id for d in decisions]
        risk_stmt = select(RiskAssessmentRow).where(
            RiskAssessmentRow.decision_id.in_(ids), RiskAssessmentRow.source == "final"
        )
        run_ids = list({d.run_id for d in decisions})
        order_stmt = select(OrderRow).where(OrderRow.run_id.in_(run_ids))
        async with self._db.transaction() as s:
            risk = {r.decision_id: r for r in (await s.execute(risk_stmt)).scalars().all()}
            orders = {
                (o.run_id, o.symbol): o for o in (await s.execute(order_stmt)).scalars().all()
            }
        out: dict[UUID, DecisionOutcome] = {}
        for d in decisions:
            verdict = risk.get(d.id)
            order = orders.get((d.run_id, d.symbol))
            out[d.id] = DecisionOutcome(
                risk_action=Action(verdict.adjusted_action) if verdict is not None else None,
                risk_reason=verdict.reason if verdict is not None else None,
                order_status=order.status if order is not None else None,
                filled_qty=order.filled_qty if order is not None else Decimal(0),
                avg_fill_price=order.avg_fill_price if order is not None else None,
            )
        return out


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
