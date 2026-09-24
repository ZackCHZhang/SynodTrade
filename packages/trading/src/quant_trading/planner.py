"""Turn approved actions into concrete orders: price, quantity, idempotency key."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from quant_core.models import (
    Action,
    Instrument,
    OrderIntent,
    OrderSide,
    OrderType,
    PipelineContext,
    Quote,
    Timeframe,
)
from quant_core.sizing import SizingConfig, buy_base_amount, size_order, spendable_cash
from quant_database import Repositories
from quant_trading.broker import client_order_id


class TradingOptions(BaseModel):
    """Options of the `trading` stage in configs/pipelines/*.yaml."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    order_type: OrderType = OrderType.LIMIT
    limit_offset_bps: Decimal = Field(default=Decimal(5), ge=0, le=500)
    time_in_force: Literal["DAY", "GTC"] = "DAY"
    cancel_after_minutes: float = Field(default=30, gt=0)
    poll_interval_seconds: float = Field(default=5, ge=0)
    wait_for_fills: bool = True  # track until done or cancelled; False: submit and return
    max_quote_age_minutes: int = Field(default=30, ge=1)
    timeframe: Timeframe = Timeframe.D1


def tick_size(price: Decimal) -> Decimal:
    """US equities: $0.01 at or above $1, $0.0001 below."""
    return Decimal("0.01") if price >= 1 else Decimal("0.0001")


def limit_price(
    side: OrderSide, quote: Quote | None, reference: Decimal, offset_bps: Decimal
) -> Decimal:
    """Marketable limit: buys at ask + offset (rounded up to the tick), sells at
    bid - offset (rounded down); without a quote side, from the reference price."""
    factor = offset_bps / Decimal(10_000)
    if side is OrderSide.BUY:
        base = quote.ask if quote is not None and quote.ask is not None else reference
        raw = base * (1 + factor)
        tick = tick_size(raw)
        return (raw / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    base = quote.bid if quote is not None and quote.bid is not None else reference
    raw = base * (1 - factor)
    tick = tick_size(raw)
    return max(tick, (raw / tick).to_integral_value(rounding=ROUND_FLOOR) * tick)


@dataclass(frozen=True, slots=True)
class PlannedOrder:
    intent: OrderIntent
    instrument: Instrument


@dataclass(frozen=True, slots=True)
class SkippedOrder:
    symbol: str
    action: Action
    reason: str


def processing_order(ctx: PipelineContext) -> list[str]:
    """Sells first, then buys by conviction (same order the risk stage used)."""

    def key(symbol: str) -> tuple[int, float, str]:
        action = ctx.risk_verdicts[symbol].adjusted_action
        agg = ctx.aggregated_decisions.get(symbol)
        return ({-1: 0, 1: 1, 0: 2}[action.direction], -abs(agg.score) if agg else 0.0, symbol)

    return sorted(ctx.risk_verdicts, key=key)


class OrderPlanner:
    def __init__(
        self,
        repos: Repositories,
        options: TradingOptions,
        sizing: SizingConfig,
        *,
        max_capital: Decimal,
        account_id: str | None = None,
    ) -> None:
        self._repos = repos
        self.options = options
        self.sizing = sizing
        self._max_capital = max_capital
        self._account_id = account_id

    async def _prices(self, symbol: str, as_of: datetime) -> tuple[Quote | None, Decimal | None]:
        quote = await self._repos.quotes.get_latest_quote(symbol, as_of=as_of)
        if quote is not None and as_of - quote.ts > timedelta(
            minutes=self.options.max_quote_age_minutes
        ):
            quote = None
        reference = quote.reference_price if quote is not None else None
        if reference is None:
            bars = await self._repos.bars.get_latest_bars(
                symbol, 1, self.options.timeframe, as_of=as_of
            )
            reference = bars[-1].close if bars else None
        return quote, reference

    async def plan(self, ctx: PipelineContext) -> tuple[list[PlannedOrder], list[SkippedOrder]]:
        ledger = await self._repos.ledger.get_state(
            ctx.pipeline_name, self._max_capital, as_of=ctx.as_of
        )
        cash = ledger.available_cash
        if self._account_id is not None:
            account = await self._repos.accounts.get_latest_account(self._account_id, ctx.as_of)
            if account is not None:
                available = (
                    account.available_funds if account.available_funds is not None else account.cash
                )
                cash = spendable_cash(ledger_cash=cash, account_available_cash=available)
        prices: dict[str, Decimal] = {}
        for symbol in ledger.positions:
            _, ref = await self._prices(symbol, ctx.as_of)
            if ref is not None:
                prices[symbol] = ref
        nav = ledger.nav(prices)

        planned: list[PlannedOrder] = []
        skipped: list[SkippedOrder] = []
        for symbol in processing_order(ctx):
            action = ctx.risk_verdicts[symbol].adjusted_action
            if action is Action.HOLD:
                continue
            quote, reference = await self._prices(symbol, ctx.as_of)
            if reference is None:
                skipped.append(SkippedOrder(symbol, action, "no price"))
                continue
            side = OrderSide.BUY if action.direction > 0 else OrderSide.SELL
            limit = (
                limit_price(side, quote, reference, self.options.limit_offset_bps)
                if self.options.order_type is OrderType.LIMIT
                else None
            )
            # Buys are sized at the limit price: never more shares than risk evaluated.
            sizing_price = limit if side is OrderSide.BUY and limit is not None else reference
            sized = size_order(
                action,
                price=sizing_price,
                base_amount=buy_base_amount(self.sizing.buy_base, ledger_cash=cash, ledger_nav=nav),
                cash_cap=max(cash, Decimal(0)),
                position_qty=ledger.position_qty(symbol),
                config=self.sizing,
            )
            if not sized.is_trade:
                skipped.append(SkippedOrder(symbol, action, sized.reason))
                continue
            if side is OrderSide.BUY:
                cash -= sized.notional
            instrument = await self._repos.instruments.get(symbol) or Instrument(symbol=symbol)
            intent = OrderIntent(
                client_order_id=client_order_id(ctx.run_id, symbol, action),
                run_id=ctx.run_id,
                pipeline_name=ctx.pipeline_name,
                symbol=symbol,
                action=action,
                side=side,
                quantity=sized.quantity,
                order_type=self.options.order_type,
                limit_price=limit,
                time_in_force=self.options.time_in_force,
                estimated_notional=sized.notional,
            )
            planned.append(PlannedOrder(intent, instrument))
        return planned, skipped
