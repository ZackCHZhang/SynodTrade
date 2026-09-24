"""交易执行：仓位→订单、幂等、Broker（IBKR / DryRun / Simulated）、订单跟踪"""

from quant_trading.broker import (
    Broker,
    BrokerError,
    DryRunBroker,
    SimulatedBroker,
    client_order_id,
)
from quant_trading.ibkr import IBKRBroker, is_paper_account
from quant_trading.planner import (
    OrderPlanner,
    PlannedOrder,
    SkippedOrder,
    TradingOptions,
    limit_price,
    tick_size,
)
from quant_trading.stage import TradingError, TradingStage, build_trading_stage, create_broker

__version__ = "0.1.0"

__all__ = [
    "Broker",
    "BrokerError",
    "DryRunBroker",
    "IBKRBroker",
    "OrderPlanner",
    "PlannedOrder",
    "SimulatedBroker",
    "SkippedOrder",
    "TradingError",
    "TradingOptions",
    "TradingStage",
    "__version__",
    "build_trading_stage",
    "client_order_id",
    "create_broker",
    "is_paper_account",
    "limit_price",
    "tick_size",
]
