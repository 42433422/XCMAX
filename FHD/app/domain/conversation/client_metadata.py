"""Domain policy for client-supplied conversation metadata."""

from __future__ import annotations

import json


def strip_client_recall_binding(metadata: str) -> str:
    """Only the server turn persistence path can associate a message with an undo."""
    try:
        payload = json.loads(metadata)
    except (TypeError, ValueError):
        return metadata
    binding = payload.get("business_harness") if isinstance(payload, dict) else None
    if not isinstance(binding, dict) or "recall_bound" not in binding:
        return metadata
    binding.pop("recall_bound")
    return json.dumps(payload, ensure_ascii=False)
