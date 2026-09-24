"""Smoke test: the package imports and its metadata is consistent."""

from importlib.metadata import version

import quant_core


def test_version_matches_metadata() -> None:
    assert quant_core.__version__ == version("quant-core")
