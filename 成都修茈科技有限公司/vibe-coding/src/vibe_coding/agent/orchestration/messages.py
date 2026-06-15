"""Message + bus primitives used by the multi-agent orchestrator.

Why a custom mini-bus rather than ``asyncio.Queue`` / Celery / Redis?

- We want **deterministic** test runs: the orchestrator sequence has to
  be reproducible from a fixture.
- We want **zero deps**: vibe-coding's value prop is "drop into any
  project", and an in-memory bus does the job.
- We want **structured payloads** so the agent UI / Web view can show
  a chat-style transcript without redaction.

The bus is single-process; cross-machine setups should pipe the
messages through a queue of their choice (Redis, NATS, …) by reading
the bus log via :meth:`MessageBus.snapshot`.
"""

from __future__ import annotations

import itertools
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable

_MESSAGE_ID = itertools.count(1)


@dataclass(slots=True)
class AgentMessage:
    """One message between two roles.

    ``kind`` is intentionally open-ended (``"plan"``, ``"task"``, ``"patch"``,
    ``"review"``, ``"failure"``, …) so new roles can introduce their own
    vocabulary without modifying this class.
    """

    sender: str
    recipient: str
    kind: str
    content: dict[str, Any] = field(default_factory=dict)
    msg_id: str = field(default_factory=lambda: f"m-{next(_MESSAGE_ID):06d}")
    timestamp: float = field(default_factory=time.time)
    parent_id: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentMessage:
        return cls(
            sender=str(raw.get("sender") or ""),
            recipient=str(raw.get("recipient") or ""),
            kind=str(raw.get("kind") or ""),
            content=dict(raw.get("content") or {}),
            msg_id=str(raw.get("msg_id") or f"m-{next(_MESSAGE_ID):06d}"),
            timestamp=float(raw.get("timestamp") or time.time()),
            parent_id=str(raw.get("parent_id") or ""),
            summary=str(raw.get("summary") or ""),
        )


@dataclass(slots=True)
class AgentTask:
    """Unit of work passed from Planner to a Coder.

    The ``brief`` is what the Coder ultimately sends to the LLM. The
    other fields are advisory — the Coder may ignore ``hints`` if the
    underlying ``ProjectVibeCoder`` already encodes the same heuristics
    (e.g. ``focus_paths``).
    """

    task_id: str = field(default_factory=lambda: f"t-{uuid.uuid4().hex[:8]}")
    brief: str = ""
    rationale: str = ""
    hints: dict[str, Any] = field(default_factory=dict)
    focus_paths: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    priority: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentTask:
        return cls(
            task_id=str(raw.get("task_id") or f"t-{uuid.uuid4().hex[:8]}"),
            brief=str(raw.get("brief") or ""),
            rationale=str(raw.get("rationale") or ""),
            hints=dict(raw.get("hints") or {}),
            focus_paths=[str(p) for p in raw.get("focus_paths") or []],
            depends_on=[str(d) for d in raw.get("depends_on") or []],
            priority=int(raw.get("priority") or 1),
            metadata=dict(raw.get("metadata") or {}),
        )


SubscriberFn = Callable[[AgentMessage], None]


class MessageBus:
    """Append-only log + subscriber broadcast.

    Reads are by snapshot (``snapshot()``) which returns a tuple — the
    bus internally swaps the buffer atomically, so iterating a snapshot
    while a producer publishes is safe.

    Threads share one bus by default. If your orchestrator runs roles
    inside threads, wrap calls in your own lock — the bus only
    serialises the underlying append.
    """

    def __init__(self) -> None:
        self._messages: list[AgentMessage] = []
        self._subscribers: list[SubscriberFn] = []

    def publish(self, message: AgentMessage) -> AgentMessage:
        self._messages.append(message)
        for sub in list(self._subscribers):
            try:
                sub(message)
            except Exception:  # noqa: BLE001
                # Subscribers that raise must not break the producer; we
                # swallow them so the orchestrator keeps making progress.
                pass
        return message

    def subscribe(self, callback: SubscriberFn) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback: SubscriberFn) -> None:
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def snapshot(self) -> tuple[AgentMessage, ...]:
        return tuple(self._messages)

    def filter(self, *, recipient: str | None = None, kind: str | None = None) -> list[AgentMessage]:
        out: list[AgentMessage] = []
        for msg in self._messages:
            if recipient is not None and msg.recipient != recipient:
                continue
            if kind is not None and msg.kind != kind:
                continue
            out.append(msg)
        return out

    def __len__(self) -> int:
        return len(self._messages)

    def __iter__(self) -> Iterable[AgentMessage]:  # type: ignore[override]
        return iter(self._messages)


__all__ = ["AgentMessage", "AgentTask", "MessageBus", "SubscriberFn"]
