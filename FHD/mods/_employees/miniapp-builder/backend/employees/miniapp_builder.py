"""Deterministic, read-only miniapp workflow specification validator."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    spec = dict(payload or {}).get("miniapp_spec")
    if not isinstance(spec, dict):
        return _failed("miniapp_spec object is required", "missing_miniapp_spec")
    issues: list[dict[str, str]] = []
    app_id = str(spec.get("id") or "").strip()[:160]
    steps = spec.get("steps") if isinstance(spec.get("steps"), list) else []
    inputs = spec.get("inputs") if isinstance(spec.get("inputs"), list) else []
    outputs = spec.get("outputs") if isinstance(spec.get("outputs"), list) else []
    if not app_id:
        issues.append({"code": "missing_id", "path": "miniapp_spec.id"})
    if not inputs:
        issues.append({"code": "missing_inputs", "path": "miniapp_spec.inputs"})
    if not outputs:
        issues.append({"code": "missing_outputs", "path": "miniapp_spec.outputs"})
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(steps[:100]):
        step = raw if isinstance(raw, dict) else {}
        step_id = str(step.get("id") or "").strip()[:160]
        operation = str(step.get("operation") or "").strip()[:160]
        depends_on = step.get("depends_on") if isinstance(step.get("depends_on"), list) else []
        if not step_id or step_id in seen:
            issues.append({"code": "invalid_step_id", "path": f"miniapp_spec.steps[{index}].id"})
            continue
        seen.add(step_id)
        if not operation:
            issues.append(
                {"code": "missing_operation", "path": f"miniapp_spec.steps[{index}].operation"}
            )
        normalized.append(
            {
                "id": step_id,
                "operation": operation,
                "depends_on": [str(value)[:160] for value in depends_on],
            }
        )
    if not normalized:
        issues.append({"code": "missing_steps", "path": "miniapp_spec.steps"})
    known = {item["id"] for item in normalized}
    if any(dep not in known for item in normalized for dep in item["depends_on"]):
        issues.append({"code": "unknown_dependency", "path": "miniapp_spec.steps.depends_on"})
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": f"小应用规格 {app_id or '?'} 已只读核对：{len(normalized)} 个步骤、{len(issues)} 个阻塞项；未生成或启动应用。",
        "miniapp_id": app_id,
        "normalized_steps": normalized,
        "issues": issues,
        "ready_for_build": not issues,
        "evidence": ["input.miniapp_spec", "input.miniapp_spec.steps"],
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
