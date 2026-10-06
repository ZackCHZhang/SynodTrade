"""Candidate sources and stage option validation (no network: IB is a stub)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from ib_async import ContractDetails, Forex, ScanData, Stock
from pydantic import ValidationError

from quant_core.registry import AGENTS, CANDIDATE_SOURCES, STAGES
from quant_selection import (
    CandidateSourceConfig,
    CandidateSourceError,
    FakeCandidateSource,
    IBKRScannerOptions,
    IBKRScannerSource,
    SelectionAgent,
    SelectionOptions,
    StaticCandidateSource,
    build_selection_stage,
)
from quant_selection.scanner import build_ibkr_scanner_source
from quant_selection.sources import build_static_source

NOW = datetime(2026, 9, 24, 14, 0, tzinfo=UTC)


def test_entry_points() -> None:
    assert STAGES.get("selection") is build_selection_stage
    assert AGENTS.get("selection") is SelectionAgent
    assert CANDIDATE_SOURCES.get("static") is build_static_source
    assert CANDIDATE_SOURCES.get("ibkr_scanner") is build_ibkr_scanner_source


async def test_static_source() -> None:
    source = build_static_source({"symbols": [" aapl", "MSFT", "AAPL", ""], "note": "core"})
    assert isinstance(source, StaticCandidateSource)
    got = await source.fetch(NOW)
    assert [(c.symbol, c.rank, c.source, c.note) for c in got] == [
        ("AAPL", 0, "static", "core"),
        ("MSFT", 1, "static", "core"),
    ]
    with pytest.raises(ValidationError):
        build_static_source({"symbols": []})


async def test_fake_source() -> None:
    fake = FakeCandidateSource("scan", ["nvda", "amd"])
    assert [c.symbol for c in await fake.fetch(NOW)] == ["NVDA", "AMD"]
    await fake.aclose()
    assert fake.closed
    assert fake.requests == [NOW]
    with pytest.raises(CandidateSourceError, match="simulated"):
        await FakeCandidateSource("scan", fail=True).fetch(NOW)


def test_selection_options_validation() -> None:
    options = SelectionOptions.model_validate(
        {"sources": [{"type": "ibkr_scanner", "scan_code": "TOP_PERC_GAIN", "rows": 10}]}
    )
    entry = options.sources[0]
    assert entry.source_name == "ibkr_scanner"
    assert entry.source_options() == {
        "scan_code": "TOP_PERC_GAIN",
        "rows": 10,
        "name": "ibkr_scanner",
    }
    with pytest.raises(ValidationError, match="unique"):
        SelectionOptions.model_validate(
            {"sources": [{"type": "ibkr_scanner"}, {"type": "ibkr_scanner"}]}
        )
    with pytest.raises(ValidationError, match="unique"):
        SelectionOptions.model_validate({"sources": [{"type": "static", "name": "universe"}]})
    two = SelectionOptions.model_validate(
        {"sources": [{"type": "ibkr_scanner"}, {"type": "ibkr_scanner", "name": "gainers"}]}
    )
    assert [s.source_name for s in two.sources] == ["ibkr_scanner", "gainers"]
    with pytest.raises(ValidationError, match="candidate sources"):
        SelectionOptions.model_validate({"include_universe": False})
    with pytest.raises(ValidationError):
        CandidateSourceConfig.model_validate({"type": "Bad-Name"})


# ------------------------------------------------------------------ IBKR scanner


def scan_row(rank: int, contract: Any) -> ScanData:
    return ScanData(
        rank=rank,
        contractDetails=ContractDetails(contract=contract),
        distance="",
        benchmark="",
        projection="",
        legsStr="",
    )


@dataclass
class StubIB:
    rows: Any = None
    connected: bool = False
    connects: list[dict[str, Any]] = field(default_factory=list)
    requests: list[tuple[Any, list[Any], list[Any]]] = field(default_factory=list)

    def isConnected(self) -> bool:  # noqa: N802 - ib_async API
        return self.connected

    async def connectAsync(self, host: str, port: int, **kwargs: Any) -> None:  # noqa: N802
        self.connected = True
        self.connects.append({"host": host, "port": port, **kwargs})

    def disconnect(self) -> None:
        self.connected = False

    async def reqScannerDataAsync(self, sub: Any, options: Any, filters: Any) -> Any:  # noqa: N802
        self.requests.append((sub, options, filters))
        return self.rows


async def test_scanner_fetch() -> None:
    ib = StubIB(
        rows=[
            scan_row(0, Stock("NVDA", "SMART", "USD")),
            scan_row(1, Forex("EURUSD")),  # not a stock
            scan_row(2, Stock("SAP", "SMART", "EUR")),  # other currency
            scan_row(3, Stock("nvda", "SMART", "USD")),  # duplicate
            scan_row(4, Stock("AMD", "SMART", "USD")),
        ]
    )
    options = IBKRScannerOptions(
        scan_code="TOP_PERC_GAIN",
        rows=5,
        above_price=10,
        market_cap_above=10_000,
        stock_type="CORP",
        filters={"avgVolumeAbove": "1000000"},
    )
    source = IBKRScannerSource(options, env={"IBKR_PORT": "7497", "IBKR_CLIENT_ID": "20"}, ib=ib)  # type: ignore[arg-type]
    got = await source.fetch(NOW)
    assert [(c.symbol, c.rank, c.note) for c in got] == [
        ("NVDA", 0, "TOP_PERC_GAIN #1"),
        ("AMD", 4, "TOP_PERC_GAIN #5"),
    ]
    assert ib.connects == [
        {"host": "127.0.0.1", "port": 7497, "clientId": 23, "timeout": 10.0, "readonly": True}
    ]
    sub, _, filters = ib.requests[0]
    assert (sub.scanCode, sub.numberOfRows, sub.abovePrice, sub.marketCapAbove) == (
        "TOP_PERC_GAIN",
        5,
        10,
        10_000,
    )
    assert sub.stockTypeFilter == "CORP"
    assert sub.belowPrice > 1e300  # unset filters keep IBKR's "no filter" value
    assert [(t.tag, t.value) for t in filters] == [("avgVolumeAbove", "1000000")]

    await source.fetch(NOW)
    assert len(ib.connects) == 1  # connection reused
    await source.aclose()
    assert not ib.connected
    await source.aclose()  # idempotent


async def test_scanner_timeout_and_empty() -> None:
    source = IBKRScannerSource(IBKRScannerOptions(), env={}, ib=StubIB(rows=None))  # type: ignore[arg-type]
    assert source.port == 4002
    assert source.client_id == 20
    with pytest.raises(CandidateSourceError, match="timed out"):
        await source.fetch(NOW)
    empty = IBKRScannerSource(IBKRScannerOptions(client_id=5), env={}, ib=StubIB(rows=[]))  # type: ignore[arg-type]
    assert empty.client_id == 5
    assert await empty.fetch(NOW) == []


def test_scanner_factory() -> None:
    source = build_ibkr_scanner_source({"name": "gainers", "scan_code": "TOP_PERC_GAIN"})
    assert source.name == "gainers"
    with pytest.raises(ValidationError):
        build_ibkr_scanner_source({"rows": 500})


async def test_scanner_runs_several_scans_on_one_connection() -> None:
    ib = StubIB(
        rows=[scan_row(0, Stock("NVDA", "SMART", "USD")), scan_row(1, Stock("AMD", "SMART", "USD"))]
    )
    options = IBKRScannerOptions(scan_codes=["TOP_PERC_GAIN", "HOT_BY_VOLUME", "TOP_PERC_GAIN"])
    source = IBKRScannerSource(options, env={}, ib=ib)  # type: ignore[arg-type]
    found = await source.fetch(NOW)
    assert len(ib.connects) == 1
    assert [r[0].scanCode for r in ib.requests] == ["TOP_PERC_GAIN", "HOT_BY_VOLUME"]
    # a symbol found by an earlier scan is not repeated
    assert [(c.symbol, c.note) for c in found] == [
        ("NVDA", "TOP_PERC_GAIN #1"),
        ("AMD", "TOP_PERC_GAIN #2"),
    ]
    with pytest.raises(CandidateSourceError, match="every scan failed"):
        await IBKRScannerSource(options, env={}, ib=StubIB(rows=None)).fetch(NOW)  # type: ignore[arg-type]
