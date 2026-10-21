"""`risk` pipeline stage: hard rules (portfolio-aware) -> risk agents -> final verdict."""

from __future__ import annotations

import asyncio
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from synodtrade_core.agent_factory import AgentSlot, instantiate_agents
from synodtrade_core.config import (
    AccountConfig,
    AgentRole,
    ConfigError,
    ConfigStore,
    PipelineConfig,
    StageConfig,
)
from synodtrade_core.fundamentals import fundamentals_inputs
from synodtrade_core.indicators import (
    TRADING_DAYS,
    TechnicalSnapshot,
    compute_indicators,
    correlation,
    relative_to,
)
from synodtrade_core.llm import LLMClientPool
from synodtrade_core.logging import get_logger
from synodtrade_core.models import (
    Action,
    AggregatedDecision,
    Bar,
    Fundamentals,
    PipelineContext,
    RiskVerdict,
    Timeframe,
)
from synodtrade_core.research import (
    earnings_reaction,
    history_entries,
    history_inputs,
    market_inputs,
    selection_inputs,
    sentiment_inputs,
)
from synodtrade_core.services import Services
from synodtrade_core.sizing import SizingConfig, spendable_cash
from synodtrade_database import KILL_SWITCH, AgentInstance, LedgerState, Repositories
from synodtrade_database.repositories import TIMEFRAME_DURATION
from synodtrade_risk.agent import CombineMethod, RiskAgent, combine
from synodtrade_risk.clock import (
    ExchangeCalendarClock,
    MarketClock,
    trading_day_start,
    trading_week_start,
)
from synodtrade_risk.config import RiskRulesConfig
from synodtrade_risk.rules import (
    MarketSnapshot,
    PortfolioState,
    RuleEngine,
    RuleOutcome,
    verdict_between,
)

log = get_logger(__name__)

Z_95 = 1.645  # one-sided 95% normal quantile, for value at risk


class RiskStageOptions(BaseModel):
    """Options of the `risk` stage in configs/pipelines/*.yaml."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    rules: str = "default"  # configs/risk/<rules>.yaml
    combine: CombineMethod = CombineMethod.MOST_CONSERVATIVE
    on_agent_failure: Literal["reject", "approve"] = "reject"
    max_quote_age_minutes: int = Field(default=30, ge=1)  # older quotes: use the last close
    timeframe: Timeframe = Timeframe.D1
    history_limit: int = Field(default=5, ge=0, le=50)  # past decisions shown to risk agents
    stored_sentiment_hours: int = Field(default=48, ge=0, le=24 * 30)  # as in `decision`


def _pct(value: Decimal | float | None) -> str:
    return "n/a" if value is None else f"{float(value) * 100:+.2f}%"


def _processing_order(decisions: dict[str, AggregatedDecision]) -> list[str]:
    """Sells first (they free risk budget), then buys by conviction, then holds."""
    return sorted(
        decisions,
        key=lambda s: (
            {-1: 0, 1: 1, 0: 2}[decisions[s].final_action.direction],
            -abs(decisions[s].score),
            s,
        ),
    )


@dataclass(slots=True)
class _RunData:
    """What the risk agents' inputs are built from, loaded once per run."""

    ledger: LedgerState
    bars: dict[str, list[Bar]] = field(default_factory=dict)  # ~1 year per symbol
    fundamentals: dict[str, Fundamentals] = field(default_factory=dict)
    benchmark_bars: list[Bar] = field(default_factory=list)
    benchmark_snapshot: TechnicalSnapshot | None = None
    orders_30d: int = 0
    selection: dict[str, dict[str, Any]] = field(default_factory=dict)


class RiskStage:
    name = "risk"

    def __init__(
        self,
        options: RiskStageOptions,
        engine: RuleEngine,
        agents: list[AgentSlot[RiskAgent]],
        repos: Repositories,
        clock: MarketClock,
        *,
        max_capital: Decimal,
        account_id: str | None = None,
        account_currency: str | None = None,
        account_pipelines: dict[str, Decimal] | None = None,
        benchmark: str | None = None,
    ) -> None:
        self.options = options
        self.engine = engine
        self.agents = agents
        self._repos = repos
        self._clock = clock
        self._max_capital = max_capital
        self._account_id = account_id
        self._account_currency = account_currency
        # every pipeline trading the same broker account -> its budget (for the ledgers)
        self._account_pipelines = account_pipelines or {}
        self._benchmark = benchmark
        for slot in agents:
            slot.agent.on_failure = options.on_agent_failure

    # ------------------------------------------------------------ data

    async def _market(self, symbol: str, as_of: datetime, cutoff: datetime) -> MarketSnapshot:
        """Price and liquidity; quotes up to `cutoff` (see PipelineContext.snapshot_cutoff)."""
        quote = await self._repos.quotes.get_latest_quote(symbol, as_of=cutoff)
        if quote is not None and cutoff - quote.ts > timedelta(
            minutes=self.options.max_quote_age_minutes
        ):
            quote = None
        bars = await self._repos.bars.get_latest_bars(
            symbol, 20, self.options.timeframe, as_of=as_of
        )
        price = quote.reference_price if quote is not None else None
        if price is None and bars:
            price = bars[-1].close
        avg_volume = Decimal(str(statistics.fmean(float(b.volume) for b in bars))) if bars else None
        return MarketSnapshot(
            price=price,
            spread_bps=quote.spread_bps if quote is not None else None,
            avg_volume=avg_volume,
        )

    async def _return_since(
        self, pipeline: str, start: datetime, nav_now: Decimal
    ) -> Decimal | None:
        then = await self._repos.ledger.get_state(pipeline, self._max_capital, as_of=start)
        prices = {}
        for symbol in then.positions:
            bars = await self._repos.bars.get_latest_bars(
                symbol, 1, self.options.timeframe, as_of=start
            )
            if bars:
                prices[symbol] = bars[-1].close
        nav_then = then.nav(prices)
        return nav_now / nav_then - 1 if nav_then > 0 else None

    async def _position_mismatch(self, ctx: PipelineContext) -> dict[str, tuple[Decimal, Decimal]]:
        """Symbols the broker account holds fewer shares of than all strategies' ledgers."""
        check = self.engine.config.position_check
        if self._account_id is None or not check.enabled:
            return {}
        cutoff = ctx.snapshot_cutoff()
        account = await self._repos.accounts.get_latest_account(self._account_id, cutoff)
        if account is None or cutoff - account.ts > timedelta(
            minutes=check.max_snapshot_age_minutes
        ):
            log.info("risk.position_check_skipped", reason="no recent account snapshot")
            return {}
        held = await self._repos.accounts.get_latest_positions(self._account_id, cutoff) or []
        broker = {p.symbol: p.qty for p in held}
        ledgers: dict[str, Decimal] = {}
        pipelines = {ctx.pipeline_name: self._max_capital, **self._account_pipelines}
        for name, capital in pipelines.items():
            state = await self._repos.ledger.get_state(name, capital, as_of=ctx.as_of)
            for symbol, pos in state.positions.items():
                ledgers[symbol] = ledgers.get(symbol, Decimal(0)) + pos.qty
        mismatch = {
            s: (broker.get(s, Decimal(0)), qty)
            for s, qty in ledgers.items()
            if broker.get(s, Decimal(0)) < qty
        }
        if mismatch:
            log.warning(
                "risk.position_mismatch",
                account=self._account_id,
                mismatch={
                    s: {"broker": str(b), "ledgers": str(q)} for s, (b, q) in mismatch.items()
                },
            )
        return mismatch

    async def _state(
        self, ctx: PipelineContext
    ) -> tuple[PortfolioState, dict[str, MarketSnapshot], LedgerState]:
        as_of, pipeline = ctx.as_of, ctx.pipeline_name
        ledger = await self._repos.ledger.get_state(pipeline, self._max_capital, as_of=as_of)
        symbols = sorted(set(ctx.aggregated_decisions) | set(ledger.positions))
        cutoff = ctx.snapshot_cutoff()
        markets = {s: await self._market(s, as_of, cutoff) for s in symbols}
        prices = {s: m.price for s, m in markets.items() if m.price is not None}
        nav = ledger.nav(prices)

        cash = ledger.available_cash
        if self._account_id is not None:
            account = await self._repos.accounts.get_latest_account(self._account_id, cutoff)
            if account is not None:
                available = (
                    account.available_funds if account.available_funds is not None else account.cash
                )
                cash = spendable_cash(ledger_cash=cash, account_available_cash=available)

        day_start = trading_day_start(as_of)
        kill = await self._repos.flags.kill_switch_active()
        state = PortfolioState(
            as_of=as_of,
            nav=nav,
            cash=cash,
            position_qty={s: p.qty for s, p in ledger.positions.items()},
            position_value={
                s: p.qty * prices[s] if s in prices else p.cost_basis
                for s, p in ledger.positions.items()
            },
            trades_today=await self._repos.orders.count_since(pipeline, day_start),
            orders_today={
                s: await self._repos.orders.count_since(pipeline, day_start, symbol=s)
                for s in ctx.aggregated_decisions
            },
            daily_return=await self._return_since(pipeline, day_start, nav),
            weekly_return=await self._return_since(pipeline, trading_week_start(as_of), nav),
            kill_switch=(await self._repos.flags.get_reason(KILL_SWITCH) or "no reason given")
            if kill
            else None,
            market_open=self._clock.is_open(as_of),
            position_mismatch=await self._position_mismatch(ctx),
        )
        return state, markets, ledger

    async def _run_data(
        self, ctx: PipelineContext, ledger: LedgerState, symbols: list[str]
    ) -> _RunData:
        data = _RunData(ledger=ledger)
        wanted = sorted(set(symbols) | set(ledger.positions))
        for symbol in wanted:
            data.bars[symbol] = await self._repos.bars.get_latest_bars(
                symbol, TRADING_DAYS + 10, self.options.timeframe, as_of=ctx.as_of
            )
        data.fundamentals = await self._repos.fundamentals.get_latest_many(wanted, ctx.as_of)
        if self._benchmark is not None:
            data.benchmark_bars = await self._repos.bars.get_latest_bars(
                self._benchmark, TRADING_DAYS + 10, self.options.timeframe, as_of=ctx.as_of
            )
            if len(data.benchmark_bars) >= 30:
                data.benchmark_snapshot = compute_indicators(data.benchmark_bars)
        data.orders_30d = await self._repos.orders.count_since(
            ctx.pipeline_name, ctx.as_of - timedelta(days=30)
        )
        selection, results = ctx.selection, ctx.selection_results
        if selection is None:
            selection = await self._repos.selection.get_latest(ctx.pipeline_name, ctx.as_of)
            results = (
                await self._repos.selection.get_results_by_run(selection.run_id)
                if selection is not None
                else []
            )
        data.selection = selection_inputs(
            selection,
            results,
            this_run=ctx.selection is not None,
            watchlist=await self._repos.watchlist.get_active(ctx.pipeline_name, ctx.as_of),
        )
        return data

    # ------------------------------------------------------------ agent inputs

    def _beta(self, symbol: str, data: _RunData) -> float | None:
        if self._benchmark is None or len(data.benchmark_bars) < 61:
            return None
        return relative_to(data.bars.get(symbol, []), data.benchmark_bars, self._benchmark).beta_1y

    def _portfolio_beta(self, data: _RunData, state: PortfolioState) -> str:
        """Value-weighted beta of the strategy's positions (cash counts as beta 0)."""
        if state.nav <= 0 or not data.ledger.positions:
            return "n/a"
        total = 0.0
        for symbol, pos in data.ledger.positions.items():
            beta = self._beta(symbol, data)
            if beta is None:
                return "n/a"
            total += float(state.position_value.get(symbol, pos.cost_basis) / state.nav) * beta
        return f"{total:.2f}"

    def _holdings(
        self, symbol: str, data: _RunData, state: PortfolioState, prices: dict[str, Decimal]
    ) -> list[dict[str, str]]:
        """The strategy's other positions: weight, P&L, industry, correlation and beta."""
        out = []
        for other, pos in sorted(data.ledger.positions.items()):
            if other == symbol:
                continue
            value = state.position_value.get(other, pos.cost_basis)
            price = prices.get(other)
            corr = correlation(data.bars.get(symbol, []), data.bars.get(other, []), 60)
            beta = self._beta(other, data)
            f = data.fundamentals.get(other)
            out.append(
                {
                    "symbol": other,
                    "weight": _pct(value / state.nav) if state.nav > 0 else "n/a",
                    "unrealized": _pct(pos.qty * price / pos.cost_basis - 1)
                    if price is not None and pos.cost_basis
                    else "n/a",
                    "industry": (f.industry if f is not None and f.industry else "n/a"),
                    "correlation_60d": f"{corr:.2f}" if corr is not None else "n/a",
                    "beta": f"{beta:.2f}" if beta is not None else "n/a",
                }
            )
        return out

    async def _agent_inputs(
        self,
        ctx: PipelineContext,
        symbol: str,
        outcome: RuleOutcome,
        state_before: dict[str, str],
        data: _RunData,
        state: PortfolioState,
        markets: dict[str, MarketSnapshot],
    ) -> dict[str, Any]:
        agg = ctx.aggregated_decisions[symbol]
        bars = data.bars.get(symbol, [])
        snap = compute_indicators(bars)
        market = markets.get(symbol)
        price = market.price if market is not None else None
        prices = {s: m.price for s, m in markets.items() if m.price is not None}

        def f(value: float | None, pct: bool = True) -> str:
            if value is None:
                return "n/a"
            return f"{value * 100:+.2f}%" if pct else f"{value:.2f}"

        sized = outcome.sized
        order = None
        if sized is not None and sized.is_trade:
            adv = statistics.fmean(float(b.volume) for b in bars[-20:]) if bars else None
            var = (
                float(sized.notional) * Z_95 * snap.volatility_20d / math.sqrt(TRADING_DAYS)
                if snap.volatility_20d is not None
                else None
            )
            loss_2atr = (
                2 * snap.atr_14 * float(sized.quantity) / float(state.nav)
                if snap.atr_14 is not None and state.nav > 0
                else None
            )
            order = {
                "side": sized.side.value if sized.side else "",
                "quantity": format(sized.quantity.normalize(), "f"),
                "notional": f"{sized.notional:,.2f}",
                "pct_of_adv": f"{float(sized.quantity) / adv * 100:.3f}%" if adv else "n/a",
                "var_95_1d": f"{var:,.2f}" if var is not None else "n/a",
                "loss_2atr_pct_nav": f"{loss_2atr * 100:.2f}%" if loss_2atr is not None else "n/a",
                **state_before,
            }

        position = None
        pos = data.ledger.positions.get(symbol)
        if pos is not None and pos.qty > 0:
            value = pos.qty * price if price is not None else pos.cost_basis
            position = {
                "qty": format(pos.qty.normalize(), "f"),
                "avg_cost": f"{pos.avg_cost:.2f}",
                "unrealized": _pct(value / pos.cost_basis - 1) if pos.cost_basis else "n/a",
                "from_cost_in_atr": f"{(float(price) - float(pos.avg_cost)) / snap.atr_14:+.1f}"
                if price is not None and snap.atr_14
                else "n/a",
            }

        past = await self._repos.decisions.get_recent_aggregated(
            symbol,
            self.options.history_limit,
            as_of=ctx.as_of,
            pipeline_name=ctx.pipeline_name,
            exclude_methods=("insufficient_data",),
        )
        past = [p for p in past if p.run_id != ctx.run_id]
        history = history_inputs(
            history_entries(
                past,
                bars,
                TIMEFRAME_DURATION[self.options.timeframe],
                await self._repos.decisions.get_outcomes(past),
            )
        )

        sentiment = ctx.sentiment_results.get(symbol, [])
        this_run = any(s.error is None for s in sentiment)
        if not this_run and self.options.stored_sentiment_hours > 0:
            sentiment = await self._repos.sentiment.get_latest_results(
                symbol, ctx.as_of - timedelta(hours=self.options.stored_sentiment_hours), ctx.as_of
            )

        fundamentals = data.fundamentals.get(symbol)
        fprice = float(price) if price is not None else snap.last_close
        fundamental_block = fundamentals_inputs(fundamentals, fprice, ctx.as_of.date())
        if fundamental_block is not None:
            reaction = earnings_reaction(fundamentals, bars, fprice)
            if reaction is not None:
                fundamental_block["lines"].append(reaction)
        benchmark = None
        if self._benchmark is not None and data.benchmark_snapshot is not None:
            benchmark = market_inputs(
                self._benchmark,
                data.benchmark_snapshot,
                relative_to(bars, data.benchmark_bars, self._benchmark),
            )
        trades_limit = self.engine.config.max_trades_per_day
        mismatch = state.position_mismatch.get(symbol)
        instrument = await self._repos.instruments.get(symbol)

        return {
            "symbol": symbol,
            "as_of": ctx.as_of.isoformat(timespec="minutes"),
            "original_action": agg.final_action.value,
            "order": order,
            "position": position,
            "portfolio": {
                **state_before,
                "total_return": _pct(state.nav / self._max_capital - 1)
                if self._max_capital
                else "n/a",
                "realized_pnl": f"{data.ledger.realized_pnl:,.2f}",
                "positions": str(len(data.ledger.positions)),
                "beta": self._portfolio_beta(data, state),
            },
            "holdings": self._holdings(symbol, data, state, prices),
            "trading": {
                "trades_today": state_before["trades_today"],
                "max_trades_per_day": str(trades_limit) if trades_limit is not None else "none",
                "orders_30d": str(data.orders_30d),
            },
            "market": {
                "last_close": f(snap.last_close, pct=False),
                "price": f"{price:.2f}" if price is not None else "n/a",
                "return_1d": f(snap.return_1d),
                "return_20d": f(snap.return_20d),
                "volatility_20d": f(snap.volatility_20d),
                "from_52w_high": f(snap.from_52w_high),
                "rsi_14": f(snap.rsi_14, pct=False),
                "atr_14_pct": f(snap.atr_14_pct),
                "max_gap_60d": f(snap.max_gap_60d),
                "max_drawdown_1y": f(snap.max_drawdown_1y),
                "spread_bps": f"{market.spread_bps:.1f}"
                if market is not None and market.spread_bps is not None
                else "n/a",
                "avg_volume_20d": f"{market.avg_volume:,.0f}"
                if market is not None and market.avg_volume is not None
                else "n/a",
            },
            "benchmark": benchmark,
            "fundamentals": fundamental_block,
            "currency": {
                "account": self._account_currency or "n/a",
                "instrument": instrument.currency if instrument is not None else "USD",
            },
            "broker_check": None
            if mismatch is None
            else {"broker": str(mismatch[0]), "ledgers": str(mismatch[1])},
            "selection": data.selection.get(symbol),
            "history": history,
            "aggregation": {"method": agg.method, "score": f"{agg.score:+.3f}"},
            "decisions": [
                {
                    "agent": d.agent_id,
                    "action": d.action.value,
                    "confidence": f"{d.confidence:.2f}",
                    "reasoning": d.reasoning,
                }
                for d in ctx.decisions.get(symbol, [])
                if d.error is None
            ],
            "sentiment": sentiment_inputs(sentiment, ctx.as_of, this_run=this_run),
            "rule_hits": [h.message for h in outcome.hits],
        }

    # ------------------------------------------------------------ run

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        if not ctx.aggregated_decisions:
            log.info("risk.nothing_to_assess")
            return ctx
        state, markets, ledger = await self._state(ctx)

        outcomes: dict[str, RuleOutcome] = {}
        context_before: dict[str, dict[str, str]] = {}
        for symbol in _processing_order(ctx.aggregated_decisions):
            agg = ctx.aggregated_decisions[symbol]
            market = markets[symbol]
            outcome = self.engine.evaluate(symbol, agg.final_action, market, state)
            value = state.position_value.get(symbol, Decimal(0))
            notional = outcome.sized.notional if outcome.sized else Decimal(0)
            nav = state.nav
            context_before[symbol] = {
                "nav": f"{nav:,.2f}",
                "cash_pct": _pct(state.cash / nav) if nav > 0 else "n/a",
                "gross_pct": _pct(state.gross_value / nav) if nav > 0 else "n/a",
                "position_pct": _pct(value / nav) if nav > 0 else "n/a",
                "position_pct_after": _pct((value + notional) / nav)
                if nav > 0 and outcome.adjusted.direction > 0
                else "n/a",
                "daily_return": _pct(state.daily_return),
                "weekly_return": _pct(state.weekly_return),
                # before this order, but after the ones approved earlier in this pass
                "trades_today": str(state.trades_today),
            }
            if outcome.sized is not None and market.price is not None:
                state.apply(symbol, outcome.sized, market.price)
            outcomes[symbol] = outcome

        await self._repos.runs.register_agent_instances(
            [AgentInstance.from_agent(slot.agent, ctx.run_id) for slot in self.agents]
        )
        to_review = [s for s, o in outcomes.items() if o.adjusted is not Action.HOLD]
        inputs: dict[str, dict[str, Any]] = {}
        if to_review and self.agents:
            data = await self._run_data(ctx, ledger, to_review)
            for s in to_review:
                inputs[s] = await self._agent_inputs(
                    ctx, s, outcomes[s], context_before[s], data, state, markets
                )
        reviews = await asyncio.gather(
            *(
                slot.agent.review(
                    inputs[symbol],
                    proposed=outcomes[symbol].adjusted,
                    symbol=symbol,
                    run_id=ctx.run_id,
                    decision_id=ctx.aggregated_decisions[symbol].id,
                    as_of=ctx.as_of,
                )
                for symbol in to_review
                for slot in self.agents
            )
        )
        by_symbol: dict[str, list[RiskVerdict]] = {}
        for review in reviews:
            by_symbol.setdefault(review.symbol, []).append(review)

        records: list[RiskVerdict] = []
        for symbol, outcome in outcomes.items():
            agg = ctx.aggregated_decisions[symbol]
            rules_verdict = RiskVerdict(
                created_at=ctx.as_of,
                run_id=ctx.run_id,
                symbol=symbol,
                source="rules",
                decision_id=agg.id,
                verdict=outcome.verdict,
                original_action=agg.final_action,
                adjusted_action=outcome.adjusted,
                reason=outcome.reason,
                rule_hits=outcome.hits,
            )
            agent_verdicts = by_symbol.get(symbol, [])
            final_action = combine(outcome.adjusted, agent_verdicts, self.options.combine)
            reason = f"rules: {outcome.reason}"
            if agent_verdicts:
                reason += " | agents: " + "; ".join(
                    f"{v.source} {v.verdict.value} -> {v.adjusted_action.value}"
                    for v in agent_verdicts
                )
            final = RiskVerdict(
                created_at=ctx.as_of,
                run_id=ctx.run_id,
                symbol=symbol,
                source="final",
                decision_id=agg.id,
                verdict=verdict_between(agg.final_action, final_action),
                original_action=agg.final_action,
                adjusted_action=final_action,
                reason=reason,
                rule_hits=outcome.hits,
                llm_call_ids=[i for v in agent_verdicts for i in v.llm_call_ids],
            )
            records += [rules_verdict, *agent_verdicts, final]
            ctx.risk_verdicts[symbol] = final

        await self._repos.risk.add_assessments(records)
        log.info(
            "risk.done",
            final={s: v.adjusted_action.value for s, v in ctx.risk_verdicts.items()},
            reduced=[s for s, v in ctx.risk_verdicts.items() if v.verdict.value != "approve"],
        )
        return ctx


def account_pipelines(store: ConfigStore, account: str) -> dict[str, Decimal]:
    """Every configured pipeline trading `account` -> its budget."""
    out: dict[str, Decimal] = {}
    for name in store.list("pipelines"):
        try:
            other = store.pipeline(name)
        except (ConfigError, ValueError) as exc:  # a broken config elsewhere: just skip it
            log.warning("risk.pipeline_config_unreadable", pipeline=name, error=str(exc))
            continue
        if other.account == account:
            out[other.name] = other.budget.max_capital
    return out


def build_risk_stage(config: StageConfig, services: Services) -> RiskStage:
    """Stage factory (entry point `synodtrade.stages: risk`).

    Services: `repos`, `config_store`, `llm` (LLMClientPool), `pipeline` (PipelineConfig:
    budget, sizing and benchmark); optional `account` (AccountConfig: caps cash by the real
    account's available funds and enables the broker position check) and `market_clock`
    (MarketClock; default: the rules' exchange calendar).
    """
    options = config.options(RiskStageOptions)
    store = services.get("config_store", ConfigStore)
    rules = store.load("risk", options.rules, RiskRulesConfig)
    pipeline = services.get("pipeline", PipelineConfig)
    repos = services.get("repos", Repositories)
    agents = instantiate_agents(
        config.agents,
        role=AgentRole.RISK,
        default_cls=RiskAgent,
        store=store,
        llm=services.get("llm", LLMClientPool),
        recorder=repos.llm_calls,
    )
    account = services.optional("account", AccountConfig)
    clock = services.optional("market_clock", MarketClock) or ExchangeCalendarClock(
        rules.trading_hours.calendar
    )
    sizing: SizingConfig = pipeline.sizing
    return RiskStage(
        options,
        RuleEngine(rules, sizing),
        agents,
        repos,
        clock,
        max_capital=pipeline.budget.max_capital,
        account_id=account.account_id if account else None,
        account_currency=account.base_currency if account else None,
        account_pipelines=account_pipelines(store, pipeline.account) if account else None,
        benchmark=pipeline.benchmark,
    )
