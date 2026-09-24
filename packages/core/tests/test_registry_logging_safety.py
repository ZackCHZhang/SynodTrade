import io
import json
from typing import Any
from uuid import uuid4

import pytest

from quant_core import registry as registry_module
from quant_core.logging import REDACTED, bind_run, configure_logging, get_logger
from quant_core.models import RunMode
from quant_core.registry import AGENTS, SENTIMENT_SOURCES, STAGES, Registry, RegistryError
from quant_core.safety import (
    ALLOW_LIVE_ENV,
    LiveTradingNotAllowedError,
    ensure_mode_allowed,
    live_trading_allowed,
)

# ------------------------------------------------------------------ registry


def test_register_and_get() -> None:
    reg: Registry[int] = Registry("thing")
    reg.register("a", 1)
    assert reg.get("a") == 1
    assert "a" in reg
    assert 5 not in reg
    assert reg.names() == ["a"]


def test_decorator_and_duplicates() -> None:
    reg: Registry[Any] = Registry("thing")

    @reg.decorator("f")
    def f() -> None: ...

    assert reg.get("f") is f
    reg.register("f", f)  # re-registering the same object is fine
    with pytest.raises(RegistryError, match="already registered"):
        reg.register("f", lambda: None)
    reg.register("f", 2, replace=True)
    assert reg.get("f") == 2
    reg.unregister("f")
    reg.unregister("missing")
    assert reg.names() == []


def test_unknown_name_lists_known() -> None:
    reg: Registry[int] = Registry("stage")
    reg.register("data_update", 1)
    with pytest.raises(RegistryError, match=r"unknown stage 'x' \(known: data_update\)"):
        reg.get("x")


class _FakeEntryPoint:
    def __init__(self, name: str, value: object) -> None:
        self.name = name
        self._value = value

    def load(self) -> object:
        return self._value


def test_entry_points_are_loaded_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_entry_points(*, group: str) -> list[_FakeEntryPoint]:
        seen.append(group)
        return [_FakeEntryPoint("plugin", 42), _FakeEntryPoint("local", 99)]

    monkeypatch.setattr(registry_module, "entry_points", fake_entry_points)
    reg: Registry[int] = Registry("stage", "quant.test")
    reg.register("local", 1)
    assert reg.get("local") == 1  # explicit registration wins, no lookup needed
    assert seen == []
    assert reg.get("plugin") == 42
    assert seen == ["quant.test"]
    assert reg.names() == ["local", "plugin"]
    assert reg.get("local") == 1


def test_no_entry_point_group() -> None:
    reg: Registry[int] = Registry("thing")
    with pytest.raises(RegistryError):
        reg.get("x")


def test_global_registries() -> None:
    assert STAGES.entry_point_group == "quant.stages"
    assert AGENTS.entry_point_group == "quant.agents"
    assert SENTIMENT_SOURCES.entry_point_group == "quant.sentiment_sources"


# ------------------------------------------------------------------ logging


def _log_lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_logs_are_json_with_run_id_and_times() -> None:
    stream = io.StringIO()
    configure_logging("DEBUG", stream=stream)
    log = get_logger("test", component="core")
    run_id = uuid4()
    with bind_run(run_id, "long_term_stocks"):
        log.info("inside", n=1)
    log.info("outside")

    inside, outside = _log_lines(stream)
    assert inside["event"] == "inside"
    assert inside["run_id"] == str(run_id)
    assert inside["pipeline"] == "long_term_stocks"
    assert inside["component"] == "core"
    assert inside["level"] == "info"
    assert inside["ts"].endswith("Z") or inside["ts"].endswith("+00:00")
    assert inside["ts_local"].endswith(("+01:00", "+02:00"))  # Europe/Berlin
    assert "run_id" not in outside


def test_secrets_are_redacted() -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    get_logger().info(
        "x",
        api_key="sk-live",
        ANTHROPIC_API_KEY="sk",
        password="p",
        access_token="t",
        input_tokens=12,
        symbol="AAPL",
    )
    [line] = _log_lines(stream)
    for key in ("api_key", "ANTHROPIC_API_KEY", "password", "access_token"):
        assert line[key] == REDACTED
    assert line["input_tokens"] == 12
    assert line["symbol"] == "AAPL"


def test_level_filtering_and_console_renderer() -> None:
    stream = io.StringIO()
    configure_logging("WARNING", json=False, stream=stream)
    log = get_logger()
    log.info("hidden")
    log.warning("shown")
    assert "hidden" not in stream.getvalue()
    assert "shown" in stream.getvalue()


# ------------------------------------------------------------------ safety


@pytest.mark.parametrize("mode", [RunMode.DRY_RUN, RunMode.PAPER])
def test_non_live_modes_always_allowed(mode: RunMode) -> None:
    ensure_mode_allowed(mode, env={})
    assert not live_trading_allowed(mode, env={ALLOW_LIVE_ENV: "1"})


@pytest.mark.parametrize("value", [None, "0", "true", "yes", " 1"])
def test_live_requires_explicit_env_flag(value: str | None) -> None:
    env = {} if value is None else {ALLOW_LIVE_ENV: value}
    assert not live_trading_allowed(RunMode.LIVE, env=env)
    with pytest.raises(LiveTradingNotAllowedError, match=ALLOW_LIVE_ENV):
        ensure_mode_allowed(RunMode.LIVE, env=env)


def test_live_allowed_with_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_mode_allowed(RunMode.LIVE, env={ALLOW_LIVE_ENV: "1"})
    monkeypatch.setenv(ALLOW_LIVE_ENV, "1")
    assert live_trading_allowed(RunMode.LIVE)
    monkeypatch.delenv(ALLOW_LIVE_ENV)
    assert not live_trading_allowed(RunMode.LIVE)
