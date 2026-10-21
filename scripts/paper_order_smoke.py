"""Smoke-test the real order path against an IBKR *paper* account.

    poetry run python scripts/paper_order_smoke.py [--symbol AAPL] [--pipeline demo_all_modules]

Skips decision/risk: injects an approved BUY for one symbol and runs the real trading
stage with IBKRBroker in PAPER mode (limit order, tracked until filled or cancelled after
a few minutes). Then prints the order, fills and the pipeline's sub-ledger.
Refuses to run unless the gateway reports only paper accounts.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import uuid4

from synodtrade_core.config import ConfigStore, StageConfig
from synodtrade_core.envfile import load_env_file
from synodtrade_core.logging import configure_logging
from synodtrade_core.models import Action, PipelineContext, RiskVerdict, RunMode, Verdict
from synodtrade_core.services import Services
from synodtrade_core.timeutil import utcnow
from synodtrade_database import Database, PipelineRun, Repositories, RunStatus
from synodtrade_trading import IBKRBroker, build_trading_stage


async def main(symbol: str, pipeline_name: str, db_url: str) -> int:
    load_env_file(".env")
    store = ConfigStore(Path("configs"))
    pipeline = store.pipeline(pipeline_name)
    account = store.account(pipeline.account)
    db = Database(db_url)
    await db.create_all()
    repos = Repositories.create(db)
    now = utcnow()
    run_id = uuid4()
    await repos.runs.start_run(
        PipelineRun(
            run_id=run_id,
            pipeline_name=pipeline.name,
            mode=RunMode.PAPER,
            config_hash="smoke-test",
            config={"smoke_test": "paper order path", "symbol": symbol},
            as_of=now,
            started_at=now,
        )
    )
    ctx = PipelineContext(
        run_id=run_id,
        pipeline_name=pipeline.name,
        mode=RunMode.PAPER,
        universe=[symbol],
        as_of=now,
    )
    ctx.risk_verdicts[symbol] = RiskVerdict(
        run_id=run_id,
        symbol=symbol,
        source="smoke_test",
        verdict=Verdict.APPROVE,
        original_action=Action.BUY,
        adjusted_action=Action.BUY,
        reason="manual smoke test of the paper order path",
    )
    broker = IBKRBroker.from_account(account, RunMode.PAPER)
    config = StageConfig.model_validate(
        {
            "type": "trading",
            "order_type": "limit",
            "limit_offset_bps": 25,
            "cancel_after_minutes": 3,
            "poll_interval_seconds": 5,
        }
    )
    stage = build_trading_stage(
        config, Services(repos=repos, broker=broker, pipeline=pipeline, account=account)
    )
    try:
        ctx = await stage.run(ctx)
    finally:
        await broker.disconnect()

    for record in await repos.orders.list_by_run(run_id):
        i = record.intent
        print(
            f"order {i.client_order_id}: {i.side.value} {i.quantity} {i.symbol} "
            f"limit {i.limit_price} -> {record.status.value}, filled {record.filled_qty} "
            f"@ {record.avg_fill_price} (IB id {record.broker_order_id})"
        )
        for f in await repos.orders.get_fills(i.client_order_id):
            print(f"  fill {f.exec_id}: {f.qty} @ {f.price}, commission {f.commission}")
    ledger = await repos.ledger.get_state(pipeline.name, pipeline.budget.max_capital)
    print(
        f"ledger {pipeline.name}: cash {ledger.cash:.2f}, reserved {ledger.reserved_cash:.2f}, "
        f"positions {{{', '.join(f'{s}: {p.qty}' for s, p in ledger.positions.items())}}}"
    )
    status = RunStatus.FAILED if ctx.aborted else RunStatus.SUCCEEDED
    await repos.runs.finish_run(run_id, status)
    await db.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--pipeline", default="demo_all_modules")
    parser.add_argument("--db-url", default="sqlite+aiosqlite:///./paper_test.db")
    args = parser.parse_args()
    configure_logging("INFO")
    raise SystemExit(asyncio.run(main(args.symbol.upper(), args.pipeline, args.db_url)))
