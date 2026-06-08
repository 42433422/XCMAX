"""Eventing primitives for MODstore Neuro-DDD."""

from .bus import (
    CircuitBreaker,
    DeduplicationCache,
    EventPriority,
    HandlerSubscription,
    InMemoryNeuroBus,
    NeuroBus,
)
from .events import DomainEvent, new_event

__all__ = [
    "CircuitBreaker",
    "DeduplicationCache",
    "DomainEvent",
    "EventPriority",
    "HandlerSubscription",
    "InMemoryNeuroBus",
    "NeuroBus",
    "new_event",
]


# Lazy attribute access for the transactional outbox helpers so importing
# ``modstore_server.eventing`` does not pull in SQLAlchemy unless needed.
def __getattr__(name):  # pragma: no cover - thin lazy bridge
    if name in {
        "OutboxDispatcherWorker",
        "OutboxRecord",
        "drain",
        "enqueue",
        "fetch_pending",
        "mark_dispatched",
        "mark_failed",
        "start_default_worker",
    }:
        from . import db_outbox

        return getattr(db_outbox, name)
    raise AttributeError(name)
