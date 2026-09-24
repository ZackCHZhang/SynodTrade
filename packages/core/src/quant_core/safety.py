"""Live-trading guard: real orders need `mode: live` AND QUANT_ALLOW_LIVE=1."""

from __future__ import annotations

import os
from collections.abc import Mapping

from quant_core.models.enums import RunMode

ALLOW_LIVE_ENV = "QUANT_ALLOW_LIVE"


class LiveTradingNotAllowedError(RuntimeError):
    pass


def live_trading_allowed(mode: RunMode, env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return mode is RunMode.LIVE and env.get(ALLOW_LIVE_ENV) == "1"


def ensure_mode_allowed(mode: RunMode, env: Mapping[str, str] | None = None) -> None:
    """Call before anything that could reach a live account. Non-live modes always pass."""
    if mode is RunMode.LIVE and not live_trading_allowed(mode, env):
        raise LiveTradingNotAllowedError(
            f"mode is live but {ALLOW_LIVE_ENV}=1 is not set; refusing to run"
        )
