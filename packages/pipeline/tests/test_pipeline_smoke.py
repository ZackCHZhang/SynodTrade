"""Smoke test: the package imports and its metadata is consistent."""

from importlib.metadata import version

import quant_core
import quant_database
import quant_decision
import quant_market_data
import quant_pipeline
import quant_risk
import quant_sentiment
import quant_trading


def test_version_matches_metadata() -> None:
    assert quant_pipeline.__version__ == version("quant-pipeline")


def test_dependencies_importable() -> None:
    assert quant_core.__version__ == version("quant-core")
    assert quant_database.__version__ == version("quant-database")
    assert quant_market_data.__version__ == version("quant-market-data")
    assert quant_sentiment.__version__ == version("quant-sentiment")
    assert quant_decision.__version__ == version("quant-decision")
    assert quant_risk.__version__ == version("quant-risk")
    assert quant_trading.__version__ == version("quant-trading")
