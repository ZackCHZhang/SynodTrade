"""Repositories: the only way other packages read or write the database."""

from __future__ import annotations

from dataclasses import dataclass

from quant_database.engine import Database
from quant_database.repositories.analysis import (
    DecisionRepository,
    RiskRepository,
    SentimentRepository,
)
from quant_database.repositories.fundamentals import FundamentalsRepository
from quant_database.repositories.market import (
    TIMEFRAME_DURATION,
    AccountRepository,
    BarRepository,
    InstrumentRepository,
    QuoteRepository,
)
from quant_database.repositories.orders import LedgerRepository, OrderRepository
from quant_database.repositories.runs import LLMCallRepository, RunRepository
from quant_database.repositories.selection import SelectionRepository
from quant_database.repositories.system import KILL_SWITCH, FlagRepository
from quant_database.repositories.watchlist import WatchlistRepository


@dataclass(frozen=True, slots=True)
class Repositories:
    """All repositories over one database, for convenient injection into stages."""

    instruments: InstrumentRepository
    bars: BarRepository
    quotes: QuoteRepository
    accounts: AccountRepository
    fundamentals: FundamentalsRepository
    runs: RunRepository
    llm_calls: LLMCallRepository
    selection: SelectionRepository
    watchlist: WatchlistRepository
    sentiment: SentimentRepository
    decisions: DecisionRepository
    risk: RiskRepository
    orders: OrderRepository
    ledger: LedgerRepository
    flags: FlagRepository

    @classmethod
    def create(cls, db: Database) -> Repositories:
        return cls(
            instruments=InstrumentRepository(db),
            bars=BarRepository(db),
            quotes=QuoteRepository(db),
            accounts=AccountRepository(db),
            fundamentals=FundamentalsRepository(db),
            runs=RunRepository(db),
            llm_calls=LLMCallRepository(db),
            selection=SelectionRepository(db),
            watchlist=WatchlistRepository(db),
            sentiment=SentimentRepository(db),
            decisions=DecisionRepository(db),
            risk=RiskRepository(db),
            orders=OrderRepository(db),
            ledger=LedgerRepository(db),
            flags=FlagRepository(db),
        )


__all__ = [
    "KILL_SWITCH",
    "TIMEFRAME_DURATION",
    "AccountRepository",
    "BarRepository",
    "DecisionRepository",
    "FlagRepository",
    "FundamentalsRepository",
    "InstrumentRepository",
    "LLMCallRepository",
    "LedgerRepository",
    "OrderRepository",
    "QuoteRepository",
    "Repositories",
    "RiskRepository",
    "RunRepository",
    "SelectionRepository",
    "SentimentRepository",
    "WatchlistRepository",
]
