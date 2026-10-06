"""SEC EDGAR client (free, no API key): XBRL company facts, filing index and Form 4 documents.

The SEC asks every client to identify itself with a User-Agent containing a contact email
(environment variable SEC_EDGAR_USER_AGENT, e.g. "Jane Doe jane@example.com") and to stay
below 10 requests per second.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from quant_core.logging import get_logger

log = get_logger(__name__)

ENV_USER_AGENT = "SEC_EDGAR_USER_AGENT"


class SecEdgarError(RuntimeError):
    pass


class SecEdgarOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data_url: str = "https://data.sec.gov"
    www_url: str = "https://www.sec.gov"
    timeout_s: float = Field(default=30.0, gt=0)
    max_requests_per_second: float = Field(default=8.0, gt=0, le=10)
    retries: int = Field(default=3, ge=0, le=10)
    insider_window_days: int = Field(default=90, ge=1, le=365)
    max_form4: int = Field(default=15, ge=0, le=100)  # Form 4 documents read per symbol


def sec_ticker(symbol: str) -> str:
    """IBKR style ("BRK B") to SEC style ("BRK-B")."""
    return symbol.strip().upper().replace(" ", "-").replace(".", "-")


class SecEdgarClient:
    def __init__(
        self,
        user_agent: str,
        options: SecEdgarOptions | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Any = asyncio.sleep,
    ) -> None:
        if "@" not in user_agent:
            raise SecEdgarError(
                f"{ENV_USER_AGENT} must contain a contact email, e.g. 'Jane Doe jane@example.com'"
            )
        self.options = options or SecEdgarOptions()
        # sent with every request, also through an injected client
        self._headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        self._client = client or httpx.AsyncClient(
            timeout=self.options.timeout_s, follow_redirects=True
        )
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._tickers: dict[str, tuple[int, str]] | None = None

    @classmethod
    def from_env(
        cls, options: SecEdgarOptions | None = None, env: Mapping[str, str] | None = None
    ) -> SecEdgarClient:
        env = os.environ if env is None else env
        agent = env.get(ENV_USER_AGENT, "").strip()
        if not agent:
            raise SecEdgarError(f"environment variable {ENV_USER_AGENT} is not set")
        return cls(agent, options)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _throttle(self) -> None:
        async with self._lock:
            wait = self._last + 1 / self.options.max_requests_per_second - time.monotonic()
            if wait > 0:
                await self._sleep(wait)
            self._last = time.monotonic()

    async def _get(self, url: str) -> httpx.Response | None:
        """GET with throttling and retries; None for 404 (no such document)."""
        for attempt in range(self.options.retries + 1):
            await self._throttle()
            try:
                response = await self._client.get(url, headers=self._headers)
            except httpx.TransportError as exc:
                if attempt == self.options.retries:
                    raise SecEdgarError(f"GET {url}: {type(exc).__name__}: {exc}") from exc
                await self._sleep(2**attempt)
                continue
            if response.status_code == 404:
                return None
            if response.status_code in (429, 500, 502, 503, 504) and attempt < self.options.retries:
                await self._sleep(2**attempt)
                continue
            if response.status_code >= 400:
                raise SecEdgarError(f"GET {url}: HTTP {response.status_code}")
            return response
        raise SecEdgarError(f"GET {url}: retries exhausted")  # pragma: no cover

    async def _json(self, url: str) -> dict[str, Any] | None:
        response = await self._get(url)
        if response is None:
            return None
        data = response.json()
        if not isinstance(data, dict):
            raise SecEdgarError(f"GET {url}: unexpected response shape")
        return data

    async def lookup(self, symbol: str) -> tuple[int, str] | None:
        """(CIK, company name) of a ticker, None if the SEC does not know it."""
        if self._tickers is None:
            data = await self._json(f"{self.options.www_url}/files/company_tickers.json")
            self._tickers = {
                str(row["ticker"]).upper(): (int(row["cik_str"]), str(row.get("title", "")))
                for row in (data or {}).values()
            }
        return self._tickers.get(sec_ticker(symbol))

    async def company_facts(self, cik: int) -> dict[str, Any] | None:
        return await self._json(f"{self.options.data_url}/api/xbrl/companyfacts/CIK{cik:010d}.json")

    async def submissions(self, cik: int) -> dict[str, Any] | None:
        return await self._json(f"{self.options.data_url}/submissions/CIK{cik:010d}.json")

    async def filing_document(self, cik: int, accession: str, document: str) -> str | None:
        """A filing's raw document; for Form 4 the XML (not the xsl-rendered HTML)."""
        name = document.rsplit("/", 1)[-1]
        url = (
            f"{self.options.www_url}/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{name}"
        )
        response = await self._get(url)
        return response.text if response is not None else None
