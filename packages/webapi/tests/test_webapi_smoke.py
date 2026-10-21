"""Smoke test: the package imports and its metadata is consistent."""

from importlib.metadata import version

import synodtrade_webapi


def test_version_matches_metadata() -> None:
    assert synodtrade_webapi.__version__ == version("synodtrade-webapi")
