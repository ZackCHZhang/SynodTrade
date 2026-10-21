"""Which accounts to synchronise, and when: on demand, before a pipeline run, periodically."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from synodtrade_account_sync.config import AccountSyncConfig, load_sync_config
from synodtrade_account_sync.ibkr import IBKRAccountReader
from synodtrade_account_sync.snapshot import BrokerReader
from synodtrade_account_sync.syncer import AccountSyncer, SyncTarget, group_targets
from synodtrade_core.config import AccountConfig, ConfigError, ConfigStore, PipelineConfig
from synodtrade_core.logging import get_logger
from synodtrade_core.timeutil import utcnow
from synodtrade_database import AccountSync, Repositories

log = get_logger(__name__)

ReaderFactory = Callable[[AccountConfig], BrokerReader]


def ibkr_reader(account: AccountConfig) -> BrokerReader:
    return IBKRAccountReader.from_account(account)


class AccountSyncService:
    """Synchronises the IBKR accounts the configured pipelines trade on.

    Pipelines sharing one IBKR account (even through different account configs) are
    synchronised together, over one connection. Synchronisations of the same account
    in this process never overlap.
    """

    def __init__(
        self,
        store: ConfigStore,
        repos: Repositories,
        *,
        reader_factory: ReaderFactory = ibkr_reader,
        config: AccountSyncConfig | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.store = store
        self.repos = repos
        self._reader_factory = reader_factory
        self._config = config
        self.clock = clock
        self._locks: dict[str, asyncio.Lock] = {}

    def config(self) -> AccountSyncConfig:
        """The fixed config, or configs/account_sync.yaml as it is now (edits apply live)."""
        return self._config if self._config is not None else load_sync_config(self.store)

    def targets(self, config: AccountSyncConfig | None = None) -> list[SyncTarget]:
        """One target per IBKR account used by a valid pipeline (limited to
        `config.accounts` if set). Pipelines that do not load are skipped with a warning."""
        config = config or self.config()
        items: list[tuple[PipelineConfig, str, AccountConfig]] = []
        for name in self.store.list("pipelines"):
            try:
                pipeline = self.store.pipeline(name)
                if config.accounts and pipeline.account not in config.accounts:
                    continue
                items.append((pipeline, pipeline.account, self.store.account(pipeline.account)))
            except ConfigError as exc:
                log.warning("account_sync.pipeline_skipped", pipeline=name, error=str(exc))
        return group_targets(items)

    def target_for(self, pipeline: PipelineConfig) -> SyncTarget:
        """The account `pipeline` trades on, with every other pipeline on that account."""
        account = self.store.account(pipeline.account)
        for target in self.targets(AccountSyncConfig()):  # ignore `accounts`: it is wanted
            if target.account_id == account.account_id:
                if pipeline.name in target.pipeline_names:
                    return target
                return SyncTarget(
                    target.account_id,
                    target.account,
                    target.account_names,
                    (*target.pipelines, pipeline),
                )
        return SyncTarget(account.account_id, account, (pipeline.account,), (pipeline,))

    async def sync_target(
        self,
        target: SyncTarget,
        *,
        trigger: str,
        pipeline_name: str | None = None,
        run_id: UUID | None = None,
        config: AccountSyncConfig | None = None,
    ) -> AccountSync:
        lock = self._locks.setdefault(target.account_id, asyncio.Lock())
        async with lock:
            syncer = AccountSyncer(self.repos, config or self.config(), clock=self.clock)
            return await syncer.sync(
                target,
                self._reader_factory(target.account),
                trigger=trigger,
                pipeline_name=pipeline_name,
                run_id=run_id,
            )

    async def sync_all(self, *, trigger: str) -> list[AccountSync]:
        config = self.config()
        return [
            await self.sync_target(target, trigger=trigger, config=config)
            for target in self.targets(config)
        ]

    async def sync_pipeline(
        self, pipeline: PipelineConfig, *, run_id: UUID | None = None
    ) -> AccountSync:
        """Before a run of `pipeline`: synchronise the account it trades on."""
        return await self.sync_target(
            self.target_for(pipeline),
            trigger="pipeline",
            pipeline_name=pipeline.name,
            run_id=run_id,
        )


class PeriodicSync:
    """Runs `sync_all` every `interval_minutes` while `enabled` (both re-read from the
    config on every tick, so edits apply without a restart)."""

    def __init__(
        self,
        service: AccountSyncService,
        *,
        tick_seconds: float = 15.0,
        trigger: str = "auto",
    ) -> None:
        self.service = service
        self.tick_seconds = tick_seconds
        self.trigger = trigger
        self.last_started: datetime | None = None
        self.last_finished: datetime | None = None
        self.last_error: str | None = None
        self.syncing = False
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def next_due(self, config: AccountSyncConfig | None = None) -> datetime | None:
        try:
            config = config or self.service.config()
        except ConfigError:
            return None
        if not config.enabled:
            return None
        if self.last_started is None:
            return self.service.clock()
        return self.last_started + timedelta(minutes=config.interval_minutes)

    async def run_once(self, trigger: str | None = None) -> list[AccountSync]:
        self.syncing = True
        self.last_started = self.service.clock()
        try:
            results = await self.service.sync_all(trigger=trigger or self.trigger)
            self.last_error = None
            return results
        except Exception as exc:  # e.g. an invalid config file; the loop keeps going
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.error("account_sync.loop_failed", error=self.last_error)
            raise
        finally:
            self.syncing = False
            self.last_finished = self.service.clock()

    async def _loop(self) -> None:
        while True:
            due = self.next_due()
            if due is not None and self.service.clock() >= due:
                with contextlib.suppress(Exception):  # logged; retried at the next interval
                    await self.run_once()
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self.tick_seconds)

    def start(self) -> None:
        if not self.running:
            self._task = asyncio.create_task(self._loop(), name="account-sync")

    def poke(self) -> None:
        """Re-check the schedule now (e.g. after the settings changed)."""
        self._wake.set()

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
