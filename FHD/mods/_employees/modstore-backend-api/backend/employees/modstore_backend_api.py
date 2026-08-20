"""Deterministic, read-only MODstore API contract auditor."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    contract = dict(payload or {}).get("api_contract")
    if not isinstance(contract, dict):
        return _failed("api_contract object is required", "missing_api_contract")
    issues: list[dict[str, str]] = []
    method = str(contract.get("method") or "").strip().upper()
    path = str(contract.get("path") or "").strip()[:500]
    tests = contract.get("tests") if isinstance(contract.get("tests"), list) else []
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        issues.append({"code": "invalid_method", "path": "api_contract.method"})
    if not path.startswith("/api/") or ".." in path:
        issues.append({"code": "invalid_api_path", "path": "api_contract.path"})
    for field in ("request_schema", "response_schema"):
        if not isinstance(contract.get(field), dict):
            issues.append({"code": "missing_schema", "path": f"api_contract.{field}"})
    if contract.get("auth_required") is not True:
        issues.append({"code": "auth_not_declared", "path": "api_contract.auth_required"})
    if not tests:
        issues.append({"code": "missing_contract_tests", "path": "api_contract.tests"})
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": f"API 契约 {method or '?'} {path or '?'} 已只读核对：{len(tests)} 项测试、{len(issues)} 个阻塞项；未注册路由或访问数据库。",
        "method": method,
        "path": path,
        "issues": issues,
        "ready_for_implementation": not issues,
        "evidence": [
            "input.api_contract.request_schema",
            "input.api_contract.response_schema",
            "input.api_contract.tests",
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
