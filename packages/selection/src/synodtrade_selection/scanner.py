"""IBKR market scanner as a candidate source (e.g. most active / top gainers US stocks).

Uses its own read-only connection to TWS / IB Gateway. IBKR client ids must be unique per
connection; in a pipeline this source uses the pipeline account's host, port and client_id + 3
(market data uses the configured id, trading + 1, IBKR news + 2), standalone
IBKR_CLIENT_ID + 3. The connection is closed after each fetch, so it never holds a client id
for the rest of the run. Scan codes and filter tags are IBKR's own (the full list
comes from `ib.reqScannerParametersAsync()`), e.g. MOST_ACTIVE, TOP_PERC_GAIN,
HOT_BY_VOLUME. Which scanners return data depends on the account's market data
subscriptions.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ib_async import IB, ScannerSubscription, TagValue
from pydantic import BaseModel, ConfigDict, Field

from synodtrade_core.aio import bounded
from synodtrade_core.config import AccountConfig
from synodtrade_core.logging import get_logger
from synodtrade_core.models import Candidate
from synodtrade_selection.sources import CandidateSourceError

log = get_logger(__name__)

CLIENT_ID_OFFSET = 3


class IBKRScannerOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = "ibkr_scanner"
    host: str | None = None  # default: $IBKR_HOST or 127.0.0.1
    port: int | None = None  # default: $IBKR_PORT or 4002
    client_id: int | None = None  # default: $IBKR_CLIENT_ID + 3
    scan_code: str = "MOST_ACTIVE"
    # Several scans over this one connection (e.g. [TOP_PERC_GAIN, HOT_BY_VOLUME]); when
    # set it replaces `scan_code`. Each scan returns up to `rows` stocks.
    scan_codes: list[str] = Field(default_factory=list)
    instrument: str = "STK"
    location: str = "STK.US.MAJOR"
    rows: int = Field(default=25, ge=1, le=50)
    above_price: float | None = Field(default=None, ge=0)
    below_price: float | None = Field(default=None, gt=0)
    above_volume: int | None = Field(default=None, ge=0)
    market_cap_above: float | None = Field(default=None, ge=0)  # millions of USD
    market_cap_below: float | None = Field(default=None, gt=0)
    stock_type: str | None = None  # ALL, CORP, ADR, ETF, REIT, CEF
    filters: dict[str, str] = Field(default_factory=dict)  # extra IBKR filter tags
    currency: str = "USD"
    connect_timeout_s: float = Field(default=10.0, gt=0)
    request_timeout_s: float = Field(default=60.0, gt=0)  # per scan
    # attempts after a timeout (connecting or scanning), each on a fresh connection
    timeout_retries: int = Field(default=1, ge=0, le=3)

    @property
    def codes(self) -> list[str]:
        return list(dict.fromkeys(self.scan_codes)) or [self.scan_code]

    def subscription(self, scan_code: str | None = None) -> ScannerSubscription:
        sub = ScannerSubscription(
            instrument=self.instrument,
            locationCode=self.location,
            scanCode=scan_code or self.scan_code,
            numberOfRows=self.rows,
        )
        # Unset fields keep ScannerSubscription's "no filter" defaults.
        for attr, value in (
            ("abovePrice", self.above_price),
            ("belowPrice", self.below_price),
            ("aboveVolume", self.above_volume),
            ("marketCapAbove", self.market_cap_above),
            ("marketCapBelow", self.market_cap_below),
            ("stockTypeFilter", self.stock_type),
        ):
            if value is not None:
                setattr(sub, attr, value)
        return sub


class IBKRScannerSource:
    def __init__(
        self,
        options: IBKRScannerOptions,
        *,
        env: Mapping[str, str] | None = None,
        ib: IB | None = None,
    ) -> None:
        env = os.environ if env is None else env
        self.options = options
        self.name = options.name
        self.host = options.host or env.get("IBKR_HOST") or "127.0.0.1"
        self.port = options.port or int(env.get("IBKR_PORT") or 4002)
        self.client_id = (
            options.client_id
            if options.client_id is not None
            else int(env.get("IBKR_CLIENT_ID") or 17) + CLIENT_ID_OFFSET
        )
        self._ib = ib or IB()

    async def aclose(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()

    async def fetch(self, as_of: datetime) -> list[Candidate]:
        """Current scanner results (a scanner has no history: `as_of` is not applied).
        A timeout is retried `timeout_retries` times on a fresh connection."""
        attempt = 0
        while True:
            try:
                return await self._fetch()
            except TimeoutError as exc:
                if attempt >= self.options.timeout_retries:
                    raise
                attempt += 1
                log.warning(
                    "selection.scanner_retry",
                    source=self.name,
                    attempt=attempt,
                    error=f"{type(exc).__name__}: {exc}",
                )
            finally:
                await self.aclose()

    async def _fetch(self) -> list[Candidate]:
        if not self._ib.isConnected():
            await self._ib.connectAsync(
                self.host,
                self.port,
                clientId=self.client_id,
                timeout=self.options.connect_timeout_s,
                readonly=True,
            )
        filters = [TagValue(k, v) for k, v in self.options.filters.items()]
        candidates: list[Candidate] = []
        seen: set[str] = set()
        failed: dict[str, str] = {}
        for code in self.options.codes:
            rows: Any = await bounded(
                self._ib.reqScannerDataAsync(self.options.subscription(code), [], filters),
                self.options.request_timeout_s,
                f"IBKR scan {code}",
            )
            if rows is None:
                failed[code] = "scanner request timed out"
                continue
            candidates += self._candidates(rows, code, seen)
        if failed and len(failed) == len(self.options.codes):
            raise CandidateSourceError(f"{self.name}: every scan failed: {failed}")
        if failed:
            log.warning("selection.scans_failed", source=self.name, failed=failed)
        if not candidates:
            log.warning("selection.scanner_empty", source=self.name, scans=self.options.codes)
        return candidates

    def _candidates(self, rows: Any, code: str, seen: set[str]) -> list[Candidate]:
        """Stocks of one scan not seen in an earlier scan; rank as in that scan."""
        candidates: list[Candidate] = []
        for row in rows:
            contract = row.contractDetails.contract
            if contract is None or contract.secType != "STK":
                continue
            if contract.currency and contract.currency != self.options.currency:
                continue
            symbol = contract.symbol.strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            candidates.append(
                Candidate(
                    symbol=symbol,
                    source=self.name,
                    rank=row.rank,
                    note=f"{code} #{row.rank + 1}",
                )
            )
        return candidates


def account_connection(account: AccountConfig) -> dict[str, Any]:
    """Connection options of this source for a pipeline's IBKR account (its own client id,
    so pipelines on different accounts/client ids never collide on one)."""
    return {
        "host": account.host,
        "port": account.port,
        "client_id": account.client_id + CLIENT_ID_OFFSET,
    }


def build_ibkr_scanner_source(options: Mapping[str, Any]) -> IBKRScannerSource:
    """Source factory (entry point `synodtrade.candidate_sources: ibkr_scanner`)."""
    return IBKRScannerSource(IBKRScannerOptions.model_validate(dict(options)))
