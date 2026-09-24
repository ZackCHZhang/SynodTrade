"""`risk` pipeline stage: hard rules (portfolio-aware) -> risk agents -> final verdict."""

from __future__ import annotations

import asyncio
import statistics
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from quant_core.agent_factory import AgentSlot, instantiate_agents
from quant_core.config import AccountConfig, AgentRole, ConfigStore, PipelineConfig, StageConfig
from quant_core.indicators import compute_indicators
from quant_core.llm import LLMClientPool
from quant_core.logging import get_logger
from quant_core.models import Action, AggregatedDecision, PipelineContext, RiskVerdict, Timeframe
from quant_core.services import Services
from quant_core.sizing import SizingConfig, spendable_cash
from quant_database import KILL_SWITCH, AgentInstance, Repositories
from quant_risk.agent import CombineMethod, RiskAgent, combine
from quant_risk.clock import (
    ExchangeCalendarClock,
    MarketClock,
    trading_day_start,
    trading_week_start,
)
from quant_risk.config import RiskRulesConfig
from quant_risk.rules import (
    MarketSnapshot,
    PortfolioState,
    RuleEngine,
    RuleOutcome,
    verdict_between,
)

log = get_logger(__name__)


class RiskStageOptions(BaseModel):
    """Options of the `risk` stage in configs/pipelines/*.yaml."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    rules: str = "default"  # configs/risk/<rules>.yaml
    combine: CombineMethod = CombineMethod.MOST_CONSERVATIVE
    on_agent_failure: Literal["reject", "approve"] = "reject"
    max_quote_age_minutes: int = Field(default=30, ge=1)  # older quotes: use the last close
    timeframe: Timeframe = Timeframe.D1


def _pct(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.2f}%"


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
    ) -> None:
        self.options = options
        self.engine = engine
        self.agents = agents
        self._repos = repos
        self._clock = clock
        self._max_capital = max_capital
        self._account_id = account_id
        for slot in agents:
            slot.agent.on_failure = options.on_agent_failure

    # ------------------------------------------------------------ data

    async def _market(self, symbol: str, as_of: datetime) -> MarketSnapshot:
        quote = await self._repos.quotes.get_latest_quote(symbol, as_of=as_of)
        if quote is not None and as_of - quote.ts > timedelta(
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

    async def _state(
        self, ctx: PipelineContext
    ) -> tuple[PortfolioState, dict[str, MarketSnapshot]]:
        as_of, pipeline = ctx.as_of, ctx.pipeline_name
        ledger = await self._repos.ledger.get_state(pipeline, self._max_capital, as_of=as_of)
        symbols = sorted(set(ctx.aggregated_decisions) | set(ledger.positions))
        markets = {s: await self._market(s, as_of) for s in symbols}
        prices = {s: m.price for s, m in markets.items() if m.price is not None}
        nav = ledger.nav(prices)

        cash = ledger.available_cash
        if self._account_id is not None:
            account = await self._repos.accounts.get_latest_account(self._account_id, as_of)
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
        )
        return state, markets

    # ------------------------------------------------------------ agent inputs

    async def _agent_inputs(
        self,
        ctx: PipelineContext,
        symbol: str,
        outcome: RuleOutcome,
        state_before: dict[str, str],
    ) -> dict[str, Any]:
        agg = ctx.aggregated_decisions[symbol]
        bars = await self._repos.bars.get_latest_bars(
            symbol, 260, self.options.timeframe, as_of=ctx.as_of
        )
        snap = compute_indicators(bars)

        def f(value: float | None, pct: bool = True) -> str:
            if value is None:
                return "n/a"
            return f"{value * 100:+.2f}%" if pct else f"{value:.2f}"

        sized = outcome.sized
        return {
            "symbol": symbol,
            "as_of": ctx.as_of.isoformat(timespec="minutes"),
            "original_action": agg.final_action.value,
            "order": None
            if sized is None or not sized.is_trade
            else {
                "side": sized.side.value if sized.side else "",
                "quantity": format(sized.quantity.normalize(), "f"),
                "notional": f"{sized.notional:,.2f}",
                **state_before,
            },
            "portfolio": state_before,
            "market": {
                "last_close": f(snap.last_close, pct=False),
                "return_1d": f(snap.return_1d),
                "return_20d": f(snap.return_20d),
                "volatility_20d": f(snap.volatility_20d),
                "from_52w_high": f(snap.from_52w_high),
                "rsi_14": f(snap.rsi_14, pct=False),
            },
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
            "sentiment": [
                {"agent": s.agent_id, "sentiment": f"{s.sentiment:+.2f}", "summary": s.summary}
                for s in ctx.sentiment_results.get(symbol, [])
                if s.error is None
            ],
            "rule_hits": [h.message for h in outcome.hits],
        }

    # ------------------------------------------------------------ run

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        if not ctx.aggregated_decisions:
            log.info("risk.nothing_to_assess")
            return ctx
        state, markets = await self._state(ctx)

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
            }
            if outcome.sized is not None and market.price is not None:
                state.apply(symbol, outcome.sized, market.price)
            outcomes[symbol] = outcome

        await self._repos.runs.register_agent_instances(
            [AgentInstance.from_agent(slot.agent, ctx.run_id) for slot in self.agents]
        )
        to_review = [s for s, o in outcomes.items() if o.adjusted is not Action.HOLD]
        inputs = {
            s: await self._agent_inputs(ctx, s, outcomes[s], context_before[s]) for s in to_review
        }
        reviews = await asyncio.gather(
            *(
                slot.agent.review(
                    inputs[symbol],
                    proposed=outcomes[symbol].adjusted,
                    symbol=symbol,
                    run_id=ctx.run_id,
                    decision_id=ctx.aggregated_decisions[symbol].id,
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


def build_risk_stage(config: StageConfig, services: Services) -> RiskStage:
    """Stage factory (entry point `quant.stages: risk`).

    Services: `repos`, `config_store`, `llm` (LLMClientPool), `pipeline` (PipelineConfig:
    budget and sizing); optional `account` (AccountConfig: caps cash by the real account's
    available funds) and `market_clock` (MarketClock; default: the rules' exchange calendar).
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
    )
