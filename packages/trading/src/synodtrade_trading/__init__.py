"""Trade execution.

Positions → orders, idempotency, brokers (IBKR / DryRun / Simulated), order tracking.
"""

from synodtrade_trading.broker import (
    Broker,
    BrokerError,
    DryRunBroker,
    SimulatedBroker,
    client_order_id,
)
from synodtrade_trading.ibkr import IBKRBroker, is_paper_account
from synodtrade_trading.planner import (
    OrderPlanner,
    PlannedOrder,
    SkippedOrder,
    TradingOptions,
    limit_price,
    tick_size,
)
from synodtrade_trading.stage import TradingError, TradingStage, build_trading_stage, create_broker

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
