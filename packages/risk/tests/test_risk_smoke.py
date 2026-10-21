"""Smoke test: the package imports and its metadata is consistent."""

from importlib.metadata import version

import synodtrade_core
import synodtrade_database
import synodtrade_risk


def test_version_matches_metadata() -> None:
    assert synodtrade_risk.__version__ == version("synodtrade-risk")


def test_dependencies_importable() -> None:
    assert synodtrade_core.__version__ == version("synodtrade-core")
    assert synodtrade_database.__version__ == version("synodtrade-database")
