"""Pre-run health checks: database, and IB Gateway when the pipeline needs it."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from synodtrade_core.config import AccountConfig, PipelineConfig
from synodtrade_core.models import RunMode
from synodtrade_database import Database

TcpCheck = Callable[[str, int, float], Awaitable[bool]]


async def tcp_reachable(host: str, port: int, limit_s: float = 3.0) -> bool:
    """Can we open a TCP connection? (Does not log in or disturb the gateway session.)"""
    try:
        async with asyncio.timeout(limit_s):
            _, writer = await asyncio.open_connection(host, port)
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


def needs_ibkr(pipeline: PipelineConfig, dry_run: bool) -> bool:
    """Market data, IBKR news and non-dry-run trading all talk to the gateway."""
    for stage in pipeline.stages:
        if not stage.enabled:
            continue
        if stage.type == "data_update":
            return True
        if stage.type == "sentiment" and "ibkr_news" in (getattr(stage, "sources", None) or []):
            return True
        if stage.type == "trading" and not dry_run and pipeline.mode is not RunMode.DRY_RUN:
            return True
    return False


@dataclass(slots=True)
class HealthReport:
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


class HealthChecker:
    def __init__(
        self, db: Database, *, tcp_check: TcpCheck = tcp_reachable, timeout_s: float = 3.0
    ) -> None:
        self._db = db
        self._tcp = tcp_check
        self._timeout = timeout_s

    async def check(
        self, pipeline: PipelineConfig, account: AccountConfig | None, *, dry_run: bool = False
    ) -> HealthReport:
        report = HealthReport()
        if not await self._db.ping():
            report.problems.append("database unreachable")
        if needs_ibkr(pipeline, dry_run):
            if account is None:
                report.problems.append(f"pipeline {pipeline.name} needs IBKR but has no account")
            elif not await self._tcp(account.host, account.port, self._timeout):
                report.problems.append(f"IB Gateway unreachable at {account.host}:{account.port}")
        return report
