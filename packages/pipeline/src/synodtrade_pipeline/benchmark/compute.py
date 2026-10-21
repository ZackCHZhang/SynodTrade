"""Daily equity curves of pipelines from their own fills, measured against a market benchmark.

A pipeline's curve starts on the day of its first paper or live run, at its `max_capital`.
Every exchange day after that, its fills up to that day are booked with the same arithmetic
as the trading ledger (`LedgerState.apply_fill`) and open positions are valued at that day's
close (the last known close if a symbol has no bar that day, the cost basis if it has none
at all). The benchmark (the pipeline's `benchmark`, SPY by default) is indexed to the same
start, so both curves begin at 0%.

Each curve also carries the LLM models the pipeline is configured with and what its LLM calls
cost: tokens from the call log, priced with the optional `prices` in llm_providers.yaml.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import pairwise

from synodtrade_core.config import ConfigError, ConfigStore, PipelineConfig, resolve_model
from synodtrade_core.llm import LLMProvidersConfig
from synodtrade_core.models import OrderSide, Timeframe
from synodtrade_core.timeutil import EXCHANGE_TZ, to_utc
from synodtrade_database import Repositories
from synodtrade_database.records import LedgerState, ModelUsage

# Runs in these modes trade a real (paper or live) account, so their fills are published.
PUBLISHED_MODES = ("paper", "live")
DEFAULT_BENCHMARK = "SPY"
TRADING_DAYS_PER_YEAR = 252
# Below these sample sizes annualised figures are noise, so they are left out.
MIN_DAYS_FOR_ANNUALISED = 60
MIN_DAYS_FOR_VOLATILITY = 20
# "Recent" LLM spend in the report: the last week of calendar days up to the curve's end.
RECENT_SPEND_DAYS = 7


@dataclass(frozen=True, slots=True)
class DayPoint:
    day: date
    nav: float
    benchmark_close: float | None


@dataclass(frozen=True, slots=True)
class LLMSpend:
    """LLM usage of a pipeline over some period, and its cost at the configured list prices."""

    calls: int = 0
    input_tokens: int = 0  # as recorded (OpenAI-compatible counts include cache hits)
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost: float | None = None  # USD; None when a used model has no price
    unpriced: tuple[str, ...] = ()  # "provider/model" without a price


def llm_spend(usages: list[ModelUsage], providers: LLMProvidersConfig | None) -> LLMSpend:
    """Sum usage rows and price them; the cost is None if any used model has no price."""
    cost = 0.0
    unpriced: list[str] = []
    for u in usages:
        provider = providers.providers.get(u.provider) if providers else None
        price = provider.prices.get(u.model) if provider else None
        if provider is None or price is None:
            if u.input_tokens or u.output_tokens:
                unpriced.append(f"{u.provider}/{u.model}")
            continue
        cost += price.cost(
            provider.kind,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=u.cache_read_input_tokens,
            cache_write_tokens=u.cache_creation_input_tokens,
        )
    return LLMSpend(
        calls=sum(u.calls for u in usages),
        input_tokens=sum(u.input_tokens for u in usages),
        output_tokens=sum(u.output_tokens for u in usages),
        cache_read_tokens=sum(u.cache_read_input_tokens for u in usages),
        cache_write_tokens=sum(u.cache_creation_input_tokens for u in usages),
        cost=None if unpriced else cost,
        unpriced=tuple(unpriced),
    )


def pipeline_models(store: ConfigStore, config: PipelineConfig) -> tuple[str, ...]:
    """Distinct model names the pipeline's agents are configured with, in stage order."""
    seen: list[str] = []
    for stage in config.stages:
        if not stage.enabled:
            continue
        for ref in stage.agents:
            name: str | None
            try:
                name = resolve_model(store.agent(ref.agent), ref.model).name
            except (ConfigError, ValueError):
                name = ref.model.name if ref.model else None
            if name and name not in seen:
                seen.append(name)
    return tuple(seen)


@dataclass(slots=True)
class PipelineCurve:
    pipeline: str
    mode: str
    benchmark: str
    capital: float
    started: datetime  # first paper/live run
    points: list[DayPoint]  # the first point is the base (0%) day
    fills: int = 0
    buys: int = 0
    sells: int = 0
    winning_sells: int = 0
    realized_pnl: float = 0.0
    commissions: float = 0.0
    open_positions: int = 0
    invested: float = 0.0  # share of the final NAV held in positions
    bars_through: date | None = None  # last session with a benchmark bar
    models: tuple[str, ...] = ()  # LLM models the pipeline's agents are configured with
    llm_total: LLMSpend | None = None  # LLM usage since the first paper/live run
    llm_recent: LLMSpend | None = None  # ... in the last RECENT_SPEND_DAYS days

    @property
    def returns(self) -> list[float]:
        """Cumulative return of every point against the base point (0.0 = flat)."""
        base = self.points[0].nav
        return [p.nav / base - 1 for p in self.points]

    @property
    def benchmark_returns(self) -> list[float | None]:
        base = next((p.benchmark_close for p in self.points if p.benchmark_close), None)
        return [
            p.benchmark_close / base - 1 if base and p.benchmark_close else None
            for p in self.points
        ]


@dataclass(frozen=True, slots=True)
class Metrics:
    days: int  # exchange days since the base day
    total_return: float
    benchmark_return: float | None
    excess_return: float | None  # total_return - benchmark_return
    cagr: float | None
    volatility: float | None  # annualised standard deviation of daily returns
    sharpe: float | None  # annualised, risk-free rate 0
    max_drawdown: float  # <= 0
    benchmark_max_drawdown: float | None
    win_rate: float | None  # share of sells that realised a profit


def max_drawdown(values: list[float]) -> float:
    peak = -math.inf
    worst = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1)
    return worst


def compute_metrics(curve: PipelineCurve) -> Metrics:
    navs = [p.nav for p in curve.points]
    days = len(navs) - 1
    total = curve.returns[-1]
    bench_closes = [p.benchmark_close for p in curve.points if p.benchmark_close]
    bench = curve.benchmark_returns[-1]
    daily = [b / a - 1 for a, b in pairwise(navs) if a > 0]
    vol = sharpe = None
    if len(daily) >= MIN_DAYS_FOR_VOLATILITY:
        mean = sum(daily) / len(daily)
        std = math.sqrt(sum((r - mean) ** 2 for r in daily) / (len(daily) - 1))
        vol = std * math.sqrt(TRADING_DAYS_PER_YEAR)
        sharpe = mean / std * math.sqrt(TRADING_DAYS_PER_YEAR) if std > 0 else None
    cagr = None
    if days >= MIN_DAYS_FOR_ANNUALISED and total > -1:
        cagr = (1 + total) ** (TRADING_DAYS_PER_YEAR / days) - 1
    return Metrics(
        days=days,
        total_return=total,
        benchmark_return=bench,
        excess_return=None if bench is None else total - bench,
        cagr=cagr,
        volatility=vol,
        sharpe=sharpe,
        max_drawdown=max_drawdown(navs),
        benchmark_max_drawdown=max_drawdown(bench_closes) if bench_closes else None,
        win_rate=curve.winning_sells / curve.sells if curve.sells else None,
    )


def exchange_day(ts: datetime) -> date:
    return to_utc(ts).astimezone(EXCHANGE_TZ).date()


def _day_end(day: date) -> datetime:
    return to_utc(datetime.combine(day + timedelta(days=1), time(0), tzinfo=EXCHANGE_TZ))


async def _closes(repos: Repositories, symbol: str, first: date, last: date) -> dict[date, float]:
    start = to_utc(datetime.combine(first, time(0), tzinfo=EXCHANGE_TZ))
    bars = await repos.bars.get_bars(symbol, Timeframe.D1, start, _day_end(last))
    return {exchange_day(b.ts): float(b.close) for b in bars}


async def build_curve(
    repos: Repositories,
    config: PipelineConfig,
    *,
    end: date | None = None,
    models: tuple[str, ...] = (),
    providers: LLMProvidersConfig | None = None,
) -> PipelineCurve | None:
    """The pipeline's curve from its first paper/live run to `end` (default: today);
    None when it never ran in paper or live mode."""
    started = await repos.runs.first_started(config.name, PUBLISHED_MODES)
    if started is None:
        return None
    first = exchange_day(started)
    last = end or datetime.now(EXCHANGE_TZ).date()
    if last < first:
        return None
    fills = await repos.orders.list_pipeline_fills(config.name, until=_day_end(last))
    benchmark = config.benchmark or DEFAULT_BENCHMARK

    # Look back a little so the base day can be the last session before the first run.
    lookback = first - timedelta(days=10)
    bench_closes = await _closes(repos, benchmark, lookback, last)
    closes = {s: await _closes(repos, s, lookback, last) for s in {f.symbol for f in fills}}

    sessions = sorted(d for d in bench_closes if first <= d <= last)
    if not sessions:  # no benchmark bars: use the days any traded symbol has a bar
        sessions = sorted({d for c in closes.values() for d in c if first <= d <= last})
    if not sessions:  # no bars at all: weekdays
        span = (last - first).days + 1
        calendar = (first + timedelta(n) for n in range(span))
        sessions = [d for d in calendar if d.weekday() < 5]
    # A fill on a day without bars (bars not updated yet) still books on that day.
    fill_days = {exchange_day(f.ts) for f in fills}
    sessions = sorted(set(sessions) | {d for d in fill_days if first <= d <= last})
    before = [d for d in bench_closes if d < first]
    base_day = max(before) if before else (sessions[0] - timedelta(days=1) if sessions else first)

    capital = Decimal(config.budget.max_capital)
    state = LedgerState(pipeline_name=config.name, max_capital=capital, cash=capital)
    curve = PipelineCurve(
        pipeline=config.name,
        mode=config.mode.value,
        benchmark=benchmark,
        capital=float(capital),
        started=started,
        points=[DayPoint(base_day, float(capital), bench_closes.get(base_day))],
        bars_through=max(bench_closes, default=None),
        models=models,
    )
    last_close: dict[str, Decimal] = {}
    bench_last: float | None = curve.points[0].benchmark_close
    pending = list(fills)
    for day in sessions:
        while pending and exchange_day(pending[0].ts) <= day:
            f = pending.pop(0)
            realized = state.apply_fill(f.side, f.symbol, f.qty, f.price, f.commission)
            curve.fills += 1
            if f.side is OrderSide.BUY:
                curve.buys += 1
            else:
                curve.sells += 1
                curve.winning_sells += int(realized > 0)
        for symbol, by_day in closes.items():
            if day in by_day:
                last_close[symbol] = Decimal(str(by_day[day]))
        bench_last = bench_closes.get(day, bench_last)
        curve.points.append(DayPoint(day, float(state.nav(last_close)), bench_last))

    nav = state.nav(last_close)
    held = nav - state.cash
    curve.realized_pnl = float(state.realized_pnl)
    curve.commissions = float(state.commissions)
    curve.open_positions = len(state.positions)
    curve.invested = float(held / nav) if nav > 0 else 0.0

    until = _day_end(last)
    usage = repos.llm_calls.usage_by_model
    curve.llm_total = llm_spend(await usage(config.name, PUBLISHED_MODES, until=until), providers)
    recent = await usage(
        config.name,
        PUBLISHED_MODES,
        since=until - timedelta(days=RECENT_SPEND_DAYS),
        until=until,
    )
    curve.llm_recent = llm_spend(recent, providers)
    return curve


async def build_curves(
    repos: Repositories,
    store: ConfigStore,
    pipelines: list[str] | None = None,
    *,
    end: date | None = None,
) -> list[PipelineCurve]:
    """Curves of `pipelines` (default: every configured pipeline that ran in paper/live)."""
    if pipelines:
        configs = [store.pipeline(n) for n in pipelines]  # unknown names fail before any query
    else:
        configured = set(store.list("pipelines"))
        ran = await repos.runs.pipelines_run_in(PUBLISHED_MODES)
        configs = [store.pipeline(n) for n in ran if n in configured]
    try:
        providers: LLMProvidersConfig | None = store.llm_providers()
    except ConfigError:
        providers = None  # costs are left out; the curves do not depend on them
    curves = []
    for config in configs:
        curve = await build_curve(
            repos,
            config,
            end=end,
            models=pipeline_models(store, config),
            providers=providers,
        )
        if curve is not None:
            curves.append(curve)
    return curves
