"""Quick read-only check of the TWS / IB Gateway API connection.

    poetry run python scripts/ibkr_check.py [--port 7497]

Connects read-only with a spare client id, prints the managed accounts (and whether they
are paper accounts), server time, AAPL's contract and the last few daily bars. Places no
orders.
"""

from __future__ import annotations

import argparse
import asyncio

from ib_async import IB, Stock


async def main(host: str, port: int, client_id: int) -> int:
    ib = IB()
    try:
        await ib.connectAsync(host, port, clientId=client_id, timeout=10, readonly=True)
    except Exception as exc:
        print(f"CONNECT FAILED {host}:{port}: {type(exc).__name__}: {exc}")
        print("-> TWS: Global Configuration > API > Settings > Enable ActiveX and Socket Clients")
        return 1
    try:
        accounts = ib.managedAccounts()
        print("connected:", f"{host}:{port}", "server time:", await ib.reqCurrentTimeAsync())
        for account in accounts:
            kind = "PAPER" if account.upper().startswith("D") else "LIVE (!)"
            print(f"account: {account}  {kind}")
        ib.reqMarketDataType(3)  # delayed if there is no real-time subscription
        [aapl] = await ib.qualifyContractsAsync(Stock("AAPL", "SMART", "USD"))
        print("AAPL conId:", getattr(aapl, "conId", None))
        bars = await ib.reqHistoricalDataAsync(
            aapl,
            endDateTime="",
            durationStr="5 D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=2,
        )
        print(f"daily bars: {len(bars)}", [(str(b.date), b.close) for b in bars[-3:]])
        news = await ib.reqNewsProvidersAsync()
        print("news providers:", [p.code for p in news])
    finally:
        ib.disconnect()
    return 0 if accounts else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7497)
    parser.add_argument("--client-id", type=int, default=91)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.host, args.port, args.client_id)))
