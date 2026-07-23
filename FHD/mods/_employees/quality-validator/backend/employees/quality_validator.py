"""Deterministic, read-only employee-pack consistency validator."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    pack = payload.get("pack")
    if not isinstance(pack, dict):
        return _failed("pack object is required", "missing_pack")
    manifest = pack.get("manifest")
    files = pack.get("files")
    if not isinstance(manifest, dict) or not isinstance(files, list):
        return _failed("pack.manifest and pack.files are required", "invalid_pack")

    issues: list[dict[str, str]] = []
    employee_id = str(manifest.get("id") or "").strip()
    if not employee_id:
        issues.append({"code": "manifest_id_missing", "path": "manifest.id"})
    v2 = manifest.get("employee_config_v2")
    actions = v2.get("actions") if isinstance(v2, dict) else None
    handlers = actions.get("handlers") if isinstance(actions, dict) else None
    if not isinstance(handlers, list) or not handlers:
        issues.append(
            {
                "code": "handlers_missing",
                "path": "manifest.employee_config_v2.actions.handlers",
            }
        )

    normalized_files = {
        PurePosixPath(str(item)).as_posix()
        for item in files
        if isinstance(item, str) and item.strip()
    }
    if "manifest.json" not in normalized_files:
        issues.append({"code": "manifest_file_missing", "path": "files"})
    if employee_id:
        module = employee_id.replace("-", "_")
        expected = f"backend/employees/{module}.py"
        if expected not in normalized_files:
            issues.append({"code": "employee_module_missing", "path": expected})

    approved = not issues
    return {
        "ok": True,
        "status": "approved" if approved else "rejected",
        "summary": f"员工包已完成确定性只读质检：检查 {len(normalized_files)} 个文件，发现 {len(issues)} 个阻塞项。",
        "valid": approved,
        "issues": issues,
        "evidence": ["pack.manifest", "pack.files", "employee module path consistency"],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
