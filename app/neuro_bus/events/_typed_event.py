"""Typed NeuroEvent subclasses — payload-first constructor (non-dataclass)."""
from __future__ import annotations

from typing import Any

from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent


def init_typed_event(
    self: NeuroEvent,
    payload: dict[str, Any],
    *,
    event_type: str,
    priority: EventPriority,
    required: tuple[str, ...],
    class_name: str,
    metadata: EventMetadata | None = None,
    preserve_queue_identity: bool = False,
) -> None:
    NeuroEvent.__init__(
        self,
        event_type=event_type,
        payload=payload,
        priority=priority,
        metadata=metadata,
        preserve_queue_identity=preserve_queue_identity,
    )
    for field in required:
        if field not in self.payload:
            raise ValueError(f"{class_name} 缺少必要字段: {field}")
