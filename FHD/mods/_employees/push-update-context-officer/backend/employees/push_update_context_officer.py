"""Deterministic, read-only update-context completeness auditor."""

from __future__ import annotations

from typing import Any

_REQUIRED = ("version", "branch", "commit_sha", "changes", "rollback", "target_tier")


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    context = dict(payload or {}).get("update_context")
    if not isinstance(context, dict):
        return _failed("update_context object is required", "missing_update_context")
    missing = [field for field in _REQUIRED if context.get(field) in (None, "", [], {})]
    issues = [{"code": "missing_field", "path": f"update_context.{field}"} for field in missing]
    sha = str(context.get("commit_sha") or "").strip()
    if sha and (len(sha) < 7 or any(char not in "0123456789abcdefABCDEF" for char in sha)):
        issues.append({"code": "invalid_commit_sha", "path": "update_context.commit_sha"})
    if context.get("git_clean") is not True:
        issues.append({"code": "worktree_not_clean", "path": "update_context.git_clean"})
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": f"更新上下文 {str(context.get('version') or '?')[:80]} 已只读核对：{len(_REQUIRED) - len(missing)}/{len(_REQUIRED)} 个核心字段完整，{len(issues)} 个阻塞项；未推送或发布。",
        "missing_fields": missing,
        "issues": issues,
        "ready_for_release_gate": not issues,
        "evidence": [f"input.update_context.{field}" for field in _REQUIRED],
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
