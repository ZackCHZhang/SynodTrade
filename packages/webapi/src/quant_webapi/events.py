"""Live run events: a structlog processor that copies every log event carrying a `run_id`
into an in-memory buffer per run, which the web UI streams (Server-Sent Events).

Covers every run in this process: runs started from the UI and runs fired by the embedded
scheduler. Runs in other processes (CLI, standalone scheduler) are only visible through the
database.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from typing import Any

import structlog
from structlog.typing import EventDict, WrappedLogger

END_EVENTS = frozenset({"pipeline.finish", "pipeline.cancelled"})
JOB_KEY = "web_job"


def _json_safe(event: EventDict) -> dict[str, Any]:
    safe: dict[str, Any] = json.loads(json.dumps(dict(event), default=str))
    return safe


class RunBuffer:
    def __init__(self, max_events: int) -> None:
        self.events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self.seq = 0
        self.ended = False
        self.subscribers: set[asyncio.Queue[dict[str, Any] | None]] = set()


class EventHub:
    def __init__(self, *, max_runs: int = 100, max_events: int = 5000) -> None:
        self._runs: OrderedDict[str, RunBuffer] = OrderedDict()
        self._max_runs = max_runs
        self._max_events = max_events
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: int | None = None
        self.job_runs: dict[str, str] = {}  # web job id -> run id
        self._job_waiters: dict[str, asyncio.Event] = {}
        self._previous: list[Any] | None = None

    # ------------------------------------------------------------ wiring

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._loop_thread = threading.get_ident()

    def install(self, output_level: str = "INFO") -> None:
        """Add the tap to the current structlog configuration, before the renderer.

        Logging must be configured at INFO (or more verbose) so the tap sees run progress;
        `output_level` then only limits what is printed.
        """
        threshold = logging.getLevelNamesMapping().get(output_level.upper(), logging.INFO)

        def drop_quiet(_: WrappedLogger, level: str, event_dict: EventDict) -> EventDict:
            name = str(event_dict.get("level", level)).upper()
            if logging.getLevelNamesMapping().get(name, logging.INFO) < threshold:
                raise structlog.DropEvent
            return event_dict

        drop_quiet.__qualname__ = "EventHub.drop_quiet"
        self._previous = list(structlog.get_config()["processors"])
        processors = [
            p
            for p in structlog.get_config()["processors"]
            if getattr(p, "__self__", None) is not self
            and getattr(p, "__qualname__", "") != "EventHub.drop_quiet"
        ]
        at = max(len(processors) - 1, 0)  # before the renderer
        processors[at:at] = [self.processor, drop_quiet]
        structlog.configure(processors=processors)

    def uninstall(self) -> None:
        """Restore the structlog processors that were active before `install`."""
        if self._previous is not None:
            structlog.configure(processors=self._previous)
            self._previous = None

    def processor(self, _: WrappedLogger, level: str, event_dict: EventDict) -> EventDict:
        run_id = event_dict.get("run_id")
        if run_id:
            event = _json_safe(event_dict)
            event.setdefault("level", level)
            if self._loop is None or threading.get_ident() == self._loop_thread:
                self._publish(str(run_id), event)
            else:
                self._loop.call_soon_threadsafe(self._publish, str(run_id), event)
        return event_dict

    # ------------------------------------------------------------ buffers

    def _buffer(self, run_id: str) -> RunBuffer:
        buf = self._runs.get(run_id)
        if buf is None:
            buf = RunBuffer(self._max_events)
            self._runs[run_id] = buf
            while len(self._runs) > self._max_runs:
                old_id, old = next(iter(self._runs.items()))
                if old.subscribers:
                    break
                del self._runs[old_id]
        return buf

    def _publish(self, run_id: str, event: dict[str, Any]) -> None:
        buf = self._buffer(run_id)
        buf.seq += 1
        event["seq"] = buf.seq
        buf.events.append(event)
        job = event.get(JOB_KEY)
        if job and job not in self.job_runs:
            self.job_runs[job] = run_id
            waiter = self._job_waiters.pop(job, None)
            if waiter is not None:
                waiter.set()
        if event.get("event") in END_EVENTS:
            buf.ended = True
        for queue in list(buf.subscribers):
            queue.put_nowait(event)
            if buf.ended:
                queue.put_nowait(None)

    def has_run(self, run_id: str) -> bool:
        return run_id in self._runs

    def is_live(self, run_id: str) -> bool:
        buf = self._runs.get(run_id)
        return buf is not None and not buf.ended

    def history(self, run_id: str) -> list[dict[str, Any]]:
        buf = self._runs.get(run_id)
        return list(buf.events) if buf is not None else []

    def stage_progress(self, run_id: str) -> dict[str, dict[str, Any]]:
        """{stage: {status: running|ok|failed|failed_skipped, seconds?}} from the events."""
        progress: dict[str, dict[str, Any]] = {}
        for event in self.history(run_id):
            name = event.get("event")
            stage = event.get("stage")
            if name == "pipeline.stage_start" and stage:
                progress[stage] = {"status": "running", "started": event.get("ts")}
            elif name == "pipeline.stage_done" and stage:
                progress[stage] = {
                    **progress.get(stage, {}),
                    "status": event.get("status"),
                    "seconds": event.get("seconds"),
                }
        return progress

    def mark_ended(self, run_id: str) -> None:
        buf = self._runs.get(run_id)
        if buf is None or buf.ended:
            return
        buf.ended = True
        for queue in list(buf.subscribers):
            queue.put_nowait(None)

    async def wait_for_job(self, job_id: str) -> str:
        """The run id of a web job, once its first event arrived (callers add a timeout)."""
        if job_id not in self.job_runs:
            await self._job_waiters.setdefault(job_id, asyncio.Event()).wait()
        return self.job_runs[job_id]

    # ------------------------------------------------------------ streaming

    async def stream(self, run_id: str, after: int = 0) -> AsyncIterator[dict[str, Any] | None]:
        """Past events (seq > after), then live ones; stops once the run has ended.

        Yields None after every 15 s of silence so the caller can send a keep-alive.
        """
        buf = self._buffer(run_id)
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        buf.subscribers.add(queue)
        try:
            for event in list(buf.events):
                if event["seq"] > after:
                    yield event
            if buf.ended:
                return
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), 15)
                except TimeoutError:
                    yield None
                    continue
                if item is None:
                    return
                if item["seq"] > after:
                    yield item
        finally:
            buf.subscribers.discard(queue)
