"""Read-only views of the database for the web UI.

Generic access goes through the ORM tables (so Decimal and UTC columns decode exactly as
the rest of the system sees them); the run, market and portfolio views reuse the
repositories.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import (
    Boolean,
    ColumnElement,
    Float,
    Integer,
    String,
    Table,
    Text,
    Uuid,
    and_,
    cast,
    func,
    select,
)

from quant_core.config import ConfigError, ConfigStore
from quant_core.models import OrderStatus, Timeframe
from quant_database import Database, Repositories
from quant_database.column_types import DecimalType, UtcDateTime
from quant_database.models import (
    Base,
    InstrumentRow,
    LLMCallRow,
    MarketBarRow,
    OrderRow,
    PipelineRunRow,
    QuoteSnapshotRow,
)

PREVIEW_CHARS = 240
OPEN_ORDER_STATUSES = [s.value for s in OrderStatus if not s.is_terminal]
FILTER_OPS = ("eq", "ne", "contains", "gt", "gte", "lt", "lte", "is_null", "not_null")


def jsonable(value: Any) -> Any:
    """Plain JSON for the browser. Decimals become floats: these views are for display."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return jsonable(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, Sequence | set | frozenset):
        return [jsonable(v) for v in value]
    return str(value)


def mask_url(url: str) -> str:
    """Hide the password in a database URL."""
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.rsplit("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def tables() -> dict[str, Table]:
    return {t.name: t for t in Base.metadata.sorted_tables}


def _column_kind(column: Any) -> str:
    t = column.type
    if isinstance(t, DecimalType):
        return "decimal"
    if isinstance(t, UtcDateTime):
        return "datetime"
    if isinstance(t, Uuid):
        return "uuid"
    if isinstance(t, Boolean):
        return "boolean"
    if isinstance(t, Integer):
        return "integer"
    if isinstance(t, Float):
        return "float"
    if isinstance(t, String | Text):
        return "string"
    return "json"


def table_info(table: Table) -> list[dict[str, Any]]:
    return [
        {
            "name": c.name,
            "kind": _column_kind(c),
            "primary_key": c.primary_key,
            "foreign_key": next((fk.target_fullname for fk in c.foreign_keys), None),
            "nullable": c.nullable,
        }
        for c in table.columns
    ]


def _coerce(column: Any, raw: str) -> Any:
    kind = _column_kind(column)
    if kind == "uuid":
        return UUID(raw)
    if kind == "datetime":
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    if kind == "decimal":
        return Decimal(raw)
    if kind == "integer":
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "boolean":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return raw


def _filter(table: Table, spec: Mapping[str, Any], dialect: str) -> ColumnElement[bool]:
    name, op, raw = str(spec.get("column")), spec.get("op", "eq"), spec.get("value")
    if name not in table.c:
        raise ValueError(f"unknown column {name!r}")
    if op not in FILTER_OPS:
        raise ValueError(f"unknown filter operator {op!r}")
    column = table.c[name]
    kind = _column_kind(column)
    if op == "is_null":
        return column.is_(None)
    if op == "not_null":
        return column.is_not(None)
    text = "" if raw is None else str(raw)
    if op == "contains":
        return cast(column, String).ilike(f"%{text}%")
    if kind == "decimal" and dialect == "sqlite" and op not in ("eq", "ne"):
        raise ValueError("decimal columns are stored as text on SQLite: use eq / ne")
    value = _coerce(column, text)
    compare: dict[str, Any] = {
        "eq": column.__eq__,
        "ne": column.__ne__,
        "gt": column.__gt__,
        "gte": column.__ge__,
        "lt": column.__lt__,
        "lte": column.__le__,
    }
    clause: ColumnElement[bool] = compare[op](value)
    return clause


def _preview(value: Any) -> tuple[Any, bool]:
    """Shorten long text / JSON cells for the grid; the row view shows them in full."""
    if isinstance(value, str) and len(value) > PREVIEW_CHARS:
        return value[:PREVIEW_CHARS] + "…", True
    if isinstance(value, dict | list):
        text = json.dumps(value, ensure_ascii=False, default=str)
        if len(text) > PREVIEW_CHARS:
            return text[:PREVIEW_CHARS] + "…", True
    return value, False


class DataService:
    def __init__(self, db: Database, configs: Path, env: Mapping[str, str] | None = None) -> None:
        self.db = db
        self.repos = Repositories.create(db)
        self._configs = configs
        self._env = env

    # ------------------------------------------------------------ generic tables

    async def table_counts(self) -> list[dict[str, Any]]:
        out = []
        async with self.db.transaction() as s:
            for name, table in tables().items():
                count = (await s.execute(select(func.count()).select_from(table))).scalar_one()
                out.append({"name": name, "rows": int(count), "columns": table_info(table)})
        return out

    async def rows(
        self,
        name: str,
        *,
        offset: int = 0,
        limit: int = 50,
        sort: str | None = None,
        desc: bool = True,
        filters: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        table = tables().get(name)
        if table is None:
            raise LookupError(f"unknown table {name!r}")
        where = [_filter(table, f, self.db.dialect) for f in filters]
        stmt = select(table)
        count = select(func.count()).select_from(table)
        if where:
            stmt = stmt.where(and_(*where))
            count = count.where(and_(*where))
        if sort:
            if sort not in table.c:
                raise ValueError(f"unknown column {sort!r}")
            stmt = stmt.order_by(table.c[sort].desc() if desc else table.c[sort].asc())
        else:
            pk = list(table.primary_key.columns)
            stmt = stmt.order_by(*(c.desc() for c in pk))
        stmt = stmt.offset(max(offset, 0)).limit(min(max(limit, 1), 500))
        async with self.db.transaction() as s:
            total = (await s.execute(count)).scalar_one()
            result = (await s.execute(stmt)).mappings().all()
        rows = []
        for row in result:
            cells: dict[str, Any] = {}
            truncated = []
            for key, value in row.items():
                cell, cut = _preview(jsonable(value))
                cells[key] = cell
                if cut:
                    truncated.append(key)
            rows.append({"cells": cells, "truncated": truncated})
        pk_name = next(iter(table.primary_key.columns)).name
        return {
            "table": name,
            "primary_key": pk_name,
            "columns": table_info(table),
            "total": int(total),
            "rows": rows,
        }

    async def row(self, name: str, pk: str) -> dict[str, Any]:
        table = tables().get(name)
        if table is None:
            raise LookupError(f"unknown table {name!r}")
        column = next(iter(table.primary_key.columns))
        async with self.db.transaction() as s:
            found = (
                (await s.execute(select(table).where(column == _coerce(column, pk))))
                .mappings()
                .one_or_none()
            )
        if found is None:
            raise LookupError(f"{name} {pk} not found")
        return {k: jsonable(v) for k, v in found.items()}

    # ------------------------------------------------------------ runs

    async def runs(
        self,
        *,
        pipeline: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        stmt = select(PipelineRunRow)
        count = select(func.count()).select_from(PipelineRunRow)
        conditions = []
        if pipeline:
            conditions.append(PipelineRunRow.pipeline_name == pipeline)
        if status:
            conditions.append(PipelineRunRow.status == status)
        if conditions:
            stmt = stmt.where(*conditions)
            count = count.where(*conditions)
        stmt = stmt.order_by(PipelineRunRow.started_at.desc()).offset(offset).limit(limit)
        async with self.db.transaction() as s:
            total = (await s.execute(count)).scalar_one()
            rows = (await s.execute(stmt)).scalars().all()
        return {"total": int(total), "runs": [self._run_light(r) for r in rows]}

    @staticmethod
    def _run_light(row: PipelineRunRow) -> dict[str, Any]:
        config = row.config or {}
        return {
            "run_id": str(row.run_id),
            "pipeline_name": row.pipeline_name,
            "mode": row.mode,
            "status": row.status,
            "as_of": jsonable(row.as_of),
            "started_at": jsonable(row.started_at),
            "ended_at": jsonable(row.ended_at),
            "error": row.error,
            "summary": jsonable(row.summary),
            "stages_run": config.get("stages_run", []),
            "offline": bool(config.get("offline", False)),
            "config_hash": row.config_hash,
        }

    async def run_detail(self, run_id: UUID) -> dict[str, Any]:
        async with self.db.transaction() as s:
            row = await s.get(PipelineRunRow, run_id)
            if row is None:
                raise LookupError(f"run {run_id} not found")
            calls = (
                (
                    await s.execute(
                        select(LLMCallRow)
                        .where(LLMCallRow.run_id == run_id)
                        .order_by(LLMCallRow.created_at, LLMCallRow.attempt)
                    )
                )
                .scalars()
                .all()
            )
        r = self.repos
        orders = await r.orders.list_by_run(run_id)
        fills = {o.client_order_id: await r.orders.get_fills(o.client_order_id) for o in orders}
        return {
            "run": {**self._run_light(row), "config": jsonable(row.config)},
            "agent_instances": jsonable(await r.runs.get_agent_instances(run_id)),
            "selection_results": jsonable(await r.selection.get_results_by_run(run_id)),
            "stock_selection": jsonable(await r.selection.get_by_run(run_id)),
            "sentiment_results": jsonable(await r.sentiment.get_results_by_run(run_id)),
            "decisions": jsonable(await r.decisions.get_decisions_by_run(run_id)),
            "aggregated_decisions": jsonable(await r.decisions.get_aggregated_by_run(run_id)),
            "risk_assessments": jsonable(await r.risk.get_by_run(run_id)),
            "orders": [
                {**jsonable(o), "fills": jsonable(fills[o.client_order_id])} for o in orders
            ],
            "llm_calls": [
                {
                    "id": str(c.id),
                    "instance_id": jsonable(c.instance_id),
                    "agent_id": c.agent_id,
                    "provider": c.provider,
                    "model": c.model,
                    "attempt": c.attempt,
                    "stop_reason": c.stop_reason,
                    "input_tokens": c.input_tokens,
                    "output_tokens": c.output_tokens,
                    "latency_ms": c.latency_ms,
                    "error": c.error,
                    "created_at": jsonable(c.created_at),
                }
                for c in calls
            ],
        }

    async def llm_call(self, call_id: UUID) -> dict[str, Any]:
        async with self.db.transaction() as s:
            row = await s.get(LLMCallRow, call_id)
        if row is None:
            raise LookupError(f"llm call {call_id} not found")
        return {c.key: jsonable(getattr(row, c.key)) for c in LLMCallRow.__mapper__.column_attrs}

    # ------------------------------------------------------------ market data

    async def instruments(self) -> list[dict[str, Any]]:
        stmt = (
            select(
                InstrumentRow.symbol,
                MarketBarRow.timeframe,
                func.count(MarketBarRow.id),
                func.min(MarketBarRow.ts),
                func.max(MarketBarRow.ts),
            )
            .join(MarketBarRow, MarketBarRow.instrument_id == InstrumentRow.id, isouter=True)
            .group_by(InstrumentRow.symbol, MarketBarRow.timeframe)
            .order_by(InstrumentRow.symbol)
        )
        async with self.db.transaction() as s:
            rows = (await s.execute(stmt)).all()
        out: dict[str, dict[str, Any]] = {}
        for symbol, timeframe, count, first, last in rows:
            entry = out.setdefault(symbol, {"symbol": symbol, "timeframes": {}})
            if timeframe is not None:
                # min/max bypass the UTC type decorator on SQLite: normalise here.
                entry["timeframes"][timeframe] = {
                    "bars": int(count),
                    "first": _as_iso(first),
                    "last": _as_iso(last),
                }
        return list(out.values())

    async def bars(self, symbol: str, timeframe: str, limit: int) -> dict[str, Any]:
        tf = Timeframe(timeframe)
        stmt = (
            select(MarketBarRow)
            .join(InstrumentRow, InstrumentRow.id == MarketBarRow.instrument_id)
            .where(InstrumentRow.symbol == symbol.upper(), MarketBarRow.timeframe == tf.value)
            .order_by(MarketBarRow.ts.desc())
            .limit(min(max(limit, 1), 5000))
        )
        quotes_stmt = (
            select(QuoteSnapshotRow)
            .join(InstrumentRow, InstrumentRow.id == QuoteSnapshotRow.instrument_id)
            .where(InstrumentRow.symbol == symbol.upper())
            .order_by(QuoteSnapshotRow.ts.desc())
            .limit(20)
        )
        async with self.db.transaction() as s:
            rows = (await s.execute(stmt)).scalars().all()
            quotes = (await s.execute(quotes_stmt)).scalars().all()
        return {
            "symbol": symbol.upper(),
            "timeframe": tf.value,
            "bars": [
                {
                    "ts": jsonable(b.ts),
                    "open": jsonable(b.open),
                    "high": jsonable(b.high),
                    "low": jsonable(b.low),
                    "close": jsonable(b.close),
                    "volume": jsonable(b.volume),
                }
                for b in reversed(rows)
            ],
            "quotes": [
                {
                    "ts": jsonable(q.ts),
                    "bid": jsonable(q.bid),
                    "ask": jsonable(q.ask),
                    "last": jsonable(q.last),
                }
                for q in quotes
            ],
        }

    # ------------------------------------------------------------ portfolio

    async def _last_price(self, symbol: str) -> Decimal | None:
        bars = await self.repos.bars.get_latest_bars(
            symbol, 1, Timeframe.D1, as_of=datetime.now(UTC) + timedelta(days=1)
        )
        quote = await self.repos.quotes.get_latest_quote(symbol)
        if quote is not None and quote.last is not None and (not bars or quote.ts >= bars[-1].ts):
            return quote.last
        return bars[-1].close if bars else None

    async def portfolio(self) -> dict[str, Any]:
        store = ConfigStore(self._configs, env=self._env)
        pipelines: list[dict[str, Any]] = []
        for name in store.list("pipelines"):
            try:
                config = store.pipeline(name)
            except ConfigError as exc:
                pipelines.append({"name": name, "error": str(exc)})
                continue
            ledger = await self.repos.ledger.get_state(name, config.budget.max_capital)
            positions = []
            prices: dict[str, Decimal] = {}
            for symbol, pos in sorted(ledger.positions.items()):
                price = await self._last_price(symbol)
                if price is not None:
                    prices[symbol] = price
                value = pos.qty * price if price is not None else None
                positions.append(
                    {
                        "symbol": symbol,
                        "qty": jsonable(pos.qty),
                        "avg_cost": jsonable(pos.avg_cost),
                        "cost_basis": jsonable(pos.cost_basis),
                        "last_price": jsonable(price),
                        "market_value": jsonable(value),
                        "unrealized_pnl": jsonable(
                            value - pos.cost_basis if value is not None else None
                        ),
                    }
                )
            nav = ledger.nav(prices)
            entry: dict[str, Any] = {
                "name": name,
                "mode": config.mode.value,
                "account": config.account,
                "currency": config.budget.currency,
                "max_capital": jsonable(ledger.max_capital),
                "cash": jsonable(ledger.cash),
                "reserved_cash": jsonable(ledger.reserved_cash),
                "available_cash": jsonable(ledger.available_cash),
                "realized_pnl": jsonable(ledger.realized_pnl),
                "commissions": jsonable(ledger.commissions),
                "nav": jsonable(nav),
                "return_pct": jsonable(
                    (nav / ledger.max_capital - 1) if ledger.max_capital else None
                ),
                "positions": positions,
            }
            pipelines.append(entry)
        accounts = []
        for name in store.list("accounts"):
            try:
                account = store.account(name)
            except ConfigError as exc:
                accounts.append({"name": name, "error": str(exc)})
                continue
            snapshot = await self.repos.accounts.get_latest_account(account.account_id)
            held = await self.repos.accounts.get_latest_positions(account.account_id)
            accounts.append(
                {
                    "name": name,
                    "account_id": account.account_id,
                    "snapshot": jsonable(snapshot),
                    "positions": jsonable(held or []),
                }
            )
        async with self.db.transaction() as s:
            recent = (
                (await s.execute(select(OrderRow).order_by(OrderRow.id.desc()).limit(100)))
                .scalars()
                .all()
            )
        orders = [
            {c.key: jsonable(getattr(o, c.key)) for c in OrderRow.__mapper__.column_attrs}
            for o in recent
        ]
        return {"pipelines": pipelines, "accounts": accounts, "orders": orders}

    # ------------------------------------------------------------ overview

    async def overview(self) -> dict[str, Any]:
        recent = await self.runs(limit=10)
        async with self.db.transaction() as s:
            by_status = (
                await s.execute(
                    select(PipelineRunRow.status, func.count()).group_by(PipelineRunRow.status)
                )
            ).all()
            per_pipeline = (
                await s.execute(
                    select(
                        PipelineRunRow.pipeline_name,
                        func.count(),
                        func.max(PipelineRunRow.started_at),
                    ).group_by(PipelineRunRow.pipeline_name)
                )
            ).all()
            open_orders = (
                await s.execute(
                    select(func.count())
                    .select_from(OrderRow)
                    .where(OrderRow.status.in_(OPEN_ORDER_STATUSES))
                )
            ).scalar_one()
        return {
            "database": {"url": mask_url(self.db.url), "dialect": self.db.dialect},
            "kill_switch": {
                "active": await self.repos.flags.kill_switch_active(),
                "reason": await self.repos.flags.get_reason("kill_switch"),
            },
            "runs_by_status": {status: int(n) for status, n in by_status},
            "pipelines": {
                name: {"runs": int(n), "last_started": _as_iso(last)}
                for name, n, last in per_pipeline
            },
            "open_orders": int(open_orders),
            "recent_runs": recent["runs"],
        }


def _as_iso(value: Any) -> str | None:
    """Aggregates (min/max) skip the column type decorator; SQLite returns naive strings."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        iso: str = value.astimezone(UTC).isoformat()
        return iso
    return str(value)
