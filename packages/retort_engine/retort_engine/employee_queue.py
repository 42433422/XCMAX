from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.models import EmployeeTaskRecord, EmployeeTaskResult, ImprovementTask


class RetortEmployeeQueue:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def enqueue_employee_task(self, task: ImprovementTask, *, source: str, status: str = "queued") -> EmployeeTaskRecord:
        record = EmployeeTaskRecord(str(uuid.uuid4()), task, source, status, datetime.now(timezone.utc).isoformat())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def enqueue_tasks(self, tasks: tuple[ImprovementTask, ...] | list[ImprovementTask], *, source: str) -> tuple[EmployeeTaskRecord, ...]:
        return tuple(self.enqueue_employee_task(task, source=source) for task in tasks)

    def load(self) -> tuple[dict[str, Any], ...]:
        if not self.path.is_file():
            return ()
        return tuple(json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line)


def parse_employee_task_result(payload: dict[str, Any]) -> EmployeeTaskResult:
    evidence = payload.get("evidence") or ()
    if isinstance(evidence, str):
        evidence = (evidence,)
    score_after = payload.get("score_after") or {}
    if not isinstance(score_after, dict):
        score_after = {}
    return EmployeeTaskResult(
        task_id=str(payload.get("task_id") or ""),
        status=str(payload.get("status") or "unknown"),
        summary=str(payload.get("summary") or ""),
        evidence=tuple(str(item) for item in evidence),
        score_after={str(k): float(v) for k, v in score_after.items()},
    )
