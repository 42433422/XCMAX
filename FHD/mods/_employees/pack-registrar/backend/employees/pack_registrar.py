"""Deterministic, read-only package-registration readiness auditor."""

from __future__ import annotations

import re
from typing import Any

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    candidate = data.get("candidate")
    checks = data.get("checks")
    if not isinstance(candidate, dict) or not isinstance(checks, dict):
        return _failed("candidate and checks objects are required", "missing_registration_input")
    issues: list[dict[str, str]] = []
    pack_id = str(candidate.get("id") or "").strip()[:160]
    version = str(candidate.get("version") or "").strip()[:80]
    digest = str(checks.get("sha256") or "").strip().lower()
    runtime_issues = (
        checks.get("runtime_issues") if isinstance(checks.get("runtime_issues"), list) else []
    )
    quality_score = checks.get("quality_score")
    if not pack_id:
        issues.append({"code": "missing_id", "path": "candidate.id"})
    if not _SEMVER.fullmatch(version):
        issues.append({"code": "invalid_semver", "path": "candidate.version"})
    if candidate.get("artifact") != "employee_pack":
        issues.append({"code": "invalid_artifact", "path": "candidate.artifact"})
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        issues.append({"code": "invalid_sha256", "path": "checks.sha256"})
    if runtime_issues:
        issues.append({"code": "runtime_issues_present", "path": "checks.runtime_issues"})
    if not isinstance(quality_score, int | float) or float(quality_score) < 80:
        issues.append({"code": "quality_below_gate", "path": "checks.quality_score"})
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": f"员工包 {pack_id or '?'}@{version or '?'} 已只读核对登记条件：{len(issues)} 个阻塞项；未写 Catalog。",
        "package_id": pack_id,
        "version": version,
        "issues": issues,
        "ready_for_registration": not issues,
        "evidence": [
            "input.candidate",
            "input.checks.runtime_issues",
            "input.checks.sha256",
            "input.checks.quality_score",
        ],
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
