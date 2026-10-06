"""Client-side throttling for IBKR historical data requests.

IBKR "pacing violations" occur with more than 6 requests for the same contract within 2
seconds and, for bars of 30 seconds or less only, with more than 60 historical requests in
10 minutes (larger bars such as 1 min or 1 day are only "soft throttled"). We stay below both
with margin, so violations should not happen in the first place (retrying after one costs a
long lockout). Callers pass `small_bars=True` for bar sizes of 30 seconds or less.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable


class PacingLimiter:
    def __init__(
        self,
        *,
        max_requests: int = 50,
        window_s: float = 600.0,
        per_key_max: int = 5,
        per_key_window_s: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._max = max_requests
        self._window = window_s
        self._key_max = per_key_max
        self._key_window = per_key_window_s
        self._clock = clock
        self._sleep = sleep
        self._global: deque[float] = deque()
        self._per_key: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: str, *, small_bars: bool = False) -> None:
        """Wait until one more request for `key` fits within the limits, then record it.
        The 10-minute window only counts (and limits) small-bar requests."""
        async with self._lock:
            while True:
                now = self._clock()
                key_times = self._per_key.setdefault(key, deque())
                self._prune(self._global, now - self._window)
                self._prune(key_times, now - self._key_window)
                wait = 0.0
                if small_bars and len(self._global) >= self._max:
                    wait = self._global[0] + self._window - now
                if len(key_times) >= self._key_max:
                    wait = max(wait, key_times[0] + self._key_window - now)
                if wait <= 0:
                    if small_bars:
                        self._global.append(now)
                    key_times.append(now)
                    return
                await self._sleep(wait)

    @staticmethod
    def _prune(times: deque[float], cutoff: float) -> None:
        while times and times[0] <= cutoff:
            times.popleft()
