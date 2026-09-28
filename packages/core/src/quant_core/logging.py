"""structlog setup: JSON lines, UTC timestamps plus local display time, run_id on every line.

Use `bind_run(run_id, pipeline)` around a pipeline run; every log call inside it (including
in other packages and tasks spawned from it) carries those fields via contextvars.
"""

from __future__ import annotations

import io
import logging
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, TextIO, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from structlog.typing import EventDict, FilteringBoundLogger, Processor, WrappedLogger

from quant_core.timeutil import DISPLAY_TZ, utcnow

_SECRET_KEY = re.compile(
    r"^(.*_)?(api_key|apikey|secret|client_secret|password|passwd|token|access_token|"
    r"auth_token|authorization)$",
    re.IGNORECASE,
)
REDACTED = "***"


class _CurrentStderr(io.TextIOBase):
    """Writes to whatever `sys.stderr` is at write time, so logging survives stderr being
    replaced (and a replaced stream being closed), e.g. under test runners or daemons."""

    def write(self, text: str) -> int:
        return sys.stderr.write(text)

    def flush(self) -> None:
        sys.stderr.flush()


def redact_secrets(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    for key in event_dict:
        if _SECRET_KEY.match(key):
            event_dict[key] = REDACTED
    return event_dict


def display_time(tz: ZoneInfo) -> Processor:
    def add(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
        ts = event_dict.get("ts")
        moment = datetime.fromisoformat(ts) if isinstance(ts, str) else utcnow()
        event_dict["ts_local"] = moment.astimezone(tz).isoformat(timespec="seconds")
        return event_dict

    return add


def configure_logging(
    level: str = "INFO",
    *,
    json: bool = True,
    display_tz: ZoneInfo = DISPLAY_TZ,
    stream: TextIO | None = None,
) -> None:
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        display_time(display_tz),
        redact_secrets,
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=stream or cast(TextIO, _CurrentStderr())),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None, **initial: Any) -> FilteringBoundLogger:
    logger: FilteringBoundLogger = structlog.get_logger(name)
    return logger.bind(**initial) if initial else logger


@contextmanager
def bind_run(run_id: UUID, pipeline: str | None = None) -> Iterator[None]:
    fields: dict[str, Any] = {"run_id": str(run_id)}
    if pipeline is not None:
        fields["pipeline"] = pipeline
    with structlog.contextvars.bound_contextvars(**fields):
        yield
