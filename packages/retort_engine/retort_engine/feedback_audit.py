from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def audit_feedback_closure(*, queue_path: str | Path = "", history_store: str | Path = "", employee_results_dir: str | Path = "") -> dict[str, Any]:
    queued = _load_queue(queue_path)
    result_rows = _load_employee_results(employee_results_dir)
    history_rows = _load_history_results(history_store)
    queued_ids = {str(row.get("task", {}).get("task_id") or row.get("task_id") or "") for row in queued}
    result_ids = {str(row.get("task_id") or "") for row in result_rows}
    history_ids = {str(row.get("task_id") or "") for row in history_rows}
    return {
        "queued_task_count": len(queued),
        "employee_result_count": len(result_rows),
        "history_result_count": len(history_rows),
        "result_tasks_have_queue_records": not result_ids or result_ids.issubset(queued_ids),
        "history_matches_employee_results": not result_ids or bool(result_ids & history_ids),
        "closed": bool(result_rows) and bool(history_rows),
    }


def _load_queue(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path) if path else Path("")
    if not file_path.is_file():
        return []
    rows = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _load_employee_results(path: str | Path) -> list[dict[str, Any]]:
    root = Path(path) if path else Path("")
    if root.is_file():
        files = [root]
    elif root.is_dir():
        files = sorted(root.glob("*.json"))
    else:
        files = []
    rows: list[dict[str, Any]] = []
    for file_path in files:
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.extend(row for row in payload.get("results") or [] if isinstance(row, dict))
    return rows


def _load_history_results(path: str | Path) -> list[dict[str, Any]]:
    db_path = Path(path) if path else Path("")
    if not db_path.is_file():
        return []
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT payload_json FROM task_results").fetchall()
    except sqlite3.Error:
        return []
    results = []
    for (payload_json,) in rows:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            results.append(payload)
    return results
