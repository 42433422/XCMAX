"""Domain policy for client-supplied conversation metadata."""

from __future__ import annotations

import json

from app.domain.conversation.message_visibility import EMPLOYEE_MEMORY_SOURCE, is_employee_memory


def strip_client_recall_binding(metadata: str) -> str:
    """Keep server-owned recall bindings and employee memory markers off client rows."""
    try:
        payload = json.loads(metadata)
    except (TypeError, ValueError):
        return metadata
    binding = payload.get("business_harness") if isinstance(payload, dict) else None
    ui = payload.get("ui") if isinstance(payload, dict) else None
    employee_memory = is_employee_memory(payload)
    recall_bound = isinstance(binding, dict) and "recall_bound" in binding
    file_fields = {"outputArtifacts", "inputAttachments", "fileSources"}.intersection(ui) if isinstance(ui, dict) else set()
    if not employee_memory and not recall_bound and not file_fields:
        return metadata
    if recall_bound:
        binding.pop("recall_bound")
    for key in file_fields:
        ui.pop(key)
    if employee_memory:
        for key in EMPLOYEE_MEMORY_SOURCE:
            payload.pop(key)
    return json.dumps(payload, ensure_ascii=False)
