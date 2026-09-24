"""Smoke test: the package imports and its metadata is consistent."""

from importlib.metadata import version

import quant_core
import quant_database
import quant_decision


def test_version_matches_metadata() -> None:
    assert quant_decision.__version__ == version("quant-decision")


def test_dependencies_importable() -> None:
    assert quant_core.__version__ == version("quant-core")
    assert quant_database.__version__ == version("quant-database")
