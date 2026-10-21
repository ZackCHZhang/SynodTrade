"""Smoke test: the package imports and its metadata is consistent."""

from importlib.metadata import version

import synodtrade_core


def test_version_matches_metadata() -> None:
    assert synodtrade_core.__version__ == version("synodtrade-core")
