import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from quant_database import Database
from quant_pipeline.cli import app, parse_as_of

cli = CliRunner()


def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}"


def init_db(url: str) -> None:
    async def create() -> None:
        db = Database(url)
        await db.create_all()
        await db.dispose()

    asyncio.run(create())


def summary_json(output: str) -> dict[str, object]:
    parsed: dict[str, object] = json.loads(output[output.index("{") : output.rindex("}") + 1])
    return parsed


def test_parse_as_of() -> None:
    assert parse_as_of("2026-10-01T10:00:00-04:00") == datetime(2026, 10, 1, 14, tzinfo=UTC)
    assert parse_as_of("2026-10-01T14:00") == datetime(2026, 10, 1, 14, tzinfo=UTC)  # UTC
    with pytest.raises(Exception, match="ISO-8601"):
        parse_as_of("yesterday")


def test_offline_run(configs: Path, tmp_path: Path) -> None:
    result = cli.invoke(
        app,
        [
            "run",
            "-p",
            "long_term_stocks",
            "--offline",
            "--configs",
            str(configs),
            "--db-url",
            db_url(tmp_path),
            "--init-db",
            "--as-of",
            "2026-10-01T14:00:00+00:00",
            "--log-level",
            "WARNING",
        ],
    )
    assert result.exit_code == 0, result.output
    summary = summary_json(result.stdout)
    assert summary["status"] == "succeeded"
    assert summary["mode"] == "dry_run"
    assert summary["decisions"] == 12


def test_run_subset_and_failure_exit_code(
    configs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = db_url(tmp_path)
    init_db(url)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("IBKR_ACCOUNT", "DU1")
    # not offline and no API key: setup fails, the run is recorded as failed, exit code 1
    result = cli.invoke(
        app,
        [
            "run",
            "-p",
            "long_term_stocks",
            "--dry-run",
            "--stages",
            "decision",
            "--configs",
            str(configs),
            "--db-url",
            url,
        ],
    )
    assert result.exit_code == 1
    assert summary_json(result.stdout)["status"] == "failed"


def test_run_needs_a_database(configs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUANT_DATABASE_URL", raising=False)
    result = cli.invoke(app, ["run", "-p", "long_term_stocks", "--configs", str(configs)])
    assert result.exit_code != 0
    assert "QUANT_DATABASE_URL" in result.output


def test_validate(configs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IBKR_ACCOUNT", "DU1")
    ok = cli.invoke(app, ["validate", "--configs", str(configs)])
    assert ok.exit_code == 0, ok.output
    assert "ok      long_term_stocks" in ok.output

    path = configs / "agents" / "value_investor.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["role"] = "risk"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    bad = cli.invoke(app, ["validate", "-p", "long_term_stocks", "--configs", str(configs)])
    assert bad.exit_code == 1
    assert "cannot use risk agent value_investor" in bad.output


def test_kill_switch(tmp_path: Path) -> None:
    url = db_url(tmp_path)
    init_db(url)
    assert "kill switch off" in cli.invoke(app, ["kill-switch", "status", "--db-url", url]).output
    on = cli.invoke(app, ["kill-switch", "on", "--reason", "broker outage", "--db-url", url])
    assert "kill switch ON (broker outage)" in on.output
    off = cli.invoke(app, ["kill-switch", "off", "--db-url", url])
    assert "kill switch off" in off.output
    bad = cli.invoke(app, ["kill-switch", "maybe", "--db-url", url])
    assert bad.exit_code != 0


def test_offline_bullish_demo_and_bad_llm_style(configs: Path, tmp_path: Path) -> None:
    base = [
        "run",
        "-p",
        "demo_all_modules",
        "--offline",
        "--configs",
        str(configs),
        "--db-url",
        db_url(tmp_path),
        "--init-db",
        "--as-of",
        "2026-10-01T14:00:00Z",
        "--log-level",
        "WARNING",
    ]
    result = cli.invoke(app, [*base, "--offline-llm", "bullish"])
    assert result.exit_code == 0, result.output
    summary = summary_json(result.stdout)
    selection = summary["selection"]
    assert isinstance(selection, dict)
    selected = selection["selected"]
    assert len(selected) == 3
    assert summary["orders"] == dict.fromkeys(selected, "dry_run")
    bad = cli.invoke(app, [*base, "--offline-llm", "euphoric"])
    assert bad.exit_code != 0
    assert "neutral or bullish" in bad.output
