"""The market data provider interface implemented by IBKR and the fake provider."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from synodtrade_core.models import AccountSnapshot, Bar, Instrument, Position, Quote, Timeframe


class MarketDataError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AccountData:
    """An account snapshot and the positions captured at the same instant."""

    account: AccountSnapshot
    positions: list[Position] = field(default_factory=list)


@runtime_checkable
class MarketDataProvider(Protocol):
    name: str

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def is_healthy(self) -> bool: ...

    async def resolve_instrument(self, symbol: str) -> Instrument:
        """Look up the broker contract (con_id, primary exchange...) for a symbol."""
        ...

    async def fetch_bars(
        self, instrument: Instrument, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        """Bars with start <= ts < end. May include the still-forming current bar."""
        ...

    async def fetch_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]: ...

    async def fetch_account(self, account_id: str) -> AccountData: ...
