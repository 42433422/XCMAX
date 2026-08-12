"""Canonical progress snapshots for durable Agent tasks."""

from __future__ import annotations

from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun

_SETTLED_STEP_STATES = {"completed", "failed", "skipped"}
_STATUS_LABELS = {
    "queued": "排队中",
    "planning": "正在生成执行计划",
    "running": "执行中",
    "retrying": "正在重试",
    "waiting_user": "等待审批或用户确认",
    "paused": "已暂停，可继续",
    "blocked": "等待依赖解除",
    "completed": "任务完成",
    "failed": "执行失败",
    "cancelled": "已取消",
}


def _clamp_percent(value: int) -> int:
    return max(0, min(100, int(value)))


def _attempt_number(value: Any) -> int:
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


def task_progress_snapshot(run: AgentRun) -> dict[str, Any]:
    """Build one honest, durable progress representation from an AgentRun.

    Step completion is the only determinate unit. Terminal success is always
    100%; failed/cancelled runs are capped below 100 so skipped work is not
    presented as successfully completed.
    """

    status = str(run.status or "queued")
    steps = list(run.steps or [])
    total = len(steps)
    completed = sum(step.status == "completed" for step in steps)
    settled = sum(step.status in _SETTLED_STEP_STATES for step in steps)
    current = next(
        (step for step in steps if step.status not in _SETTLED_STEP_STATES),
        steps[-1] if steps else None,
    )
    current_index = steps.index(current) + 1 if current is not None else 0

    if total:
        percent = _clamp_percent(round((settled / total) * 100))
        if status != "completed":
            percent = min(99, percent)
    else:
        percent = 100 if status == "completed" else 0

    control_request = run.metadata.get("control_request")
    control_action = (
        str(control_request.get("action") or "")
        if isinstance(control_request, dict)
        and str(control_request.get("status") or "") == "requested"
        else ""
    )
    if control_action == "pause":
        stage = "正在请求暂停"
    elif control_action == "cancel":
        stage = "正在请求取消"
    else:
        stage = _STATUS_LABELS.get(status, "状态待同步")

    step_label = ""
    if current is not None:
        step_label = str(current.description or f"{current.tool_id}.{current.action}").strip()

    task_context = run.metadata.get("task_context")
    attempt = _attempt_number(task_context.get("attempt")) if isinstance(task_context, dict) else 1
    return {
        "percent": percent,
        "completed_units": completed,
        "settled_units": settled,
        "total_units": total,
        "current_unit": current_index,
        "stage": stage,
        "detail": step_label,
        "status": status,
        "attempt": attempt,
        "indeterminate": total == 0 and status != "completed",
        "basis": "steps" if total else "status",
        "updated_at": run.updated_at,
    }


def progress_snapshot_of_task_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Read the persisted canonical progress snapshot without exposing aliases."""

    raw = (metadata or {}).get("progress")
    return dict(raw) if isinstance(raw, dict) else {}


def fallback_task_progress_snapshot(
    *, status: str, attempt: int, updated_at: str
) -> dict[str, Any]:
    """Return a complete status-only snapshot for legacy task rows."""

    normalized_status = str(status or "queued")
    return {
        "percent": 100 if normalized_status == "completed" else 0,
        "completed_units": 0,
        "settled_units": 0,
        "total_units": 0,
        "current_unit": 0,
        "stage": _STATUS_LABELS.get(normalized_status, "状态待同步"),
        "detail": "",
        "status": normalized_status,
        "attempt": _attempt_number(attempt),
        "indeterminate": normalized_status != "completed",
        "basis": "status",
        "updated_at": str(updated_at or ""),
    }


__all__ = [
    "fallback_task_progress_snapshot",
    "progress_snapshot_of_task_metadata",
    "task_progress_snapshot",
]
