"""Deterministic, read-only pull-request merge eligibility evaluator."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(payload or {}).get("pr_snapshot")
    if not isinstance(snapshot, dict):
        return _failed("pr_snapshot object is required", "missing_pr_snapshot")
    issues: list[dict[str, str]] = []
    pr_number = snapshot.get("number")
    checks = snapshot.get("checks") if isinstance(snapshot.get("checks"), list) else []
    reviews = snapshot.get("reviews") if isinstance(snapshot.get("reviews"), list) else []
    if not isinstance(pr_number, int) or pr_number <= 0:
        issues.append({"code": "invalid_pr_number", "path": "pr_snapshot.number"})
    if snapshot.get("draft") is True:
        issues.append({"code": "pr_is_draft", "path": "pr_snapshot.draft"})
    if snapshot.get("mergeable") is not True:
        issues.append({"code": "pr_not_mergeable", "path": "pr_snapshot.mergeable"})
    if not checks or any(
        str(item.get("status") or "").lower() != "success"
        for item in checks
        if isinstance(item, dict)
    ):
        issues.append({"code": "checks_not_green", "path": "pr_snapshot.checks"})
    if not any(
        str(item.get("state") or "").lower() == "approved"
        for item in reviews
        if isinstance(item, dict)
    ):
        issues.append({"code": "approval_missing", "path": "pr_snapshot.reviews"})
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": f"PR #{pr_number or '?'} 快照已只读核对：{len(checks)} 项检查、{len(reviews)} 条评审、{len(issues)} 个阻塞项；未访问 GitHub 或执行合并。",
        "pr_number": pr_number,
        "issues": issues,
        "eligible_for_merge": not issues,
        "evidence": [
            "input.pr_snapshot.checks",
            "input.pr_snapshot.reviews",
            "input.pr_snapshot.mergeable",
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
