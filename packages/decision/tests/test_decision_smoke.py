"""Smoke test: the package imports and its metadata is consistent."""

from importlib.metadata import version

import synodtrade_core
import synodtrade_database
import synodtrade_decision


def test_version_matches_metadata() -> None:
    assert synodtrade_decision.__version__ == version("synodtrade-decision")


def test_dependencies_importable() -> None:
    assert synodtrade_core.__version__ == version("synodtrade-core")
    assert synodtrade_database.__version__ == version("synodtrade-database")
