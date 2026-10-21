import asyncio
import io
import json
import socket
from typing import Any

import httpx
import pytest

from synodtrade_core.config import AccountConfig, PipelineConfig
from synodtrade_core.logging import configure_logging
from synodtrade_database import Database
from synodtrade_scheduler import (
    CompositeNotifier,
    HealthChecker,
    Level,
    LogNotifier,
    TelegramNotifier,
    default_notifier,
    needs_ibkr,
    tcp_reachable,
)

ACCOUNT = AccountConfig(
    name="ibkr_main", account_id="DU1", host="127.0.0.1", port=4002, client_id=17
)


def pipeline(mode: str = "paper", stages: list[dict[str, Any]] | None = None) -> PipelineConfig:
    return PipelineConfig.model_validate(
        {
            "name": "p",
            "mode": mode,
            "account": "ibkr_main",
            "universe": ["AAPL"],
            "budget": {"max_capital": 1000},
            "stages": stages
            if stages is not None
            else [{"type": "decision"}, {"type": "risk"}, {"type": "trading"}],
        }
    )


# ------------------------------------------------------------------ notifiers


async def test_log_notifier() -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    await LogNotifier().notify(Level.ERROR, "run failed", "details")
    [line] = [json.loads(x) for x in stream.getvalue().splitlines()]
    assert (line["level"], line["title"], line["message"]) == ("error", "run failed", "details")


async def test_telegram_notifier() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        assert request.url.path == "/botSECRET/sendMessage"
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tg = TelegramNotifier("SECRET", "42", client=client)
    await tg.notify(Level.INFO, "fyi", "below the minimum level")
    await tg.notify(Level.ERROR, "run failed", "x" * 5000)
    assert len(sent) == 1
    assert sent[0]["chat_id"] == "42"
    assert sent[0]["text"].startswith("[ERROR] run failed")
    assert len(sent[0]["text"]) == 4000


async def test_telegram_delivery_failure_is_logged_without_token() -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    await TelegramNotifier("SECRET", "42", client=client).notify(Level.ERROR, "t", "m")
    assert "telegram.delivery_failed" in stream.getvalue()
    assert "SECRET" not in stream.getvalue()


async def test_composite_and_default() -> None:
    calls: list[str] = []

    class Recorder:
        async def notify(self, level: Level, title: str, message: str) -> None:
            calls.append(title)

    await CompositeNotifier([Recorder(), Recorder()]).notify(Level.INFO, "hi", "")
    assert calls == ["hi", "hi"]
    assert len(default_notifier({}).notifiers) == 1
    with_tg = default_notifier({"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"})
    assert isinstance(with_tg.notifiers[1], TelegramNotifier)


# ------------------------------------------------------------------ health


async def test_tcp_reachable_against_a_local_server() -> None:
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        assert await tcp_reachable("127.0.0.1", port, 1.0)
    finally:
        server.close()
        await server.wait_closed()
    with socket.socket() as s:  # a port that was free a moment ago is (almost surely) closed
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
    assert not await tcp_reachable("127.0.0.1", closed, 1.0)


@pytest.mark.parametrize(
    ("mode", "stages", "dry_run", "expected"),
    [
        ("paper", [{"type": "decision"}, {"type": "risk"}, {"type": "trading"}], False, True),
        ("paper", [{"type": "decision"}, {"type": "risk"}, {"type": "trading"}], True, False),
        ("dry_run", [{"type": "decision"}, {"type": "risk"}, {"type": "trading"}], False, False),
        ("dry_run", [{"type": "data_update"}], False, True),
        ("dry_run", [{"type": "sentiment", "sources": ["reddit"]}], False, False),
        ("dry_run", [{"type": "sentiment", "sources": ["ibkr_news"]}], False, True),
        ("paper", [{"type": "data_update", "enabled": False}], False, False),
    ],
)
def test_needs_ibkr(mode: str, stages: list[dict[str, Any]], dry_run: bool, expected: bool) -> None:
    assert needs_ibkr(pipeline(mode, stages), dry_run) is expected


async def test_health_checker(db: Database) -> None:
    probes: list[tuple[str, int]] = []

    async def gateway_down(host: str, port: int, limit_s: float) -> bool:
        probes.append((host, port))
        return False

    async def gateway_up(host: str, port: int, limit_s: float) -> bool:
        return True

    down = await HealthChecker(db, tcp_check=gateway_down).check(pipeline(), ACCOUNT)
    assert down.problems == ["IB Gateway unreachable at 127.0.0.1:4002"]
    assert probes == [("127.0.0.1", 4002)]
    assert (await HealthChecker(db, tcp_check=gateway_up).check(pipeline(), ACCOUNT)).ok
    no_account = await HealthChecker(db, tcp_check=gateway_up).check(pipeline(), None)
    assert "has no account" in no_account.problems[0]
    dry = await HealthChecker(db, tcp_check=gateway_down).check(pipeline(), ACCOUNT, dry_run=True)
    assert dry.ok  # a dry run that does not trade does not need the gateway

    broken_db = Database("sqlite+aiosqlite:///Z:/missing/dir/x.db")
    report = await HealthChecker(broken_db, tcp_check=gateway_up).check(pipeline(), ACCOUNT)
    assert report.problems == ["database unreachable"]
    await broken_db.dispose()
