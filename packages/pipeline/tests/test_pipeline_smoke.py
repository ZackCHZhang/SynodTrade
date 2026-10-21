"""Smoke test: the package imports and its metadata is consistent."""

from importlib.metadata import version

import synodtrade_core
import synodtrade_database
import synodtrade_decision
import synodtrade_market_data
import synodtrade_pipeline
import synodtrade_risk
import synodtrade_sentiment
import synodtrade_trading


def test_version_matches_metadata() -> None:
    assert synodtrade_pipeline.__version__ == version("synodtrade-pipeline")


def test_dependencies_importable() -> None:
    assert synodtrade_core.__version__ == version("synodtrade-core")
    assert synodtrade_database.__version__ == version("synodtrade-database")
    assert synodtrade_market_data.__version__ == version("synodtrade-market-data")
    assert synodtrade_sentiment.__version__ == version("synodtrade-sentiment")
    assert synodtrade_decision.__version__ == version("synodtrade-decision")
    assert synodtrade_risk.__version__ == version("synodtrade-risk")
    assert synodtrade_trading.__version__ == version("synodtrade-trading")
