"""Feature flags: event-primary path per bounded context."""

from __future__ import annotations

import os


def _truthy(val: str) -> bool:
    return val.strip().lower() in {"1", "true", "yes", "on"}


def is_any_event_primary_enabled() -> bool:
    raw = (os.environ.get("XCAGI_EVENT_PRIMARY") or "").strip()
    return bool(raw) and _truthy(raw)


def is_event_primary_enabled(context_id: str) -> bool:
    """
    ``XCAGI_EVENT_PRIMARY=1`` enables event-primary for all facades that consult this flag.
    ``XCAGI_EVENT_PRIMARY_SHIPMENT=1`` enables only shipment (context id ``shipment``).
    """
    if is_any_event_primary_enabled():
        return True
    key = f"XCAGI_EVENT_PRIMARY_{context_id.strip().upper()}"
    raw = (os.environ.get(key) or "").strip()
    return bool(raw) and _truthy(raw)
