# -*- coding: utf-8 -*-
"""员工运行时执行指标（进程内计数，供诊断/可观测）。"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

_lock = threading.Lock()
_DEFAULT_METRICS: dict[str, Any] = {
    "runs_total": 0,
    "runs_success": 0,
    "runs_failed": 0,
    "runs_blocked": 0,
    "triggers_total": 0,
    "orchestrations_total": 0,
    "write_blocks_total": 0,
    "last_run_at": None,
    "by_employee": {},
}
_metrics: dict[str, Any] = dict(_DEFAULT_METRICS)
_metrics["by_employee"] = {}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _bump(key: str, employee_id: str | None = None, *, delta: int = 1) -> None:
    with _lock:
        _metrics[key] = int(_metrics.get(key) or 0) + delta
        if employee_id:
            per = _metrics.setdefault("by_employee", {})
            row = dict(per.get(employee_id) or {})
            row[key] = int(row.get(key) or 0) + delta
            per[employee_id] = row


def record_employee_run(
    employee_id: str,
    *,
    success: bool,
    blocked: bool = False,
    task: str = "",
    summary: str = "",
) -> None:
    now = _now_iso()
    _bump("runs_total", employee_id)
    if blocked:
        _bump("runs_blocked", employee_id)
    elif success:
        _bump("runs_success", employee_id)
    else:
        _bump("runs_failed", employee_id)
    with _lock:
        _metrics["last_run_at"] = now
        per = _metrics.setdefault("by_employee", {})
        row = dict(per.get(employee_id) or {})
        row["last_run_at"] = now
        row["last_execution"] = {
            "executed_at": now,
            "success": bool(success) and not blocked,
            "blocked": bool(blocked),
        }
        per[employee_id] = row
    try:
        from app.application.ai_circle_service import record_employee_activity

        record_employee_activity(
            employee_id,
            success=success,
            blocked=blocked,
            task=task,
            summary=summary,
        )
    except Exception:  # noqa: BLE001  # metrics must never break employee execution
        pass


def record_employee_trigger(employee_id: str, event_type: str) -> None:
    _bump("triggers_total", employee_id)
    with _lock:
        per = _metrics.setdefault("by_employee", {})
        row = dict(per.get(employee_id) or {})
        triggers = dict(row.get("triggers_by_event") or {})
        triggers[event_type] = int(triggers.get(event_type) or 0) + 1
        row["triggers_by_event"] = triggers
        per[employee_id] = row


def record_orchestration(employee_id: str) -> None:
    _bump("orchestrations_total", employee_id)


def record_write_block(employee_id: str) -> None:
    _bump("write_blocks_total", employee_id)


def get_employee_runtime_metrics() -> dict[str, Any]:
    with _lock:
        return {
            "runs_total": _metrics.get("runs_total", 0),
            "runs_success": _metrics.get("runs_success", 0),
            "runs_failed": _metrics.get("runs_failed", 0),
            "runs_blocked": _metrics.get("runs_blocked", 0),
            "triggers_total": _metrics.get("triggers_total", 0),
            "orchestrations_total": _metrics.get("orchestrations_total", 0),
            "write_blocks_total": _metrics.get("write_blocks_total", 0),
            "last_run_at": _metrics.get("last_run_at"),
            "by_employee": dict(_metrics.get("by_employee") or {}),
        }


def reset_employee_runtime_metrics() -> None:
    with _lock:
        _metrics.clear()
        _metrics.update(dict(_DEFAULT_METRICS))
        _metrics["by_employee"] = {}


__all__ = [
    "get_employee_runtime_metrics",
    "record_employee_run",
    "record_employee_trigger",
    "record_orchestration",
    "record_write_block",
    "reset_employee_runtime_metrics",
]
