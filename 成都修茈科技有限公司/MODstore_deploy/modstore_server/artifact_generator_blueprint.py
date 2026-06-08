"""artifact-generator 上游 employee-planner 蓝图预校验（静态阶段）。"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# 与 orchestration_plan / skill-artifact-generation 输出对齐
_REQUIRED_STRING_FIELDS = (
    "employee_name",
    "employee_brief",
    "script_brief",
    "workflow_brief",
)


def extract_upstream_employee_plan(payload: Any) -> Dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    for key in ("employee_plan", "employee_orchestration_plan", "planner_blueprint"):
        raw = payload.get(key)
        if isinstance(raw, dict) and raw:
            return raw
    return None


def validate_upstream_employee_plan(plan: Dict[str, Any]) -> Tuple[str, List[str]]:
    """返回 (status, missing_fields)；status 为 ok 或 error。"""
    missing: List[str] = []
    for field in _REQUIRED_STRING_FIELDS:
        val = plan.get(field)
        if not isinstance(val, str) or not val.strip():
            missing.append(field)
    if missing:
        return "error", missing
    return "ok", []


def artifact_generator_preflight(
    *,
    payload: Any,
    brief: str,
    require_plan: bool = False,
) -> Dict[str, Any]:
    """静态阶段预检：蓝图字段 + 返回 skill 约定 JSON 片段。"""
    plan = extract_upstream_employee_plan(payload)
    if plan is None:
        if require_plan:
            return {
                "status": "error",
                "generation_mode": "unknown",
                "artifact_paths": [],
                "validation_result": {"blueprint": "missing"},
                "warnings": [],
                "missing_fields": ["employee_plan"],
                "error": "缺少上游 employee-planner 蓝图（employee_plan）",
            }
        return {
            "status": "ok",
            "generation_mode": "asset",
            "artifact_paths": [],
            "validation_result": {"blueprint": "skipped", "reason": "no_upstream_plan"},
            "warnings": [],
        }
    status, missing = validate_upstream_employee_plan(plan)
    if status == "error":
        return {
            "status": "error",
            "generation_mode": "asset",
            "artifact_paths": [],
            "validation_result": {"blueprint": "invalid", "missing_fields": missing},
            "warnings": [],
            "missing_fields": missing,
            "error": f"上游蓝图缺少必填字段：{', '.join(missing)}",
        }
    return {
        "status": "ok",
        "generation_mode": "asset",
        "artifact_paths": [],
        "validation_result": {"blueprint": "valid"},
        "warnings": [],
        "employee_plan": plan,
        "brief_from_plan": str(plan.get("employee_brief") or brief).strip() or brief,
    }
