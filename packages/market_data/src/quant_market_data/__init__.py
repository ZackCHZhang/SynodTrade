"""行情/账户数据更新（IBKR 历史 K 线、实时快照、账户与持仓）"""

from quant_market_data.fake import FakeMarketDataProvider, generate_daily_bars
from quant_market_data.ibkr import IBKRMarketDataProvider
from quant_market_data.pacing import PacingLimiter
from quant_market_data.provider import AccountData, MarketDataError, MarketDataProvider
from quant_market_data.stage import (
    DataUpdateError,
    DataUpdateOptions,
    DataUpdateStage,
    build_data_update_stage,
)
from quant_market_data.updater import DataUpdater, UpdateReport

__version__ = "0.1.0"

__all__ = [
    "AccountData",
    "DataUpdateError",
    "DataUpdateOptions",
    "DataUpdateStage",
    "DataUpdater",
    "FakeMarketDataProvider",
    "IBKRMarketDataProvider",
    "MarketDataError",
    "MarketDataProvider",
    "PacingLimiter",
    "UpdateReport",
    "__version__",
    "build_data_update_stage",
    "generate_daily_bars",
]
