"""`bounded`: awaits with a deadline and a message saying what timed out."""

import asyncio

import pytest

from synodtrade_core.aio import bounded


async def test_bounded_returns_the_result() -> None:
    async def answer() -> int:
        return 42

    assert await bounded(answer(), 1, "answer") == 42


async def test_bounded_names_what_timed_out_and_cancels_it() -> None:
    cancelled = asyncio.Event()

    async def hang() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with pytest.raises(TimeoutError, match=r"^IBKR positions timed out after 0.01s$"):
        await bounded(hang(), 0.01, "IBKR positions")
    assert cancelled.is_set()


async def test_bounded_keeps_timeouts_of_the_awaitable_itself() -> None:
    async def own_timeout() -> None:
        raise TimeoutError("connect timed out")

    with pytest.raises(TimeoutError, match=r"^connect timed out$"):
        await bounded(own_timeout(), 10, "something")
