"""Deterministic, read-only six-dimension quality assessor."""

from __future__ import annotations

from typing import Any

_DIMENSIONS = ("purpose", "input", "action", "evidence", "safety", "operability")


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    assessment = dict(payload or {}).get("assessment")
    if not isinstance(assessment, dict):
        return _failed("assessment object is required", "missing_assessment")
    scores = assessment.get("scores") if isinstance(assessment.get("scores"), dict) else {}
    evidence = assessment.get("evidence") if isinstance(assessment.get("evidence"), list) else []
    issues: list[dict[str, str]] = []
    normalized: dict[str, float] = {}
    for dimension in _DIMENSIONS:
        value = scores.get(dimension)
        if not isinstance(value, int | float) or not 0 <= float(value) <= 100:
            issues.append({"code": "invalid_score", "path": f"assessment.scores.{dimension}"})
        else:
            normalized[dimension] = round(float(value), 2)
    if len(evidence) < len(_DIMENSIONS):
        issues.append({"code": "insufficient_evidence", "path": "assessment.evidence"})
    overall = (
        round(sum(normalized.values()) / len(_DIMENSIONS), 2)
        if len(normalized) == len(_DIMENSIONS)
        else 0.0
    )
    if overall < 80:
        issues.append({"code": "quality_below_gate", "path": "assessment.scores"})
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": f"员工包六维质量已只读核对：综合 {overall} 分，{len(issues)} 个阻塞项；未上架产物。",
        "dimension_scores": normalized,
        "overall_score": overall,
        "issues": issues,
        "ready_for_next_gate": not issues,
        "evidence": ["input.assessment.scores", "input.assessment.evidence"],
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
