"""Deterministic, read-only script-binding contract auditor."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

EMPLOYEE_ID = "script-binder"


def _failure(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message[:500],
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }


def _safe_relative(path: str) -> bool:
    candidate = PurePosixPath(path)
    return bool(path) and not candidate.is_absolute() and ".." not in candidate.parts


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Validate a proposed workflow-to-pack binding without modifying the pack."""

    data = dict(payload or {})
    if str(data.get("action") or "audit_binding_plan") != "audit_binding_plan":
        return _failure("unsupported action", "unsupported_action")
    manifest = data.get("manifest")
    workflow = data.get("workflow")
    if not isinstance(manifest, dict) or not isinstance(workflow, dict):
        return _failure("manifest and workflow objects are required", "missing_binding_input")

    issues: list[dict[str, str]] = []
    pack_id = str(manifest.get("id") or "").strip()[:160]
    workflow_pack_id = str(workflow.get("employee_pack_id") or "").strip()[:160]
    skills = workflow.get("skills") if isinstance(workflow.get("skills"), list) else []
    declared = (
        manifest.get("employee", {}).get("capabilities", [])
        if isinstance(manifest.get("employee"), dict)
        else []
    )
    declared_labels = {
        str(item.get("label") or "").strip()
        for item in declared
        if isinstance(item, dict) and str(item.get("label") or "").strip()
    }
    if not pack_id:
        issues.append({"code": "missing_pack_id", "path": "manifest.id"})
    if pack_id != workflow_pack_id:
        issues.append({"code": "pack_id_mismatch", "path": "workflow.employee_pack_id"})
    if not skills:
        issues.append({"code": "missing_skills", "path": "workflow.skills"})
    binding_plan: list[dict[str, str]] = []
    for index, item in enumerate(skills[:100]):
        skill = item if isinstance(item, dict) else {}
        skill_id = str(skill.get("id") or "").strip()[:160]
        script_path = str(skill.get("script_path") or "").strip()[:500]
        if not skill_id:
            issues.append({"code": "missing_skill_id", "path": f"workflow.skills[{index}].id"})
        if not _safe_relative(script_path):
            issues.append(
                {"code": "unsafe_script_path", "path": f"workflow.skills[{index}].script_path"}
            )
        if skill_id and skill_id not in declared_labels:
            issues.append(
                {"code": "capability_not_declared", "path": f"workflow.skills[{index}].id"}
            )
        if skill_id and _safe_relative(script_path):
            binding_plan.append({"skill_id": skill_id, "script_path": script_path})
    status = "approved" if not issues else "rejected"
    return {
        "ok": True,
        "status": status,
        "summary": (
            f"员工包 {pack_id or '?'} 的脚本绑定计划已完成只读核对："
            f"{len(binding_plan)} 项可绑定，{len(issues)} 个阻塞项；未写 manifest 或刷新 Catalog。"
        ),
        "employee_pack_id": pack_id,
        "binding_plan": binding_plan,
        "issues": issues,
        "ready_for_binding": not issues,
        "evidence": ["input.manifest", "input.workflow", "input.workflow.skills"],
        "read_only": True,
        "side_effects": [],
        "meta": {"employee_id": EMPLOYEE_ID, "contract_version": "1.0"},
    }
