"""Pipeline runs, agent instance registry and the LLM call audit log."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from quant_core.llm import LLMCallRecord, LLMUsage
from quant_core.timeutil import to_utc, utcnow
from quant_database.models import AgentInstanceRow, LLMCallRow, PipelineRunRow
from quant_database.records import AgentInstance, ModelUsage, PipelineRun, RunStatus
from quant_database.repositories.base import Repository, row_dict


class RunRepository(Repository):
    async def start_run(self, run: PipelineRun) -> None:
        async with self._db.transaction() as s:
            s.add(PipelineRunRow(**run.model_dump(mode="python")))

    async def finish_run(
        self,
        run_id: UUID,
        status: RunStatus,
        *,
        error: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> None:
        if status is RunStatus.RUNNING:
            raise ValueError("finish_run needs a final status")
        async with self._db.transaction() as s:
            row = await s.get(PipelineRunRow, run_id)
            if row is None:
                raise KeyError(f"unknown run {run_id}")
            row.status = status.value
            row.ended_at = utcnow()
            row.error = error
            row.summary = summary

    async def get_run(self, run_id: UUID) -> PipelineRun | None:
        async with self._db.transaction() as s:
            row = await s.get(PipelineRunRow, run_id)
        return None if row is None else PipelineRun.model_validate(row_dict(row))

    async def running_runs(self, pipeline_name: str | None = None) -> list[PipelineRun]:
        """Runs of this pipeline (None: of any pipeline) not yet finished (used to prevent
        overlapping runs, and by account sync to leave orders of running runs alone)."""
        stmt = select(PipelineRunRow).where(PipelineRunRow.status == RunStatus.RUNNING.value)
        if pipeline_name is not None:
            stmt = stmt.where(PipelineRunRow.pipeline_name == pipeline_name)
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [PipelineRun.model_validate(row_dict(r)) for r in rows]

    async def first_started(self, pipeline_name: str, modes: Sequence[str]) -> datetime | None:
        """When the pipeline's first run in one of `modes` started (None: never ran in them)."""
        stmt = select(func.min(PipelineRunRow.started_at)).where(
            PipelineRunRow.pipeline_name == pipeline_name, PipelineRunRow.mode.in_(modes)
        )
        async with self._db.transaction() as s:
            value: datetime | None = (await s.execute(stmt)).scalar_one()
        if value is None:
            return None
        return to_utc(value) if value.tzinfo is not None else value.replace(tzinfo=UTC)

    async def pipelines_run_in(self, modes: Sequence[str]) -> list[str]:
        """Names of pipelines with at least one run in one of `modes`, sorted."""
        stmt = (
            select(PipelineRunRow.pipeline_name)
            .where(PipelineRunRow.mode.in_(modes))
            .distinct()
            .order_by(PipelineRunRow.pipeline_name)
        )
        async with self._db.transaction() as s:
            return list((await s.execute(stmt)).scalars().all())

    async def register_agent_instances(self, instances: Sequence[AgentInstance]) -> None:
        async with self._db.transaction() as s:
            s.add_all(AgentInstanceRow(**i.model_dump(mode="python")) for i in instances)

    async def get_agent_instances(self, run_id: UUID) -> list[AgentInstance]:
        stmt = (
            select(AgentInstanceRow)
            .where(AgentInstanceRow.run_id == run_id)
            .order_by(AgentInstanceRow.agent_type, AgentInstanceRow.agent_id)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [AgentInstance.model_validate(row_dict(r)) for r in rows]


class LLMCallRepository(Repository):
    """Persistent `quant_core.llm.LLMCallRecorder`."""

    async def record(self, call: LLMCallRecord) -> None:
        usage = call.usage
        async with self._db.transaction() as s:
            s.add(
                LLMCallRow(
                    id=call.id,
                    run_id=call.run_id,
                    instance_id=call.instance_id,
                    agent_id=call.agent_id,
                    provider=call.provider,
                    model=call.model,
                    attempt=call.attempt,
                    request=call.request,
                    response_text=call.response_text,
                    raw_response=call.raw_response,
                    stop_reason=call.stop_reason,
                    input_tokens=usage.input_tokens if usage else None,
                    output_tokens=usage.output_tokens if usage else None,
                    cache_read_input_tokens=usage.cache_read_input_tokens if usage else None,
                    cache_creation_input_tokens=(
                        usage.cache_creation_input_tokens if usage else None
                    ),
                    latency_ms=call.latency_ms,
                    error=call.error,
                    created_at=call.created_at,
                )
            )

    @staticmethod
    def _to_record(row: LLMCallRow) -> LLMCallRecord:
        usage = None
        if row.input_tokens is not None:
            usage = LLMUsage(
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens or 0,
                cache_read_input_tokens=row.cache_read_input_tokens or 0,
                cache_creation_input_tokens=row.cache_creation_input_tokens or 0,
            )
        data = row_dict(row)
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ):
            data.pop(key)
        return LLMCallRecord.model_validate({**data, "usage": usage})

    async def get_by_run(self, run_id: UUID) -> list[LLMCallRecord]:
        stmt = (
            select(LLMCallRow)
            .where(LLMCallRow.run_id == run_id)
            .order_by(LLMCallRow.created_at, LLMCallRow.attempt)
        )
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
        return [self._to_record(r) for r in rows]

    async def get_many(self, ids: Sequence[UUID]) -> list[LLMCallRecord]:
        """Records in the order of `ids` (unknown ids are skipped).

        Not ordered by created_at: consecutive calls can share a timestamp on coarse clocks.
        """
        if not ids:
            return []
        stmt = select(LLMCallRow).where(LLMCallRow.id.in_(list(ids)))
        async with self._db.transaction() as s:
            rows = {r.id: r for r in (await s.execute(stmt)).scalars().all()}
        return [self._to_record(rows[i]) for i in ids if i in rows]

    async def usage_by_model(
        self,
        pipeline_name: str,
        modes: Sequence[str],
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[ModelUsage]:
        """Tokens of the pipeline's LLM calls in runs of `modes`, summed per (provider, model).

        `since` / `until` bound the call time (inclusive / exclusive). Calls that failed
        before a response (no usage recorded) still count as calls.
        """
        coalesce = func.coalesce
        stmt = (
            select(
                LLMCallRow.provider,
                LLMCallRow.model,
                func.count(LLMCallRow.id),
                func.sum(coalesce(LLMCallRow.input_tokens, 0)),
                func.sum(coalesce(LLMCallRow.output_tokens, 0)),
                func.sum(coalesce(LLMCallRow.cache_read_input_tokens, 0)),
                func.sum(coalesce(LLMCallRow.cache_creation_input_tokens, 0)),
            )
            .join(PipelineRunRow, PipelineRunRow.run_id == LLMCallRow.run_id)
            .where(PipelineRunRow.pipeline_name == pipeline_name, PipelineRunRow.mode.in_(modes))
            .group_by(LLMCallRow.provider, LLMCallRow.model)
            .order_by(LLMCallRow.provider, LLMCallRow.model)
        )
        if since is not None:
            stmt = stmt.where(LLMCallRow.created_at >= since)
        if until is not None:
            stmt = stmt.where(LLMCallRow.created_at < until)
        async with self._db.transaction() as s:
            rows = (await s.execute(stmt)).all()
        return [
            ModelUsage(
                provider=provider,
                model=model,
                calls=int(calls),
                input_tokens=int(tin or 0),
                output_tokens=int(tout or 0),
                cache_read_input_tokens=int(cread or 0),
                cache_creation_input_tokens=int(cwrite or 0),
            )
            for provider, model, calls, tin, tout, cread, cwrite in rows
        ]
