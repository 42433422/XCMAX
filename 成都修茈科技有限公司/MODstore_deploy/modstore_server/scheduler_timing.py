"""Shared timing bounds for scheduler integrations."""

from __future__ import annotations

import os


def cleanup_misfire_grace_time() -> int:
    try:
        configured = int(
            os.environ.get("MODSTORE_SCHEDULER_CLEANUP_MISFIRE_GRACE_SECONDS", 4 * 3600)
        )
    except ValueError:
        configured = 4 * 3600
    return max(60, configured)
