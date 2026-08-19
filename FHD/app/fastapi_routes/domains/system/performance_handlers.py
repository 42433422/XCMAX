"""Performance response projection helpers for system routes."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS


def performance_tasks_status_payload(task_id: str | None = None):
    try:
        from app.utils.performance.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.async_task_manager:
            return JSONResponse(
                {"success": False, "message": "异步任务管理未启用", "data": None},
                status_code=503,
            )
        if task_id:
            result = optimizer.async_task_manager.get_status(task_id)
            if result is None:
                return JSONResponse(
                    {"success": False, "message": "任务不存在", "data": None},
                    status_code=404,
                )
            return {
                "success": True,
                "data": {
                    "task_id": result.task_id,
                    "status": result.status.value,
                    "progress": result.progress,
                    "duration_ms": round(result.duration_ms, 2) if result.duration_ms else None,
                    "error": result.error,
                    "metadata": result.metadata,
                },
            }
        active_tasks = optimizer.async_task_manager.active_tasks
        return {
            "success": True,
            "data": {
                "active_tasks": (
                    {
                        tid: {
                            "task_id": task.task_id,
                            "status": task.status.value,
                            "progress": task.progress,
                            "name": task.metadata.get("task_name", ""),
                        }
                        for tid, task in (active_tasks or {}).items()
                    }
                    if active_tasks
                    else {}
                ),
                "stats": optimizer.async_task_manager.stats,
            },
        }
    except RECOVERABLE_ERRORS as exc:
        return JSONResponse(
            {"success": False, "message": str(exc), "data": None}, status_code=500
        )
