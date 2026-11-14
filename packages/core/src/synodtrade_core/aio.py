"""Bounding awaits that may never complete (e.g. an IBKR request TWS never answers)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable


async def bounded[T](aw: Awaitable[T], seconds: float, what: str) -> T:
    """`await aw`, but raise `TimeoutError("<what> timed out after <seconds>s")` (and cancel
    it) when it takes longer than `seconds`."""
    cm = asyncio.timeout(seconds)
    try:
        async with cm:
            return await aw
    except TimeoutError as exc:
        if not cm.expired():
            raise  # raised by `aw` itself
        raise TimeoutError(f"{what} timed out after {seconds:g}s") from exc
