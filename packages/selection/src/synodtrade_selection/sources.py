"""Candidate sources: where the symbols to choose from come from.

Every source implements core's `CandidateSource` (`name`, `async fetch(as_of)`) and is
registered under the entry point group `synodtrade.candidate_sources`:

- `static`: a fixed list of symbols from the pipeline YAML;
- `ibkr_scanner`: an IBKR market scanner (see synodtrade_selection.scanner).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from synodtrade_core.models import Candidate


class CandidateSourceError(RuntimeError):
    """A source could not deliver candidates (connection, subscription, bad response)."""


def normalise_symbols(values: Iterable[str]) -> list[str]:
    """Upper-case, strip, drop empties and duplicates (first occurrence wins)."""
    out: list[str] = []
    for value in values:
        symbol = value.strip().upper()
        if symbol and symbol not in out:
            out.append(symbol)
    return out


class StaticSourceOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = "static"
    symbols: list[str] = Field(min_length=1)
    note: str | None = None

    @field_validator("symbols")
    @classmethod
    def _normalise(cls, value: list[str]) -> list[str]:
        return normalise_symbols(value)


class StaticCandidateSource:
    """A fixed list; the order is the rank."""

    def __init__(self, options: StaticSourceOptions) -> None:
        self.options = options
        self.name = options.name

    async def fetch(self, as_of: datetime) -> list[Candidate]:
        return [
            Candidate(symbol=s, source=self.name, rank=i, note=self.options.note)
            for i, s in enumerate(self.options.symbols)
        ]


class FakeCandidateSource:
    """Serves the given symbols (or fails), for tests and offline runs."""

    def __init__(self, name: str, symbols: Iterable[str] = (), *, fail: bool = False) -> None:
        self.name = name
        self.symbols = normalise_symbols(symbols)
        self._fail = fail
        self.requests: list[datetime] = []
        self.closed = False

    async def fetch(self, as_of: datetime) -> list[Candidate]:
        self.requests.append(as_of)
        if self._fail:
            raise CandidateSourceError(f"{self.name}: simulated failure")
        return [
            Candidate(symbol=s, source=self.name, rank=i, note="offline")
            for i, s in enumerate(self.symbols)
        ]

    async def aclose(self) -> None:
        self.closed = True


def build_static_source(options: Mapping[str, Any]) -> StaticCandidateSource:
    """Source factory (entry point `synodtrade.candidate_sources: static`)."""
    return StaticCandidateSource(StaticSourceOptions.model_validate(dict(options)))
