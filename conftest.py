"""Workspace-wide pytest hooks.

- Everything under tests/integration/ is marked `integration`.
- `integration` tests may use the network; all other tests are restricted to loopback
  by pytest-socket (`--allow-hosts` in pyproject.toml).
"""

from pathlib import Path

import pytest

INTEGRATION_DIR = Path(__file__).parent / "tests" / "integration"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.path.is_relative_to(INTEGRATION_DIR):
            item.add_marker(pytest.mark.integration)
        if item.get_closest_marker("integration"):
            item.add_marker(pytest.mark.enable_socket)


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's real .env (API keys) must never reach the tests."""
    monkeypatch.setenv("SYNODTRADE_NO_DOTENV", "1")
