from __future__ import annotations

import json
from pathlib import Path

from retort_engine.employee_queue import parse_employee_task_result
from retort_engine.history import RetortHistoryStore
from retort_engine.models import EmployeeTaskResult


def feedback_ingest(*, history_store: str, result_file: str = "", task_id: str = "", status: str = "", summary: str = "", evidence: tuple[str, ...] = ()) -> EmployeeTaskResult:
    if result_file:
        payload = json.loads(Path(result_file).read_text(encoding="utf-8"))
    else:
        payload = {"task_id": task_id, "status": status, "summary": summary, "evidence": list(evidence)}
    result = parse_employee_task_result(payload)
    RetortHistoryStore(history_store).record_task_result(result)
    return result
