"""Bridge functions for converting between MODstore DomainEvent and FHD NeuroEvent dict format.

These functions produce/consume dict formats compatible with FHD's
NeuroEvent.to_dict() / NeuroEvent.from_dict() without importing from FHD,
so MODstore remains independently runnable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .events import DomainEvent

_NORMAL_PRIORITY = 2


def domain_event_to_neuro_event(domain_event: DomainEvent) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "event_id": domain_event.event_id,
        "trace_id": domain_event.trace_id or None,
        "span_id": domain_event.span_id or str(uuid4())[:8],
        "parent_span_id": None,
        "source": domain_event.producer,
        "domain": "modstore",
        "retry_count": 0,
        "max_retries": 3,
        "timeout_ms": 5000,
        "dedup_key": domain_event.idempotency_key,
    }
    try:
        dt = datetime.fromisoformat(domain_event.occurred_at)
        metadata["timestamp"] = dt.timestamp()
    except (ValueError, TypeError):
        metadata["timestamp"] = 0.0

    return {
        "event_type": domain_event.event_name,
        "priority": domain_event.priority,
        "metadata": metadata,
        "payload": domain_event.payload,
    }


def neuro_event_dict_to_domain_event(data: dict[str, Any]) -> DomainEvent:
    metadata = data.get("metadata") or {}
    raw_payload = data.get("payload") or {}
    payload = dict(raw_payload)

    occurred_at: str
    ts = metadata.get("timestamp")
    if isinstance(ts, (int, float)):
        occurred_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    else:
        occurred_at = datetime.now(timezone.utc).isoformat()

    subject_id = payload.pop("_aggregate_id", "")
    version = payload.pop("_version", 1)

    return DomainEvent(
        event_id=metadata.get("event_id") or str(uuid4()),
        event_name=data.get("event_type", ""),
        event_version=version if isinstance(version, int) else 1,
        occurred_at=occurred_at,
        producer=metadata.get("source", "unknown"),
        idempotency_key=metadata.get("dedup_key") or "",
        subject_id=str(subject_id),
        payload=payload,
        priority=data.get("priority", _NORMAL_PRIORITY),
        trace_id=str(metadata.get("trace_id") or ""),
        span_id=str(metadata.get("span_id") or ""),
    )
