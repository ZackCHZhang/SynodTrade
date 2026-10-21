"""Source errors and the in-memory fake source."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from synodtrade_core.models import SentimentItem


class SourceError(RuntimeError):
    """A source could not deliver data (network, rate limit, bad response)."""


class SourceConfigError(SourceError):
    """A source is misconfigured (e.g. missing credentials)."""


class FakeSentimentSource:
    """Serves given items (filtered by symbol and time), for tests and dry runs."""

    def __init__(
        self, name: str, items: Iterable[SentimentItem] = (), *, fail: bool = False
    ) -> None:
        self.name = name
        self._items = list(items)
        self._fail = fail
        self.closed = False
        self.requests: list[tuple[list[str], datetime]] = []

    async def fetch(self, symbols: Sequence[str], since: datetime) -> list[SentimentItem]:
        self.requests.append((list(symbols), since))
        if self._fail:
            raise SourceError(f"{self.name}: simulated failure")
        wanted = {s.upper() for s in symbols}
        return [i for i in self._items if i.symbol in wanted and i.created_at >= since]

    async def aclose(self) -> None:
        self.closed = True
