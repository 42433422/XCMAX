from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.history import RetortHistoryStore
from retort_engine.models import EmployeeTaskRecord, ImprovementTask


def build_task_dispatch_plan(project: str | Path, *, enqueue: bool = False) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    source_tasks = _latest_llm_employee_tasks(root) or _priority_tasks(root)
    dispatch_tasks = [_dispatch_task(item, index) for index, item in enumerate(source_tasks, start=1)]
    queued_records = _enqueue(root, dispatch_tasks) if enqueue else []
    ready_count = sum(1 for item in dispatch_tasks if item.get("owner_hint") and item.get("acceptance") and item.get("evidence_required"))
    return {
        "status": "ready" if dispatch_tasks and ready_count == len(dispatch_tasks) and (not enqueue or len(queued_records) == len(dispatch_tasks)) else "needs_tasks",
        "project": str(root),
        "summary": {
            "source_llm_task_count": len(source_tasks),
            "ready_task_count": ready_count,
            "dispatch_task_count": len(dispatch_tasks),
            "queued_dispatch_count": len(queued_records),
            "all_tasks_have_owner": all(bool(item.get("owner_hint")) for item in dispatch_tasks),
            "all_tasks_have_acceptance": all(bool(item.get("acceptance")) for item in dispatch_tasks),
            "all_tasks_have_evidence_required": all(bool(item.get("evidence_required")) for item in dispatch_tasks),
            "enqueue": enqueue,
        },
        "tasks": [{**task, "queue_id": queued.get("queue_id", "")} for task, queued in zip(dispatch_tasks, queued_records or [{} for _ in dispatch_tasks])],
        "evidence": {
            "queue_path": str(root / ".retort" / "employee_queue.jsonl"),
            "history_store": str(root / ".retort" / "retort_history.sqlite"),
            "source": "latest_llm_employee_tasks" if _latest_llm_employee_tasks(root) else "task_prioritization_report",
        },
    }


def _latest_llm_employee_tasks(root: Path) -> list[dict[str, Any]]:
    path = root / ".retort" / "llm_reviews.jsonl"
    if not path.is_file():
        return []
    tasks: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = payload.get("json_result") if isinstance(payload.get("json_result"), dict) else {}
        current = [item for item in result.get("employee_tasks") or [] if isinstance(item, dict)]
        if current:
            tasks = current
    return tasks


def _priority_tasks(root: Path) -> list[dict[str, Any]]:
    path = root / "docs" / "retort_task_prioritization_report.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = []
    for item in payload.get("priorities") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "title": f"Replay and verify {item.get('dimension', 'retort')}",
                "owner_hint": item.get("owner_hint"),
                "acceptance": item.get("acceptance"),
                "evidence_required": item.get("evidence_required"),
            }
        )
    return rows


def _dispatch_task(item: dict[str, Any], index: int) -> dict[str, Any]:
    evidence = item.get("evidence_required") or []
    evidence_list = [str(evidence)] if isinstance(evidence, str) else [str(row) for row in evidence if str(row).strip()]
    title = str(item.get("title") or f"Retort dispatch task {index}")
    return {
        "task_id": f"retort-dispatch-{index:02d}-{uuid.uuid4().hex[:8]}",
        "title": title,
        "dimension": _dimension_from_title(title),
        "owner_hint": str(item.get("owner_hint") or "retort-employee"),
        "priority": "P1",
        "why": "LLM self-evolution requested this follow-up after deep review.",
        "action": f"Execute and verify: {title}",
        "acceptance": str(item.get("acceptance") or "Evidence report proves task completion and no score regression."),
        "evidence_required": evidence_list or ["execution_log", "result_artifact", "post_task_score"],
        "ready_for_employee": True,
    }


def _enqueue(root: Path, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue_path = root / ".retort" / "employee_queue.jsonl"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    store = RetortHistoryStore(root / ".retort" / "retort_history.sqlite")
    queued = []
    with queue_path.open("a", encoding="utf-8") as handle:
        for task in tasks:
            queue_id = str(uuid.uuid4())
            row = {
                "queue_id": queue_id,
                "run_id": "task-dispatch-plan-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                "source": "retort_task_dispatch_plan",
                "status": "queued",
                "task": task,
            }
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            store.record_employee_task(_record(queue_id, task))
            queued.append({"queue_id": queue_id, "task_id": task["task_id"]})
    return queued


def _record(queue_id: str, task: dict[str, Any]) -> EmployeeTaskRecord:
    improvement = ImprovementTask(
        task_id=str(task["task_id"]),
        title=str(task["title"]),
        dimension=str(task["dimension"]),
        why=str(task["why"]),
        action=str(task["action"]),
        acceptance=str(task["acceptance"]),
        owner_hint=str(task["owner_hint"]),
        priority=str(task["priority"]),
    )
    return EmployeeTaskRecord(queue_id=queue_id, task=improvement, source="retort_task_dispatch_plan", status="queued")


def _dimension_from_title(title: str) -> str:
    lowered = title.lower()
    if "publish" in lowered or "发布" in title:
        return "product_operability"
    if "benchmark" in lowered or "基准" in title or "误报" in title:
        return "comparative_analysis_depth"
    if "replay" in lowered or "重放" in title or "复盘" in title:
        return "external_ingestion"
    return "absorption_tasking"
