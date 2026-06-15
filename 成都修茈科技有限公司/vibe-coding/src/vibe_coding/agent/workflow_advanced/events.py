"""Event bus used by :class:`AdvancedWorkflowExecutor` for triggers.

Single-process pub/sub with both **sync** and **async** wait-for
helpers so the same bus drives the synchronous executor (uses a
``threading.Condition``) and the asyncio executor (uses
``asyncio.Event``).

External producers (HTTP webhook, file watcher, cron) call
:meth:`publish` to push an event; nodes block on
:meth:`wait_for` / :meth:`async_wait_for` until a matching event
arrives.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Deque


@dataclass(slots=True)
class WorkflowEvent:
    """One event published to the bus."""

    topic: str
    payload: Any = None
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "payload": self.payload,
            "timestamp": float(self.timestamp),
            "metadata": dict(self.metadata),
        }


SyncFilter = Callable[[Any], bool]


class EventBus:
    """Thread- and asyncio-safe in-memory event bus.

    Designed for the single-process common case (CI runner, IDE
    plugin, Web UI). For cross-process / cross-machine deployment,
    pipe events into your queue of choice (Redis, NATS, Kafka) and
    have the producer call :meth:`publish` on the local bus.
    """

    def __init__(self, *, history: int = 100) -> None:
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._history: Deque[WorkflowEvent] = deque(maxlen=history)
        self._async_loops: dict[int, list[asyncio.Future]] = {}

    # --------------------------------------------------------- producer

    def publish(self, topic: str, payload: Any = None, **metadata: Any) -> WorkflowEvent:
        event = WorkflowEvent(topic=topic, payload=payload, metadata=dict(metadata))
        with self._cond:
            self._history.append(event)
            self._cond.notify_all()
        # Notify async waiters living in different event loops.
        for futures in list(self._async_loops.values()):
            for fut in list(futures):
                if fut.done():
                    continue
                loop = fut.get_loop()
                loop.call_soon_threadsafe(_safe_set, fut, event)
        return event

    # --------------------------------------------------------- sync waiter

    def wait_for(
        self,
        topic: str,
        *,
        timeout_s: float = 60.0,
        filter_fn: SyncFilter | None = None,
        consume_existing: bool = True,
    ) -> WorkflowEvent | None:
        """Block until an event matching ``topic`` arrives.

        ``consume_existing=True`` (default) inspects the history first
        so an event published *before* the wait started is still
        delivered. Set to ``False`` for "only new events" semantics.
        """
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        with self._cond:
            if consume_existing:
                for event in list(self._history):
                    if event.topic != topic:
                        continue
                    if filter_fn is not None and not _safe_filter(filter_fn, event.payload):
                        continue
                    return event
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(timeout=remaining)
                # Inspect the newest event.
                for event in reversed(self._history):
                    if event.topic != topic:
                        continue
                    if filter_fn is not None and not _safe_filter(filter_fn, event.payload):
                        continue
                    return event

    # --------------------------------------------------------- async waiter

    async def async_wait_for(
        self,
        topic: str,
        *,
        timeout_s: float = 60.0,
        filter_fn: SyncFilter | None = None,
        consume_existing: bool = True,
    ) -> WorkflowEvent | None:
        loop = asyncio.get_event_loop()
        if consume_existing:
            with self._lock:
                for event in list(self._history):
                    if event.topic != topic:
                        continue
                    if filter_fn is not None and not _safe_filter(filter_fn, event.payload):
                        continue
                    return event
        future: asyncio.Future = loop.create_future()
        with self._lock:
            self._async_loops.setdefault(id(loop), []).append(future)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(future, timeout=timeout_s)
                except asyncio.TimeoutError:
                    return None
                if event.topic != topic:
                    future = loop.create_future()
                    with self._lock:
                        self._async_loops.setdefault(id(loop), []).append(future)
                    continue
                if filter_fn is not None and not _safe_filter(filter_fn, event.payload):
                    future = loop.create_future()
                    with self._lock:
                        self._async_loops.setdefault(id(loop), []).append(future)
                    continue
                return event
        finally:
            with self._lock:
                bucket = self._async_loops.get(id(loop)) or []
                if future in bucket:
                    bucket.remove(future)

    # --------------------------------------------------------- helpers

    def history(self, *, topic: str | None = None, limit: int | None = None) -> list[WorkflowEvent]:
        with self._lock:
            items = list(self._history)
        if topic is not None:
            items = [e for e in items if e.topic == topic]
        if limit is not None:
            items = items[-int(limit):]
        return items


# ----------------------------------------------------------------- helpers


def _safe_set(future: asyncio.Future, event: WorkflowEvent) -> None:
    if future.done():
        return
    try:
        future.set_result(event)
    except asyncio.InvalidStateError:
        pass


def _safe_filter(filter_fn: SyncFilter, payload: Any) -> bool:
    try:
        return bool(filter_fn(payload))
    except Exception:  # noqa: BLE001
        return False


__all__ = ["EventBus", "WorkflowEvent"]
