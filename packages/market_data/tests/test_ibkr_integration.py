"""Against a real IB Gateway / TWS (paper). Opt-in:

set SYNODTRADE_TEST_IBKR=1
set IBKR_PORT=4002            (and IBKR_HOST, IBKR_ACCOUNT as needed)
python tasks.py integration
"""

import os
from datetime import timedelta

import pytest

from synodtrade_core.models import Timeframe
from synodtrade_core.timeutil import utcnow
from synodtrade_market_data import IBKRMarketDataProvider

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("SYNODTRADE_TEST_IBKR") != "1", reason="SYNODTRADE_TEST_IBKR!=1"
    ),
]


async def test_paper_gateway_round_trip() -> None:
    provider = IBKRMarketDataProvider(
        host=os.environ.get("IBKR_HOST", "127.0.0.1"),
        port=int(os.environ.get("IBKR_PORT", "4002")),
        client_id=int(os.environ.get("IBKR_CLIENT_ID", "91")),
    )
    await provider.connect()
    try:
        assert await provider.is_healthy()
        aapl = await provider.resolve_instrument("AAPL")
        assert aapl.con_id == 265598
        now = utcnow()
        bars = await provider.fetch_bars(aapl, Timeframe.D1, now - timedelta(days=10), now)
        assert bars
        assert all(b.symbol == "AAPL" for b in bars)
        await provider.fetch_quotes([aapl])
        account_id = os.environ.get("IBKR_ACCOUNT")
        if account_id:
            data = await provider.fetch_account(account_id)
            assert data.account.nav > 0
    finally:
        await provider.disconnect()
