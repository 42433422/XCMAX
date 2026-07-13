"""Timing policy for enterprise entitlement refreshes."""

from __future__ import annotations

import os


def entitlement_sync_ttl_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("XCAGI_ENTITLEMENT_SYNC_TTL_SECONDS", "300")))
    except ValueError:
        return 300.0


__all__ = ["entitlement_sync_ttl_seconds"]
