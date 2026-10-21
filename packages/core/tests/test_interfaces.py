from collections.abc import Sequence
from datetime import datetime

from synodtrade_core.interfaces import SentimentSource, Stage
from synodtrade_core.models import PipelineContext, SentimentItem


class NoopStage:
    name = "noop"

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        return ctx


class EmptySource:
    name = "empty"

    async def fetch(self, symbols: Sequence[str], since: datetime) -> list[SentimentItem]:
        return []


def test_protocols_are_structural() -> None:
    assert isinstance(NoopStage(), Stage)
    assert isinstance(EmptySource(), SentimentSource)
    assert not isinstance(object(), Stage)
