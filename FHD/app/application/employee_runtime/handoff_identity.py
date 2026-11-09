"""Read a registered AI role identity without conflating it with availability."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.application.employee_runtime.workspace_io import (
    workspace_directory,
    workspace_file,
    workspace_names,
)


def load_identity_card(
    workspace: str | Path | None, candidate: Any
) -> tuple[dict[str, Any] | None, str]:
    """Return only the canonical role ID, tenant and execution flags from its card."""
    if type(candidate) is not str:
        return None, "handoff_unknown_employee"
    target = candidate.strip()
    if (
        not target
        or target in {".", ".."}
        or any(char in target for char in "/\\:")
        or any(ord(char) < 32 or ord(char) == 127 for char in target)
    ):
        return None, "handoff_unknown_employee"
    if not workspace:
        return None, "handoff_identity_unverified"
    folder = Path(workspace) / "employees"
    try:
        with workspace_directory(workspace, folder) as parent_fd:
            if not any(name.endswith(".json") for name in workspace_names(parent_fd)):
                return None, "handoff_identity_unverified"
            try:
                with workspace_file(parent_fd, f"{target}.json", os.O_RDONLY, "r") as handle:
                    loaded = json.load(handle)
            except FileNotFoundError:
                return None, "handoff_unknown_employee"
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        return None, "handoff_identity_unverified"
    if not isinstance(loaded, dict):
        return None, "handoff_identity_unverified"
    identity = loaded.get("employee_id")
    tenant = loaded.get("tenant_id")
    if (
        type(identity) is not str
        or identity.strip() != target
        or type(tenant) not in (str, int)
        or not str(tenant).strip()
    ):
        return None, "handoff_identity_unverified"
    return {
        "employee_id": identity.strip(),
        "tenant_id": str(tenant).strip(),
        **{
            key: bool(loaded.get(key, key == "available"))
            for key in ("available", "timeout", "crash", "unrecoverable")
        },
    }, ""
