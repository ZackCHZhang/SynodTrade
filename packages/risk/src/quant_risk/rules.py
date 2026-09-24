"""Layer 1: deterministic risk rules. Runs before any risk agent and cannot be overridden.

Two kinds of rules:
- gates, independent of order size: they close the symbol entirely (everything -> HOLD)
  or only for buys (sells, which reduce risk, still pass);
- size rules, evaluated on the actual order the pipeline would place (core sizing): if a
  tier breaks one, the next tier toward HOLD is tried (STRONG_BUY -> BUY -> HOLD).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import IntEnum

from quant_core.models import Action, RuleHit, Verdict
from quant_core.sizing import SizedOrder, SizingConfig, buy_base_amount, size_order
from quant_risk.config import RiskRulesConfig


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    price: Decimal | None  # reference price for sizing (quote mid/last, else last close)
    spread_bps: Decimal | None = None
    avg_volume: Decimal | None = None  # 20-day average shares


@dataclass(slots=True)
class PortfolioState:
    """The pipeline's sub-account during one risk pass; updated as orders get approved."""

    as_of: datetime
    nav: Decimal
    cash: Decimal  # spendable cash for new buys
    position_qty: dict[str, Decimal] = field(default_factory=dict)
    position_value: dict[str, Decimal] = field(default_factory=dict)
    trades_today: int = 0
    orders_today: dict[str, int] = field(default_factory=dict)
    daily_return: Decimal | None = None  # NAV now / NAV at start of trading day - 1
    weekly_return: Decimal | None = None
    kill_switch: str | None = None  # reason, if the database kill switch is on
    market_open: bool = True

    @property
    def gross_value(self) -> Decimal:
        return sum(self.position_value.values(), Decimal(0))

    def apply(self, symbol: str, sized: SizedOrder, price: Decimal) -> None:
        """Account for an approved order so later symbols see its effect.

        Sale proceeds are not credited to cash: the sell may not fill before the buys.
        """
        if not sized.is_trade:
            return
        if sized.action.direction > 0:
            self.cash -= sized.notional
            self.position_qty[symbol] = self.position_qty.get(symbol, Decimal(0)) + sized.quantity
            self.position_value[symbol] = (
                self.position_value.get(symbol, Decimal(0)) + sized.notional
            )
        else:
            self.position_qty[symbol] = self.position_qty.get(symbol, Decimal(0)) - sized.quantity
            self.position_value[symbol] = (
                self.position_value.get(symbol, Decimal(0)) - sized.quantity * price
            )
        self.trades_today += 1
        self.orders_today[symbol] = self.orders_today.get(symbol, 0) + 1


class Gate(IntEnum):
    OPEN = 0
    NO_BUYS = 1
    CLOSED = 2


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    original: Action
    adjusted: Action
    hits: list[RuleHit]
    sized: SizedOrder | None  # the order for `adjusted` (None for HOLD)

    @property
    def verdict(self) -> Verdict:
        return verdict_between(self.original, self.adjusted)

    @property
    def reason(self) -> str:
        blocking = [h.message for h in self.hits if h.blocking]
        return "; ".join(blocking) if blocking else "all risk rules passed"


def verdict_between(original: Action, adjusted: Action) -> Verdict:
    if adjusted is original:
        return Verdict.APPROVE
    if adjusted is Action.HOLD:
        return Verdict.REJECT
    return Verdict.REDUCE


def reductions(action: Action) -> list[Action]:
    """`action` and every tier between it and HOLD, most aggressive first."""
    return sorted(
        (a for a in Action if a.is_reduction_of(action)), key=lambda a: abs(a.weight), reverse=True
    )


def _pct(value: Decimal) -> str:
    return f"{value * 100:.2f}%"


class RuleEngine:
    def __init__(self, config: RiskRulesConfig, sizing: SizingConfig) -> None:
        self.config = config
        self.sizing = sizing

    def evaluate(
        self, symbol: str, action: Action, market: MarketSnapshot, state: PortfolioState
    ) -> RuleOutcome:
        symbol = symbol.upper()
        gate, gate_hits = self._gates(symbol, action, market, state)
        hits = list(gate_hits)
        for candidate in reductions(action):
            if candidate is Action.HOLD:
                return RuleOutcome(action, Action.HOLD, hits, None)
            if gate is Gate.CLOSED or (gate is Gate.NO_BUYS and candidate.direction > 0):
                continue
            assert market.price is not None  # a missing price closes the gate
            sized, failures = self._size_rules(symbol, candidate, market.price, state)
            if failures:
                hits += failures
                continue
            if not sized.is_trade:
                hits.append(RuleHit(rule="order_too_small", message=sized.reason, blocking=False))
            return RuleOutcome(action, candidate, hits, sized)
        raise AssertionError("unreachable: HOLD is always a candidate")  # pragma: no cover

    # ------------------------------------------------------------ gates

    def _gates(
        self, symbol: str, action: Action, market: MarketSnapshot, state: PortfolioState
    ) -> tuple[Gate, list[RuleHit]]:
        cfg = self.config
        found: list[tuple[Gate, str, str, dict[str, str | int | float | bool | None]]] = []

        def gate(level: Gate, rule: str, message: str, **details: str | int | float | None) -> None:
            found.append((level, rule, message, dict(details)))

        if cfg.kill_switch:
            gate(Gate.CLOSED, "kill_switch", "kill switch enabled in the risk config")
        if state.kill_switch is not None:
            gate(Gate.CLOSED, "kill_switch", f"kill switch active: {state.kill_switch}")
        if cfg.whitelist and symbol not in cfg.whitelist:
            gate(Gate.CLOSED, "whitelist", f"{symbol} is not on the whitelist")
        if symbol in cfg.blacklist:
            gate(Gate.CLOSED, "blacklist", f"{symbol} is blacklisted")
        if cfg.trading_hours.enabled and not state.market_open:
            gate(Gate.CLOSED, "trading_hours", f"market closed at {state.as_of.isoformat()}")
        if market.price is None:
            gate(Gate.CLOSED, "no_price", f"no current price for {symbol}")
        if cfg.max_trades_per_day is not None and state.trades_today >= cfg.max_trades_per_day:
            gate(
                Gate.CLOSED,
                "max_trades_per_day",
                f"{state.trades_today} trades today, limit {cfg.max_trades_per_day}",
                trades_today=state.trades_today,
            )
        if cfg.one_order_per_symbol_per_day and state.orders_today.get(symbol, 0) > 0:
            gate(Gate.CLOSED, "one_order_per_symbol_per_day", f"{symbol} already traded today")
        for rule, change, limit, period in (
            ("daily_loss_limit", state.daily_return, cfg.max_daily_loss_pct, "today"),
            ("weekly_loss_limit", state.weekly_return, cfg.max_weekly_loss_pct, "this week"),
        ):
            if limit is not None and change is not None and change <= -limit:
                gate(
                    Gate.NO_BUYS,
                    rule,
                    f"strategy value {_pct(change)} {period}, limit -{_pct(limit)}: no buys",
                    change=float(change),
                )

        liq = cfg.liquidity
        if liq.max_spread_bps is not None:
            if market.spread_bps is None:
                if liq.require_quote:
                    gate(Gate.NO_BUYS, "liquidity_spread", f"no two-sided quote for {symbol}")
                else:
                    found.append(
                        (
                            Gate.OPEN,
                            "liquidity_spread",
                            "spread not checked: no two-sided quote",
                            {},
                        )
                    )
            elif market.spread_bps > liq.max_spread_bps:
                gate(
                    Gate.NO_BUYS,
                    "liquidity_spread",
                    f"spread {market.spread_bps:.1f} bps > {liq.max_spread_bps} bps",
                    spread_bps=float(market.spread_bps),
                )
        if liq.min_avg_volume is not None and (
            market.avg_volume is None or market.avg_volume < liq.min_avg_volume
        ):
            gate(
                Gate.NO_BUYS,
                "liquidity_volume",
                f"20-day average volume {market.avg_volume} < {liq.min_avg_volume}",
                avg_volume=float(market.avg_volume) if market.avg_volume is not None else None,
            )

        level = max((g for g, *_ in found), default=Gate.OPEN)
        hits = [
            RuleHit(
                rule=rule,
                message=message,
                # a hit only blocks if it restricts this particular action
                blocking=(g is Gate.CLOSED and action is not Action.HOLD)
                or (g is Gate.NO_BUYS and action.direction > 0),
                details=details,
            )
            for g, rule, message, details in found
        ]
        return level, hits

    # ------------------------------------------------------------ size rules

    def _size_rules(
        self, symbol: str, action: Action, price: Decimal, state: PortfolioState
    ) -> tuple[SizedOrder, list[RuleHit]]:
        cfg = self.config
        sized = size_order(
            action,
            price=price,
            base_amount=buy_base_amount(
                self.sizing.buy_base, ledger_cash=state.cash, ledger_nav=state.nav
            ),
            cash_cap=max(state.cash, Decimal(0)),
            position_qty=state.position_qty.get(symbol, Decimal(0)),
            config=self.sizing,
        )
        if not sized.is_trade:
            return sized, []
        failures: list[RuleHit] = []

        def fail(rule: str, message: str, value: Decimal) -> None:
            failures.append(
                RuleHit(
                    rule=rule,
                    message=f"{action}: {message}",
                    blocking=True,
                    details={"tier": action.value, "value": float(value)},
                )
            )

        notional = sized.notional
        if cfg.max_order_notional is not None and notional > cfg.max_order_notional:
            fail(
                "max_order_notional",
                f"order value {notional:.2f} > limit {cfg.max_order_notional}",
                notional,
            )
        if action.direction > 0:
            if state.nav <= 0:
                fail("non_positive_nav", "strategy value is not positive", state.nav)
                return sized, failures
            position = (state.position_value.get(symbol, Decimal(0)) + notional) / state.nav
            if position > cfg.max_position_pct:
                fail(
                    "max_position_pct",
                    f"{symbol} would be {_pct(position)} of strategy value, "
                    f"limit {_pct(cfg.max_position_pct)}",
                    position,
                )
            gross = (state.gross_value + notional) / state.nav
            if gross > cfg.max_gross_exposure_pct:
                fail(
                    "max_gross_exposure_pct",
                    f"exposure would be {_pct(gross)}, limit {_pct(cfg.max_gross_exposure_pct)}",
                    gross,
                )
            cash = (state.cash - notional) / state.nav
            if cash < cfg.min_cash_pct:
                fail(
                    "min_cash_pct",
                    f"cash would fall to {_pct(cash)}, minimum {_pct(cfg.min_cash_pct)}",
                    cash,
                )
        return sized, failures
