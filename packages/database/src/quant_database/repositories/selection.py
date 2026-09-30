"""Stock selection: per-agent picks and the aggregated selection of each run."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from quant_core.models import SelectionResult, StockSelection
from quant_database.models import SelectionResultRow, StockSelectionRow
from quant_database.repositories.base import Repository, as_of_or_now, row_dict, uuid_list


class SelectionRepository(Repository):
    async def add_results(self, results: Sequence[SelectionResult]) -> None:
        async with self._db.transaction() as s:
            s.add_all(
                SelectionResultRow(
                    **r.model_dump(exclude={"picks", "llm_call_ids"}),
                    picks=[p.model_dump(mode="json") for p in r.picks],
                    llm_call_ids=uuid_list(r.llm_call_ids),
                )
                for r in results
            )

    async def add_selection(self, selection: StockSelection) -> None:
        async with self._db.transaction() as s:
            s.add(StockSelectionRow(**selection.model_dump()))

    async def get_results_by_run(self, run_id: UUID) -> list[SelectionResult]:
        stmt = (
            select(SelectionResultRow)
            .where(SelectionResultRow.run_id == run_id)
            .order_by(SelectionResultRow.agent_id, SelectionResultRow.instance_id)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [SelectionResult.model_validate(row_dict(r)) for r in rows]

    async def get_by_run(self, run_id: UUID) -> StockSelection | None:
        stmt = select(StockSelectionRow).where(StockSelectionRow.run_id == run_id)
        async with self._db.transaction() as s:
            row = (await s.execute(stmt)).scalar_one_or_none()
        return StockSelection.model_validate(row_dict(row)) if row is not None else None

    async def get_latest(
        self, pipeline_name: str, as_of: datetime | None = None
    ) -> StockSelection | None:
        """The pipeline's most recent selection made at or before `as_of`."""
        stmt = (
            select(StockSelectionRow)
            .where(
                StockSelectionRow.pipeline_name == pipeline_name,
                StockSelectionRow.created_at <= as_of_or_now(as_of),
            )
            .order_by(StockSelectionRow.created_at.desc())
            .limit(1)
        )
        async with self._db.transaction() as s:
            row = (await s.execute(stmt)).scalar_one_or_none()
        return StockSelection.model_validate(row_dict(row)) if row is not None else None
