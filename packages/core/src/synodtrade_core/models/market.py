"""Instruments, bars, quotes, positions and account snapshots."""

from __future__ import annotations

from decimal import Decimal
from typing import Self

from pydantic import Field, model_validator

from synodtrade_core.models.base import (
    CoreModel,
    Money,
    NonNegativeMoney,
    PositiveMoney,
    PositiveQuantity,
    Quantity,
    Symbol,
)
from synodtrade_core.models.enums import Timeframe
from synodtrade_core.timeutil import UtcDatetime


class Instrument(CoreModel):
    symbol: Symbol
    sec_type: str = "STK"
    exchange: str = "SMART"
    primary_exchange: str | None = None
    currency: str = "USD"
    con_id: int | None = None  # IBKR contract id, resolved and cached by market_data
    lot_size: PositiveQuantity = Decimal(1)


class Bar(CoreModel):
    symbol: Symbol
    timeframe: Timeframe
    ts: UtcDatetime  # bar start
    open: PositiveMoney
    high: PositiveMoney
    low: PositiveMoney
    close: PositiveMoney
    volume: Quantity = Field(ge=0)

    @model_validator(mode="after")
    def _check_ohlc(self) -> Self:
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError(f"inconsistent OHLC for {self.symbol} at {self.ts.isoformat()}")
        return self


class Quote(CoreModel):
    symbol: Symbol
    ts: UtcDatetime
    bid: PositiveMoney | None = None
    ask: PositiveMoney | None = None
    last: PositiveMoney | None = None
    bid_size: Quantity | None = None
    ask_size: Quantity | None = None

    @model_validator(mode="after")
    def _check_book(self) -> Self:
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError(f"crossed quote for {self.symbol}: bid {self.bid} > ask {self.ask}")
        return self

    @property
    def mid(self) -> Decimal | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2

    @property
    def spread_bps(self) -> Decimal | None:
        mid = self.mid
        if mid is None or self.bid is None or self.ask is None:
            return None
        return (self.ask - self.bid) / mid * 10_000

    @property
    def reference_price(self) -> Decimal | None:
        """Best available price for sizing: mid, else last."""
        return self.mid if self.mid is not None else self.last


class Position(CoreModel):
    account_id: str
    symbol: Symbol
    qty: Quantity
    avg_cost: NonNegativeMoney
    ts: UtcDatetime
    market_price: PositiveMoney | None = None


class AccountSnapshot(CoreModel):
    account_id: str
    ts: UtcDatetime
    currency: str = "USD"
    nav: Money
    cash: Money
    buying_power: NonNegativeMoney
    available_funds: Money | None = None
