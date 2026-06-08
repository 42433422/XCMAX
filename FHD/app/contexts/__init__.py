"""Bounded-context registry and feature flags for event-primary routing."""

from app.contexts.flags import is_any_event_primary_enabled, is_event_primary_enabled
from app.contexts.manifest import BOUNDED_CONTEXTS, BoundedContextMeta

__all__ = [
    "BOUNDED_CONTEXTS",
    "BoundedContextMeta",
    "is_any_event_primary_enabled",
    "is_event_primary_enabled",
]
