"""Sanity checks for the deployment files (docker is not available in unit tests)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_compose_wires_scheduler_to_database_and_gateway() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert set(services) == {"postgres", "ib-gateway", "scheduler"}
    scheduler = services["scheduler"]
    assert scheduler["depends_on"]["postgres"]["condition"] == "service_healthy"
    env = scheduler["environment"]
    assert env["IBKR_HOST"] == "ib-gateway"
    assert "@postgres:5432/" in env["SYNODTRADE_DATABASE_URL"]
    assert env["SYNODTRADE_DATABASE_URL"].startswith("postgresql+asyncpg://")
    assert services["ib-gateway"]["environment"]["TRADING_MODE"] == "${TRADING_MODE:-paper}"
    for service in services.values():  # nothing is exposed beyond localhost
        for port in service.get("ports", []):
            assert port.startswith("127.0.0.1:"), port


def test_dockerfile_runs_migrations_then_scheduler() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12" in dockerfile
    assert "poetry install --without dev" in dockerfile
    assert "synodtrade-db upgrade && exec synodtrade-scheduler run" in dockerfile
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert ".env" in ignored  # secrets never baked into the image
