"""Smoke test: the package imports and its metadata is consistent."""

from importlib.metadata import version

import quant_webapi


def test_version_matches_metadata() -> None:
    assert quant_webapi.__version__ == version("quant-webapi")
