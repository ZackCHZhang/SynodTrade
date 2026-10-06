from datetime import UTC, datetime, timedelta

from quant_database import Repositories

T0 = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)
P = "demo"


async def test_selection_refreshes_and_re_adds(repos: Repositories) -> None:
    wl = repos.watchlist
    assert await wl.record_selection(P, [("nvda", 0.8, "trend"), ("AMD", 0.7, "gap")], T0) == [
        "NVDA",
        "AMD",
    ]
    later = T0 + timedelta(days=2)
    assert await wl.record_selection(P, [("NVDA", 0.9, "still strong")], later) == []
    [nvda] = [e for e in await wl.get_active(P, later) if e.symbol == "NVDA"]
    assert (nvda.times_selected, nvda.last_score, nvda.last_reason) == (2, 0.9, "still strong")
    assert nvda.added_at == T0
    assert nvda.last_selected_at == later
    # point in time: nothing before it was added; other pipelines are separate
    assert await wl.get_active(P, T0 - timedelta(minutes=1)) == []
    assert await wl.get_active("other", later) == []

    assert await wl.remove(P, "nvda", later)
    assert not await wl.remove(P, "NVDA", later)  # already removed
    assert [e.symbol for e in await wl.get_active(P, later)] == ["AMD"]
    again = later + timedelta(days=1)
    assert await wl.record_selection(P, [("NVDA", 0.6, "back")], again) == ["NVDA"]
    [back] = [e for e in await wl.get_active(P, again) if e.symbol == "NVDA"]
    assert (back.added_at, back.times_selected) == (again, 1)  # a fresh entry


async def test_expiry_size_limit_pins_and_keep(repos: Repositories) -> None:
    wl = repos.watchlist
    for i, symbol in enumerate(["A", "B", "C", "D"]):
        await wl.record_selection(P, [(symbol, 0.5, None)], T0 + timedelta(days=i))
    await wl.add(P, "PIN", T0, pinned=True, note="long-term idea")
    now = T0 + timedelta(days=12)
    # A (day 0) and B (day 1) are older than 10 days, but B is held -> kept
    removed = await wl.expire(P, now, max_age=timedelta(days=10), keep=["b"])
    assert removed == ["A"]
    # size 3: PIN, B (held) are protected; the stalest of C/D goes
    removed = await wl.expire(P, now, max_age=timedelta(days=10), max_size=3, keep=["B"])
    assert removed == ["C"]
    active = await wl.get_active(P, now)
    assert [e.symbol for e in active] == ["PIN", "D", "B"]  # pinned first, then recency
    everything = await wl.get_all(P)
    reasons = {e.symbol: e.removed_reason for e in everything if not e.active}
    assert reasons == {"A": "not selected for 10 days", "C": "list full (max 3)"}
    # manual add keeps an existing entry's history and only updates pin/note
    entry = await wl.add(P, "d", now, pinned=True)
    assert (entry.pinned, entry.times_selected, entry.note) == (True, 1, None)
