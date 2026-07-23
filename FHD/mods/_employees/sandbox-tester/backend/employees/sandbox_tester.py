"""Deterministic, read-only sandbox execution receipt verifier."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    test_run = payload.get("test_run")
    if not isinstance(test_run, dict):
        return _failed("test_run object is required", "missing_test_run")

    checks = {
        "sandboxed": test_run.get("sandboxed") is True,
        "exit_code_zero": test_run.get("exit_code") == 0,
        "no_network_attempts": test_run.get("network_attempts") == 0,
        "no_filesystem_escape": test_run.get("filesystem_escape_attempts") == 0,
        "reproducible": test_run.get("reproducible") is True,
    }
    tests = test_run.get("tests") if isinstance(test_run.get("tests"), list) else []
    checks["tests_present"] = bool(tests)
    checks["tests_passed"] = bool(tests) and all(
        isinstance(item, dict) and str(item.get("status") or "").lower() == "passed"
        for item in tests
    )
    blockers = [name for name, passed in checks.items() if not passed]
    approved = not blockers
    return {
        "ok": True,
        "status": "approved" if approved else "rejected",
        "summary": (
            f"沙箱执行回执已只读核验：{sum(checks.values())}/{len(checks)} 项通过，"
            f"{len(blockers)} 个边界阻塞项；本步骤未执行不受信代码。"
        ),
        "checks": checks,
        "blockers": blockers,
        "evidence": [
            "test_run isolation fields",
            "test_run.tests",
            "test_run.reproducible",
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
