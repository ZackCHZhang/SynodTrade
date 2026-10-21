"""Repositories: the only way other packages read or write the database."""

from __future__ import annotations

from dataclasses import dataclass

from synodtrade_database.engine import Database
from synodtrade_database.repositories.account_sync import AccountSyncRepository
from synodtrade_database.repositories.analysis import (
    DecisionRepository,
    RiskRepository,
    SentimentRepository,
)
from synodtrade_database.repositories.fundamentals import FundamentalsRepository
from synodtrade_database.repositories.market import (
    TIMEFRAME_DURATION,
    AccountRepository,
    BarRepository,
    InstrumentRepository,
    QuoteRepository,
)
from synodtrade_database.repositories.orders import LedgerRepository, OrderRepository
from synodtrade_database.repositories.runs import LLMCallRepository, RunRepository
from synodtrade_database.repositories.selection import SelectionRepository
from synodtrade_database.repositories.system import KILL_SWITCH, FlagRepository
from synodtrade_database.repositories.watchlist import WatchlistRepository


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
    account_syncs: AccountSyncRepository

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
            account_syncs=AccountSyncRepository(db),
        )


__all__ = [
    "KILL_SWITCH",
    "TIMEFRAME_DURATION",
    "AccountRepository",
    "AccountSyncRepository",
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
