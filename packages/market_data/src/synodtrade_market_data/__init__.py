"""Market/account data updates (IBKR historical bars, live snapshots, account and positions)"""

from synodtrade_market_data.fake import (
    FakeFundamentalsRefresher,
    FakeMarketDataProvider,
    fake_fundamentals,
    generate_daily_bars,
)
from synodtrade_market_data.fundamentals import FundamentalsUpdater, compute_fundamentals
from synodtrade_market_data.ibkr import IBKRMarketDataProvider
from synodtrade_market_data.pacing import PacingLimiter
from synodtrade_market_data.provider import AccountData, MarketDataError, MarketDataProvider
from synodtrade_market_data.sec_edgar import SecEdgarClient, SecEdgarError, SecEdgarOptions
from synodtrade_market_data.stage import (
    DataUpdateError,
    DataUpdateOptions,
    DataUpdateStage,
    build_data_update_stage,
)
from synodtrade_market_data.updater import DataUpdater, UpdateReport

__version__ = "0.1.0"

__all__ = [
    "AccountData",
    "DataUpdateError",
    "DataUpdateOptions",
    "DataUpdateStage",
    "DataUpdater",
    "FakeFundamentalsRefresher",
    "FakeMarketDataProvider",
    "FundamentalsUpdater",
    "IBKRMarketDataProvider",
    "MarketDataError",
    "MarketDataProvider",
    "PacingLimiter",
    "SecEdgarClient",
    "SecEdgarError",
    "SecEdgarOptions",
    "UpdateReport",
    "__version__",
    "build_data_update_stage",
    "compute_fundamentals",
    "fake_fundamentals",
    "generate_daily_bars",
]
