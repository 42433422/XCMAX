"""Domain event envelope."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class DomainEvent:
    event_id: str
    event_name: str
    event_version: int
    occurred_at: str
    producer: str
    idempotency_key: str
    subject_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 2
    trace_id: str = ""
    span_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "event_version": self.event_version,
            "occurred_at": self.occurred_at,
            "producer": self.producer,
            "idempotency_key": self.idempotency_key,
            "subject_id": self.subject_id,
            "payload": self.payload,
            "priority": self.priority,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
        }


def new_event(
    event_name: str,
    *,
    producer: str,
    subject_id: str,
    payload: dict[str, Any] | None = None,
    event_version: int = 1,
    idempotency_key: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    priority: int = 2,
) -> DomainEvent:
    tid = (trace_id or "").strip()
    sp = (span_id or "").strip()
    if not tid or not sp:
        try:
            from modstore_server.eventing.request_trace import current_trace_ids

            ct, cs = current_trace_ids()
            tid = tid or ct
            sp = sp or cs
        except Exception:  # noqa: BLE001
            pass
    return DomainEvent(
        event_id=str(uuid4()),
        event_name=event_name,
        event_version=event_version,
        occurred_at=datetime.now(timezone.utc).isoformat(),
        producer=producer,
        idempotency_key=idempotency_key or f"{event_name}:{subject_id}",
        subject_id=subject_id,
        payload=payload or {},
        priority=int(priority),
        trace_id=tid or "",
        span_id=sp or "",
    )
