import os
from pathlib import Path

import pytest

from synodtrade_core.envfile import DISABLE_ENV, load_env_file


def test_env_file_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SYNODTRADE_TEST_A=from_file\nQUANT_TEST_B=from_file\n", encoding="utf-8")
    monkeypatch.setenv("SYNODTRADE_TEST_B", "already_set")
    monkeypatch.delenv("SYNODTRADE_TEST_A", raising=False)

    assert not load_env_file(env_file)  # the test suite disables .env loading
    assert "SYNODTRADE_TEST_A" not in os.environ

    monkeypatch.delenv(DISABLE_ENV)
    assert load_env_file(env_file)
    assert os.environ["SYNODTRADE_TEST_A"] == "from_file"
    assert os.environ["SYNODTRADE_TEST_B"] == "already_set"  # real environment wins
    assert not load_env_file(tmp_path / "missing.env")
    monkeypatch.delenv("SYNODTRADE_TEST_A")
