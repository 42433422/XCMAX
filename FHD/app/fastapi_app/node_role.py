"""Runtime role helpers shared by API startup paths."""

from __future__ import annotations

import os


def passive_node_enabled() -> bool:
    """Return true for application peers that must not run singleton workers."""
    return os.environ.get("XCAGI_PASSIVE_NODE", "0").strip().lower() in {
        "1",
        "true",
        "on",
        "yes",
    }
