"""Result builders for employee runtime terminal states."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any


def build_blocked_result(
    employee_id: str,
    pack: dict[str, Any],
    task: str,
    handler_list: list[str],
    gate: dict[str, Any],
    started_at: float,
) -> dict[str, Any]:
    return {
        "employee_id": employee_id,
        "pack": {"id": pack["pack_id"], "version": pack.get("version")},
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 3),
        "result": {
            "task": task,
            "handlers": handler_list,
            "outputs": [],
            "summary": "blocked by risk middleware",
            "risk_gate": gate,
        },
        "executed_at": datetime.now(UTC).isoformat(),
        "blocked_by_risk_gate": True,
        "success": False,
    }


def build_cognition_failed_result(
    employee_id: str,
    pack: dict[str, Any],
    task: str,
    handler_list: list[str],
    reasoning: dict[str, Any],
    started_at: float,
) -> dict[str, Any]:
    return {
        "employee_id": employee_id,
        "pack": {"id": pack["pack_id"], "version": pack.get("version")},
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 3),
        "success": False,
        "error": str(reasoning.get("error") or "employee cognition failed"),
        "error_code": reasoning.get("error_code"),
        "retryable": reasoning.get("retryable"),
        "result": {
            "task": task,
            "handlers": handler_list,
            "outputs": [],
            "summary": "cognition failed",
            "cognition_error": reasoning.get("error"),
        },
        "executed_at": datetime.now(UTC).isoformat(),
    }
