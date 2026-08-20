"""Deterministic, read-only artifact blueprint validator."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


def _safe(path: str) -> bool:
    value = PurePosixPath(path)
    return bool(path) and not value.is_absolute() and ".." not in value.parts


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    blueprint = data.get("blueprint")
    if not isinstance(blueprint, dict):
        return _failed("blueprint object is required", "missing_blueprint")
    issues: list[dict[str, str]] = []
    artifact_id = str(blueprint.get("id") or "").strip()[:160]
    artifact = str(blueprint.get("artifact") or "").strip()
    files = blueprint.get("files") if isinstance(blueprint.get("files"), list) else []
    capabilities = (
        blueprint.get("capabilities") if isinstance(blueprint.get("capabilities"), list) else []
    )
    acceptance = (
        blueprint.get("acceptance") if isinstance(blueprint.get("acceptance"), list) else []
    )
    if not artifact_id:
        issues.append({"code": "missing_id", "path": "blueprint.id"})
    if artifact not in {"employee_pack", "mod"}:
        issues.append({"code": "invalid_artifact", "path": "blueprint.artifact"})
    if not capabilities:
        issues.append({"code": "missing_capabilities", "path": "blueprint.capabilities"})
    if not acceptance:
        issues.append({"code": "missing_acceptance", "path": "blueprint.acceptance"})
    clean_files: list[str] = []
    for index, value in enumerate(files[:200]):
        path = str(value or "").strip()[:500]
        if not _safe(path):
            issues.append({"code": "unsafe_file_path", "path": f"blueprint.files[{index}]"})
        elif path not in clean_files:
            clean_files.append(path)
    if not clean_files:
        issues.append({"code": "missing_files", "path": "blueprint.files"})
    return _receipt(
        artifact_id,
        issues,
        {
            "artifact": artifact,
            "files": clean_files,
            "capabilities": [str(value)[:160] for value in capabilities[:100]],
            "acceptance": [str(value)[:300] for value in acceptance[:100]],
        },
    )


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


def _receipt(
    artifact_id: str, issues: list[dict[str, str]], plan: dict[str, Any]
) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": f"产物蓝图 {artifact_id or '?'} 已只读核对：{len(plan['files'])} 个文件、{len(issues)} 个阻塞项；未生成文件。",
        "artifact_id": artifact_id,
        "build_plan": plan,
        "issues": issues,
        "ready_for_generation": not issues,
        "evidence": ["input.blueprint", "input.blueprint.files", "input.blueprint.acceptance"],
        "read_only": True,
        "side_effects": [],
    }
