"""configs/account_sync.yaml: when and how IBKR accounts are synchronised with the database."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from synodtrade_core.config import ConfigStore, load_model

CONFIG_FILE = "account_sync.yaml"
SLUG = r"^[a-z][a-z0-9_]*$"


class AccountSyncConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Background synchronisation (web console process, or `synodtrade-sync loop`).
    enabled: bool = True
    interval_minutes: int = Field(default=20, ge=1, le=24 * 60)
    # Synchronise the pipeline's account first in every paper/live run (before any stage).
    before_pipeline: bool = True
    # A failed synchronisation before a run aborts the run (default: log it and go on; the
    # trading stage still brings its own open orders up to date before trading).
    required_before_pipeline: bool = False
    # An open order the broker no longer knows (not open, not executed) is closed as
    # cancelled once it has not changed for this long (it may still be on its way).
    gone_after_minutes: int = Field(default=30, ge=1, le=7 * 24 * 60)
    # Orders closed in the last N days are checked again for fills reported late, e.g. an
    # order closed as cancelled that was in fact executed. IBKR keeps executions for about
    # a day by default (TWS can keep up to 7: Global Configuration > API > Settings).
    recheck_days: int = Field(default=3, ge=0, le=30)
    # Save the account summary and positions (account_snapshots / position_snapshots).
    snapshot: bool = True
    # Account configs (configs/accounts/) to synchronise; empty: every account a pipeline uses.
    accounts: list[Annotated[str, Field(pattern=SLUG)]] = Field(default_factory=list)


def load_sync_config(store: ConfigStore) -> AccountSyncConfig:
    """configs/account_sync.yaml, or the defaults if the file does not exist."""
    path = store.root / CONFIG_FILE
    if not path.is_file():
        return AccountSyncConfig()
    return load_model(path, AccountSyncConfig, store._env)
