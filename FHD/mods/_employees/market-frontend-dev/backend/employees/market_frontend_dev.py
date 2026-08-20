"""Deterministic, read-only MODstore frontend change auditor."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    proposal = dict(payload or {}).get("frontend_change")
    if not isinstance(proposal, dict):
        return _failed("frontend_change object is required", "missing_frontend_change")
    issues: list[dict[str, str]] = []
    files = proposal.get("files") if isinstance(proposal.get("files"), list) else []
    tests = proposal.get("tests") if isinstance(proposal.get("tests"), list) else []
    api_contracts = (
        proposal.get("api_contracts") if isinstance(proposal.get("api_contracts"), list) else []
    )
    framework = str(proposal.get("framework") or "").strip().lower()
    if framework != "vue3":
        issues.append({"code": "framework_not_vue3", "path": "frontend_change.framework"})
    clean_files: list[str] = []
    for index, value in enumerate(files[:200]):
        path = str(value or "").strip()[:500]
        if not path.startswith("market/src/") or not path.endswith((".vue", ".ts", ".css")):
            issues.append(
                {"code": "file_outside_frontend_scope", "path": f"frontend_change.files[{index}]"}
            )
        else:
            clean_files.append(path)
    if not clean_files:
        issues.append({"code": "missing_frontend_files", "path": "frontend_change.files"})
    if not tests:
        issues.append({"code": "missing_tests", "path": "frontend_change.tests"})
    if not api_contracts:
        issues.append({"code": "missing_api_contracts", "path": "frontend_change.api_contracts"})
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": f"市场前端变更已只读核对：{len(clean_files)} 个范围内文件、{len(tests)} 项测试、{len(issues)} 个阻塞项；未修改源码。",
        "files": clean_files,
        "issues": issues,
        "ready_for_implementation": not issues,
        "evidence": [
            "input.frontend_change.files",
            "input.frontend_change.api_contracts",
            "input.frontend_change.tests",
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
