"""Risk: deterministic hard-rule engine + risk agents (can only reduce risk)"""

from quant_risk.agent import (
    CombineMethod,
    RiskAgent,
    RiskAgentOutput,
    bounded_output,
    combine,
)
from quant_risk.clock import (
    AlwaysOpenClock,
    ExchangeCalendarClock,
    MarketClock,
    trading_day_start,
    trading_week_start,
)
from quant_risk.config import LiquidityRules, RiskRulesConfig, TradingHoursRules
from quant_risk.rules import (
    Gate,
    MarketSnapshot,
    PortfolioState,
    RuleEngine,
    RuleOutcome,
    reductions,
    verdict_between,
)
from quant_risk.stage import RiskStage, RiskStageOptions, build_risk_stage

__version__ = "0.1.0"

__all__ = [
    "AlwaysOpenClock",
    "CombineMethod",
    "ExchangeCalendarClock",
    "Gate",
    "LiquidityRules",
    "MarketClock",
    "MarketSnapshot",
    "PortfolioState",
    "RiskAgent",
    "RiskAgentOutput",
    "RiskRulesConfig",
    "RiskStage",
    "RiskStageOptions",
    "RuleEngine",
    "RuleOutcome",
    "TradingHoursRules",
    "__version__",
    "bounded_output",
    "build_risk_stage",
    "combine",
    "reductions",
    "trading_day_start",
    "trading_week_start",
    "verdict_between",
]
