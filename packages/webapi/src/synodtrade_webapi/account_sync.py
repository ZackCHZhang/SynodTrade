"""Account synchronisation as seen from the web UI: the periodic loop running inside the
server process (settings in configs/account_sync.yaml, re-read on every tick), manual
synchronisation, and the history stored in `account_syncs`."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from synodtrade_account_sync import AccountSyncService, PeriodicSync
from synodtrade_core.config import ConfigError, ConfigStore
from synodtrade_database import AccountSync, Database, Repositories


def _iso(t: datetime | None) -> str | None:
    return t.isoformat() if t else None


def sync_dict(sync: AccountSync) -> dict[str, Any]:
    return sync.model_dump(mode="json")


class AccountSyncController:
    def __init__(
        self,
        configs: Path,
        db: Database,
        env: Mapping[str, str] | None = None,
        *,
        service: AccountSyncService | None = None,
    ) -> None:
        self.service = service or AccountSyncService(
            ConfigStore(configs, env=env), Repositories.create(db)
        )
        self.periodic = PeriodicSync(self.service)

    def start(self) -> None:
        self.periodic.start()

    async def stop(self) -> None:
        await self.periodic.stop()

    def loop_status(self) -> dict[str, Any]:
        periodic = self.periodic
        config_error = None
        config: dict[str, Any] | None = None
        try:
            parsed = self.service.config()
            config = parsed.model_dump(mode="json")
            next_due = periodic.next_due(parsed) if periodic.running else None
        except ConfigError as exc:
            config_error = str(exc)
            next_due = None
        return {
            "running": periodic.running,
            "syncing": periodic.syncing,
            "last_started": _iso(periodic.last_started),
            "last_finished": _iso(periodic.last_finished),
            "last_error": periodic.last_error,
            "next_due": _iso(next_due),
            "config": config,
            "config_error": config_error,
        }

    async def status(self, history: int = 30) -> dict[str, Any]:
        repos = self.service.repos
        accounts: list[dict[str, Any]] = []
        try:
            for target in self.service.targets():
                accounts.append(
                    {
                        "account_id": target.account_id,
                        "account_names": list(target.account_names),
                        "pipelines": target.pipeline_names,
                    }
                )
        except ConfigError:
            pass  # shown through loop_status()["config_error"]
        return {
            **self.loop_status(),
            "accounts": accounts,
            "latest": [sync_dict(s) for s in await repos.account_syncs.latest()],
            "history": [sync_dict(s) for s in await repos.account_syncs.recent(history)],
        }

    async def run_now(self) -> list[dict[str, Any]]:
        return [sync_dict(s) for s in await self.periodic.run_once(trigger="manual")]
