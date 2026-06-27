from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.models import AbsorptionResult, EmployeeTaskRecord, EmployeeTaskResult


class RetortHistoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def record_absorption_run(self, result: AbsorptionResult) -> int:
        return self._insert("absorption_runs", {"created_at": _now_iso(), "status": result.status, "source": result.external_ref.source, "payload_json": result.to_dict()})

    def record_employee_task(self, record: EmployeeTaskRecord) -> int:
        return self._insert("employee_tasks", {"created_at": record.created_at or _now_iso(), "queue_id": record.queue_id, "task_id": record.task.task_id, "owner_hint": record.task.owner_hint, "status": record.status, "payload_json": record.to_dict()})

    def record_task_result(self, task_result: EmployeeTaskResult) -> int:
        return self._insert("task_results", {"created_at": _now_iso(), "task_id": task_result.task_id, "status": task_result.status, "payload_json": task_result.to_dict()})

    def latest_task_results(self, limit: int = 20) -> tuple[dict[str, Any], ...]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute("SELECT payload_json FROM task_results ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return tuple(json.loads(row[0]) for row in rows)

    def _insert(self, table: str, values: dict[str, Any]) -> int:
        columns = list(values)
        placeholders = ",".join("?" for _ in columns)
        payload = [json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value for value in values.values()]
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})", payload)
            return int(cursor.lastrowid)

    def _init_schema(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS absorption_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL, payload_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS employee_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, queue_id TEXT NOT NULL, task_id TEXT NOT NULL, owner_hint TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS task_results (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, task_id TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL);
                """
            )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
