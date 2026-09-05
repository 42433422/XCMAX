from __future__ import annotations

from retort_engine.employee_queue import parse_employee_task_result
from retort_engine.history import RetortHistoryStore
from retort_engine.models import EmployeeTaskResult
from retort_engine.secure_artifacts import read_private_json


def feedback_ingest(
    *,
    history_store: str,
    result_file: str = "",
    task_id: str = "",
    status: str = "",
    summary: str = "",
    evidence: tuple[str, ...] = (),
) -> EmployeeTaskResult:
    if result_file:
        payload = read_private_json(result_file)
    else:
        payload = {
            "task_id": task_id,
            "status": status,
            "summary": summary,
            "evidence": list(evidence),
        }
    result = parse_employee_task_result(payload)
    RetortHistoryStore(history_store).record_task_result(result)
    return result
