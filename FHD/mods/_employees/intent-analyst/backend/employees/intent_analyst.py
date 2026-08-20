"""Deterministic requirement-structure auditor using only supplied fields."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    spec = payload.get("request_spec")
    issues: list[dict[str, str]] = []
    if not isinstance(spec, dict):
        issues.append({"code": "missing_request_spec", "detail": "request_spec is required"})
        spec = {}
    required_text = ("goal",)
    required_lists = ("non_goals", "constraints", "risks", "acceptance")
    for field in required_text:
        if not str(spec.get(field) or "").strip():
            issues.append({"code": f"missing_{field}", "detail": f"{field} must be explicit"})
    for field in required_lists:
        values = spec.get(field)
        if not isinstance(values, list) or not [item for item in values if str(item).strip()]:
            issues.append(
                {"code": f"missing_{field}", "detail": f"{field} must contain at least one item"}
            )
    approved = not issues
    return {
        "ok": True,
        "status": "approved" if approved else "needs_review",
        "summary": "intent is testable and bounded"
        if approved
        else "intent structure is incomplete",
        "goal": str(spec.get("goal") or ""),
        "issues": issues,
        "evidence": ["fixture_only", "structured_fields_only", "no_llm_inference"],
        "read_only": True,
        "side_effects": [],
    }


__all__ = ["run"]
