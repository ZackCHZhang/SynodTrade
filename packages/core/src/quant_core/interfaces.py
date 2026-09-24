"""Protocols implemented by other packages."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from quant_core.models import PipelineContext, SentimentItem


@runtime_checkable
class Stage(Protocol):
    """One pipeline step. Reads earlier outputs from the context and appends its own."""

    name: str

    async def run(self, ctx: PipelineContext) -> PipelineContext: ...


@runtime_checkable
class SentimentSource(Protocol):
    name: str

    async def fetch(self, symbols: Sequence[str], since: datetime) -> list[SentimentItem]: ...
