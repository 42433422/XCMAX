from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def build_task_prioritization_report(project: str | Path) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    queue_items = _jsonl(root / ".retort" / "employee_queue.jsonl")
    employee_results = _employee_results(root)
    dimension_counts = Counter(str(((item.get("task") or {}) if isinstance(item.get("task"), dict) else {}).get("dimension") or "unknown") for item in queue_items)
    completed = [item for item in employee_results if item.get("status") == "completed"]
    priorities = []
    for dimension, count in dimension_counts.most_common():
        completed_count = sum(1 for item in completed if dimension in json.dumps(item, ensure_ascii=False))
        priorities.append(
            {
                "dimension": dimension,
                "queued_count": count,
                "completed_evidence_count": completed_count,
                "priority": "P1" if count >= 3 else "P2",
                "next_action": f"replay_and_verify_{dimension}",
            }
        )
    return {
        "status": "ready" if priorities and completed else "needs_history",
        "project": str(root),
        "summary": {
            "queued_task_count": len(queue_items),
            "employee_result_count": len(employee_results),
            "completed_result_count": len(completed),
            "prioritized_dimension_count": len(priorities),
        },
        "priorities": priorities,
        "evidence": {
            "queue_path": str(root / ".retort" / "employee_queue.jsonl"),
            "employee_results_dir": str(root / ".retort" / "employee_results"),
        },
    }


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _employee_results(root: Path) -> list[dict[str, Any]]:
    result_dir = root / ".retort" / "employee_results"
    rows: list[dict[str, Any]] = []
    for path in sorted(result_dir.glob("*.json")) if result_dir.is_dir() else []:
        if path.name.endswith(".worker_review.json"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.extend(item for item in payload.get("results") or [] if isinstance(item, dict))
    return rows
