"""Alerting. Logs by default; Telegram when TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are set.

Other channels (e-mail, Slack...) implement the `Notifier` protocol and are added to the
`CompositeNotifier` in `default_notifier`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Protocol, runtime_checkable

import httpx

from synodtrade_core.logging import get_logger

log = get_logger(__name__)


class Level(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@runtime_checkable
class Notifier(Protocol):
    async def notify(self, level: Level, title: str, message: str) -> None: ...


class LogNotifier:
    async def notify(self, level: Level, title: str, message: str) -> None:
        getattr(log, level.value)("alert", title=title, message=message)


class TelegramNotifier:
    """Sends alerts through a Telegram bot. Failures to deliver are logged, never raised."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        min_level: Level = Level.WARNING,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat_id = chat_id
        self._min = min_level
        self._client = client or httpx.AsyncClient(timeout=10)

    async def notify(self, level: Level, title: str, message: str) -> None:
        order = list(Level)
        if order.index(level) < order.index(self._min):
            return
        text = f"[{level.value.upper()}] {title}\n{message}"[:4000]
        try:
            response = await self._client.post(
                self._url, json={"chat_id": self._chat_id, "text": text}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.error("telegram.delivery_failed", error=type(exc).__name__)  # no token in logs


class CompositeNotifier:
    def __init__(self, notifiers: Sequence[Notifier]) -> None:
        self.notifiers = list(notifiers)

    async def notify(self, level: Level, title: str, message: str) -> None:
        for notifier in self.notifiers:
            await notifier.notify(level, title, message)


def default_notifier(env: Mapping[str, str] | None = None) -> CompositeNotifier:
    env = os.environ if env is None else env
    notifiers: list[Notifier] = [LogNotifier()]
    token, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if token and chat:
        notifiers.append(TelegramNotifier(token, chat))
    return CompositeNotifier(notifiers)
