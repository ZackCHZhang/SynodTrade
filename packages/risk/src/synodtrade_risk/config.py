"""Hard risk-rule parameters: configs/risk/<name>.yaml.

All ratios are fractions of the pipeline's own NAV (its virtual sub-account), not of the
whole IBKR account.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Ratio = Decimal


class LiquidityRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_spread_bps: Decimal | None = Field(default=Decimal(50), ge=0)
    min_avg_volume: Decimal | None = Field(default=Decimal(100_000), ge=0)  # 20-day avg shares
    # Without a two-sided quote the spread cannot be checked: block buys (True) or allow them.
    require_quote: bool = False


class TradingHoursRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    calendar: str = "XNYS"  # exchange_calendars code (NYSE)


class PositionCheckRules(BaseModel):
    """Compare the broker account's real positions with the strategies' virtual ledgers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Close a symbol (no buys, no sells) when the account holds fewer shares than the
    # ledgers of all strategies trading this account say: the books are out of sync.
    enabled: bool = True
    max_snapshot_age_minutes: int = Field(default=120, ge=1)  # older snapshots: not checked


class RiskRulesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    kill_switch: bool = False  # config-level kill switch (the database flag is checked too)

    max_position_pct: Ratio = Field(default=Decimal("0.20"), gt=0, le=1)
    max_gross_exposure_pct: Ratio = Field(default=Decimal("0.90"), gt=0, le=1)
    min_cash_pct: Ratio = Field(default=Decimal("0.10"), ge=0, lt=1)

    max_daily_loss_pct: Ratio | None = Field(default=Decimal("0.03"), gt=0, lt=1)
    max_weekly_loss_pct: Ratio | None = Field(default=Decimal("0.06"), gt=0, lt=1)

    max_trades_per_day: int | None = Field(default=4, ge=0)
    max_order_notional: Decimal | None = Field(default=None, gt=0)
    one_order_per_symbol_per_day: bool = True

    whitelist: list[str] = Field(default_factory=list)  # empty: every symbol allowed
    blacklist: list[str] = Field(default_factory=list)

    liquidity: LiquidityRules = Field(default_factory=LiquidityRules)
    trading_hours: TradingHoursRules = Field(default_factory=TradingHoursRules)
    position_check: PositionCheckRules = Field(default_factory=PositionCheckRules)

    @field_validator("whitelist", "blacklist")
    @classmethod
    def _upper(cls, value: list[str]) -> list[str]:
        return [s.strip().upper() for s in value]
