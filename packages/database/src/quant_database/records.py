"""Records that only exist in the database layer (runs, agent instances, orders, ledger)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from quant_core.agent import Agent
from quant_core.models import CoreModel, OrderIntent, OrderStatus, RunMode
from quant_core.timeutil import UtcDatetime, utcnow


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"  # a stage failed and the run was aborted (fail-safe: no trading)


class PipelineRun(CoreModel):
    run_id: UUID
    pipeline_name: str
    mode: RunMode
    config_hash: str
    config: dict[str, Any]
    as_of: UtcDatetime
    started_at: UtcDatetime
    status: RunStatus = RunStatus.RUNNING
    ended_at: UtcDatetime | None = None
    error: str | None = None
    summary: dict[str, Any] | None = None


class AgentInstance(CoreModel):
    """One agent instance taking part in one run (several per agent config if count > 1)."""

    instance_id: UUID
    run_id: UUID
    agent_id: str
    agent_type: str
    persona: str
    prompt_version: str
    provider: str
    model: str
    config: dict[str, Any]
    created_at: UtcDatetime = Field(default_factory=utcnow)

    @classmethod
    def from_agent(cls, agent: Agent[Any], run_id: UUID) -> AgentInstance:
        cfg = agent.config
        return cls(
            instance_id=agent.instance_id,
            run_id=run_id,
            agent_id=cfg.agent_id,
            agent_type=cfg.role.value,
            persona=cfg.persona,
            prompt_version=cfg.prompt_version,
            provider=agent.model.provider,
            model=agent.model.name,
            config={**cfg.model_dump(mode="json"), "model": agent.model.model_dump(mode="json")},
        )


class OrderRecord(CoreModel):
    id: int
    intent: OrderIntent
    status: OrderStatus
    broker_order_id: str | None = None
    filled_qty: Decimal = Decimal(0)
    avg_fill_price: Decimal | None = None
    message: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @property
    def client_order_id(self) -> str:
        return self.intent.client_order_id

    @property
    def remaining_qty(self) -> Decimal:
        return max(Decimal(0), self.intent.quantity - self.filled_qty)


@dataclass(slots=True)
class LedgerPosition:
    symbol: str
    qty: Decimal = Decimal(0)
    cost_basis: Decimal = Decimal(0)  # total cost incl. commissions of the open quantity

    @property
    def avg_cost(self) -> Decimal:
        return self.cost_basis / self.qty if self.qty else Decimal(0)


@dataclass(slots=True)
class LedgerState:
    """A pipeline's virtual sub-account, derived from its own fills.

    `cash` starts at the pipeline's `max_capital` and moves with every fill (commissions
    included). `reserved_cash` is money committed to open buy orders not yet filled; the
    spendable amount for new buys is `available_cash`.
    """

    pipeline_name: str
    max_capital: Decimal
    cash: Decimal
    reserved_cash: Decimal = Decimal(0)
    realized_pnl: Decimal = Decimal(0)
    commissions: Decimal = Decimal(0)
    positions: dict[str, LedgerPosition] = field(default_factory=dict)

    @property
    def available_cash(self) -> Decimal:
        return max(Decimal(0), self.cash - self.reserved_cash)

    def position_qty(self, symbol: str) -> Decimal:
        pos = self.positions.get(symbol.upper())
        return pos.qty if pos else Decimal(0)

    def nav(self, prices: dict[str, Decimal]) -> Decimal:
        """Cash plus open positions at `prices`; positions without a price count at cost."""
        value = self.cash
        for symbol, pos in self.positions.items():
            price = prices.get(symbol)
            value += pos.qty * price if price is not None else pos.cost_basis
        return value
