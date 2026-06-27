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
    feedback_counts = _dimension_feedback_counts(employee_results, set(dimension_counts))
    priorities = []
    dimensions = sorted(dimension_counts, key=lambda item: (feedback_counts.get(item, 0), dimension_counts[item]), reverse=True)
    for dimension in dimensions:
        count = dimension_counts[dimension]
        completed_count = sum(1 for item in completed if dimension in json.dumps(item, ensure_ascii=False))
        feedback_count = feedback_counts.get(dimension, 0)
        priorities.append(
            {
                "dimension": dimension,
                "owner_hint": _owner_for_dimension(dimension),
                "queued_count": count,
                "completed_evidence_count": completed_count,
                "employee_feedback_count": feedback_count,
                "feedback_driven": feedback_count > 0,
                "priority": "P0" if feedback_count > 0 else ("P1" if count >= 3 else "P2"),
                "next_action": f"feedback_driven_replay_and_verify_{dimension}" if feedback_count > 0 else f"replay_and_verify_{dimension}",
                "acceptance": f"Next absorption run improves or preserves {dimension} with post-tests passing.",
                "evidence_required": ["queued_task_id", "employee_result", "post_absorption_test", "replay_report"],
                "ready_for_employee": True,
            }
        )
    ready_count = sum(1 for item in priorities if item.get("ready_for_employee") and item.get("acceptance") and item.get("evidence_required"))
    feedback_priority_count = sum(1 for item in priorities if item.get("feedback_driven"))
    return {
        "status": "ready" if priorities and completed else "needs_history",
        "project": str(root),
        "summary": {
            "queued_task_count": len(queue_items),
            "employee_result_count": len(employee_results),
            "completed_result_count": len(completed),
            "prioritized_dimension_count": len(priorities),
            "ready_employee_task_count": ready_count,
            "feedback_driven_priority_count": feedback_priority_count,
            "employee_feedback_applied": feedback_priority_count > 0,
            "all_tasks_have_acceptance": bool(priorities) and ready_count == len(priorities),
        },
        "priorities": priorities,
        "evidence": {
            "queue_path": str(root / ".retort" / "employee_queue.jsonl"),
            "employee_results_dir": str(root / ".retort" / "employee_results"),
        },
    }


def _dimension_feedback_counts(employee_results: list[dict[str, Any]], queued_dimensions: set[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    markers = ("failed", "missing", "gap", "blocker", "risk", "regression", "不足", "失败", "缺口", "风险", "建议", "下一轮")
    for item in employee_results:
        text = json.dumps(item, ensure_ascii=False).lower()
        if not any(marker in text for marker in markers):
            continue
        dimensions = _dimensions_in_result(item, queued_dimensions)
        for dimension in dimensions:
            counts[dimension] += 1
    return counts


def _dimensions_in_result(item: dict[str, Any], queued_dimensions: set[str]) -> set[str]:
    dimensions: set[str] = set()
    task = item.get("task") if isinstance(item.get("task"), dict) else {}
    if task.get("dimension"):
        dimensions.add(str(task["dimension"]))
    text = json.dumps(item, ensure_ascii=False)
    for dimension in queued_dimensions:
        if dimension and dimension in text:
            dimensions.add(dimension)
    return dimensions


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


def _owner_for_dimension(dimension: str) -> str:
    if "operability" in dimension:
        return "product-runtime"
    if "comparative" in dimension or "external" in dimension:
        return "absorption-review"
    if "feedback" in dimension:
        return "feedback-runtime"
    return "retort-maintainer"
