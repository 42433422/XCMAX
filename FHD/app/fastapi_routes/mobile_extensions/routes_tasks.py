"""TaskRoutes: 移动端读取桌面/云端统一任务（只读，P0 合流）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.application.mobile_extensions.protocols import MobilePrincipal, UserDependency
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS


class TaskListCall(Protocol):
    def __call__(
        self,
        *,
        user_id: str,
        tenant_id: str,
        limit: int,
        include_archived: bool,
    ) -> list[Any]: ...


class TaskGetCall(Protocol):
    def __call__(self, *, user_id: str, tenant_id: str, task_id: str) -> Any | None: ...


@dataclass(frozen=True)
class TaskRoutesPorts:
    list_tasks: TaskListCall
    get_task: TaskGetCall


def _json_payload(task: Any) -> dict[str, Any]:
    if hasattr(task, "to_dict"):
        payload = task.to_dict()
        if isinstance(payload, dict):
            return dict(payload)
    return {}


def task_summary(task: Any) -> dict[str, Any]:
    """移动端任务摘要：只暴露展示需要的字段。"""
    payload = _json_payload(task)
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    progress = payload.get("progress")
    if not isinstance(progress, dict):
        progress = {}
    try:
        percent = int(progress.get("percent") or 0)
    except (TypeError, ValueError):
        percent = 0
    return {
        "task_id": str(payload.get("task_id") or ""),
        "title": str(payload.get("title") or ""),
        "status": str(payload.get("status") or ""),
        "attention_state": str(payload.get("attention_state") or ""),
        "approval_required": bool(payload.get("approval_required")),
        "workspace_id": str(payload.get("workspace_id") or ""),
        "workspace_isolation": str(payload.get("workspace_isolation") or ""),
        "conversation_id": str(payload.get("conversation_id") or ""),
        "execution_target": str(metadata.get("execution_target") or "cloud"),
        "progress_percent": max(0, min(100, percent)),
        "updated_at": str(payload.get("updated_at") or ""),
    }


class TaskRoutes:
    def __init__(self, ports: TaskRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        def _unauthorized() -> JSONResponse:
            return JSONResponse(
                format_mobile_response(None, "未授权", success=False, code=401),
                status_code=401,
            )

        def _scope(user: MobilePrincipal) -> tuple[str, str]:
            return str(user.id), str(getattr(user, "tenant_id", "") or "")

        @router.get("/tasks", response_model=None)
        async def mobile_task_list(
            limit: int = Query(default=50, ge=1, le=200),
            include_archived: bool = Query(default=False),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            if user is None:
                return _unauthorized()
            user_id, tenant_id = _scope(user)
            try:
                tasks = ports.list_tasks(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    limit=limit,
                    include_archived=include_archived,
                )
                items = [task_summary(task) for task in tasks]
                return format_mobile_response({"items": items, "count": len(items)})
            except RECOVERABLE_ERRORS:
                return JSONResponse(
                    format_mobile_response(
                        None, "任务列表加载失败，请稍后重试", success=False, code=500
                    ),
                    status_code=500,
                )

        @router.get("/tasks/{task_id}", response_model=None)
        async def mobile_task_detail(
            task_id: str,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            if user is None:
                return _unauthorized()
            user_id, tenant_id = _scope(user)
            try:
                task = ports.get_task(user_id=user_id, tenant_id=tenant_id, task_id=task_id)
            except RECOVERABLE_ERRORS:
                return JSONResponse(
                    format_mobile_response(
                        None, "任务加载失败，请稍后重试", success=False, code=500
                    ),
                    status_code=500,
                )
            if task is None:
                return JSONResponse(
                    format_mobile_response(None, "任务不存在或无权查看", success=False, code=404),
                    status_code=404,
                )
            return format_mobile_response(task_summary(task))

        self.mobile_task_list = mobile_task_list
        self.mobile_task_detail = mobile_task_detail


__all__ = ["TaskRoutes", "TaskRoutesPorts", "task_summary"]
