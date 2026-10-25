# mypy: disable-error-code="call-arg"
"""Target discovery and default edit scope for Butler orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def default_mod_focus(scope: str) -> List[str]:
    mapping: Dict[str, List[str]] = {
        "manifest": ["manifest.json"],
        "backend": ["backend/blueprints.py", "backend/employees"],
        "frontend": ["config/frontend_spec.json", "frontend/views"],
        "employee_prompt": ["backend/employees"],
    }
    return mapping.get(
        scope,
        [
            "manifest.json",
            "backend/blueprints.py",
            "backend/employees",
            "config",
            "frontend/views",
        ],
    )


def locate_employee_mod(employee_id: str, scope: str) -> tuple[Path | None, list[str]]:
    """Find the installed MOD directory that declares an employee."""
    del scope  # Retained for compatibility with scope-aware callers.
    try:
        from modstore_server.infrastructure import library_paths

        for mod_dir in Path(library_paths.resolved_library()).iterdir():
            if not mod_dir.is_dir():
                continue
            manifest_path = mod_dir / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            employees = data.get("workflow_employees") or []
            for employee in employees:
                if not isinstance(employee, dict):
                    continue
                declared_id = str(employee.get("id") or employee.get("employee_id") or "").strip()
                if declared_id and (
                    declared_id == employee_id or employee_id.startswith(declared_id)
                ):
                    focus = [
                        f"backend/employees/{declared_id}.py",
                        f"backend/employees/{declared_id}",
                    ]
                    return mod_dir, focus
    except RECOVERABLE_ERRORS:
        pass
    return None, []
