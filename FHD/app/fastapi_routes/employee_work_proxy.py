"""桌面管理端统一员工任务代理。

权威任务台账位于本机 MODstore daily runtime；FHD 只负责校验管理员会话并把
桌面请求代理过去，避免桌面、手机各自再造一套任务状态。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS

router = APIRouter(prefix="/api/xcmax/employee-work", tags=["xcmax-employee-work"])


def _admin_gate(request: Request) -> JSONResponse | None:
    from app.fastapi_routes.xcmax_admin import _require_market_admin_session

    return _require_market_admin_session(request)


def _authenticated_admin_actor_ref(request: Request) -> str:
    """Bind a new ledger item to the exact local administrator session."""

    try:
        from app.infrastructure.auth.dependencies import resolve_session_user

        user = resolve_session_user(request)
        user_id = int(getattr(user, "id", 0) or 0)
        if user_id <= 0 or not bool(getattr(user, "is_active", False)):
            return ""
        tenant_id = int(getattr(user, "tenant_id", None) or 0)
        if tenant_id < 0:
            return ""
        return f"fhd:user:{user_id}:tenant:{tenant_id}"
    except (TypeError, ValueError, *RECOVERABLE_ERRORS):
        return ""


async def _get(path: str, *, query: str = "") -> dict[str, Any] | JSONResponse:
    try:
        from app.application.modstore_local_client import modstore_get, modstore_management_base_url

        return await modstore_get(
            path,
            query=query,
            timeout=30.0,
            base_url=modstore_management_base_url(),
            strict_internal_auth=True,
        )
    except RECOVERABLE_ERRORS:
        return JSONResponse(
            {"success": False, "message": "管理端员工任务服务暂时不可用，请稍后重试"},
            status_code=502,
        )


async def _post(path: str, body: dict[str, Any]) -> dict[str, Any] | JSONResponse:
    try:
        from app.application.modstore_local_client import (
            modstore_management_base_url,
            modstore_post,
        )

        payload = dict(body or {})
        return await modstore_post(
            path,
            json_body=payload,
            timeout=120.0,
            base_url=modstore_management_base_url(),
            strict_internal_auth=True,
        )
    except RECOVERABLE_ERRORS:
        return JSONResponse(
            {"success": False, "message": "管理端员工任务服务暂时不可用，请稍后重试"},
            status_code=502,
        )


@router.get("")
async def desktop_management_work_list(
    request: Request,
    status: str = Query(""),
    owner_employee_id: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
):
    gate = _admin_gate(request)
    if gate is not None:
        return gate
    query = urlencode(
        {
            "status": status,
            "owner_employee_id": owner_employee_id,
            "limit": int(limit),
        }
    )
    return await _get("/api/admin/employee-autonomy/work-items", query=query)


@router.post("")
async def desktop_management_work_create(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
):
    gate = _admin_gate(request)
    if gate is not None:
        return gate
    payload = dict(body or {})
    actor_ref = _authenticated_admin_actor_ref(request)
    if not actor_ref:
        return JSONResponse(
            {"success": False, "message": "管理员会话主体已失效，请重新登录"},
            status_code=401,
        )
    payload.pop("user_id", None)
    payload.pop("created_by_user_id", None)
    payload.pop("external_actor_ref", None)
    payload.pop("source_ref", None)
    payload.setdefault("source_kind", "desktop")
    payload["external_actor_ref"] = actor_ref
    return await _post("/api/admin/employee-autonomy/work-items", payload)


@router.get("/summary")
async def desktop_management_work_summary(request: Request):
    gate = _admin_gate(request)
    if gate is not None:
        return gate
    return await _get("/api/admin/employee-autonomy/work-items/summary")


@router.get("/employees")
async def desktop_management_employees(request: Request):
    gate = _admin_gate(request)
    if gate is not None:
        return gate
    return await _get("/api/admin/employee-autonomy/work-items/employees")


@router.post("/decisions/{decision_id}/resolve")
async def desktop_management_decision_resolve(
    request: Request,
    decision_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
):
    gate = _admin_gate(request)
    if gate is not None:
        return gate
    return await _post(
        f"/api/admin/employee-autonomy/work-items/decisions/{decision_id}/resolve",
        body,
    )


@router.get("/{task_id}")
async def desktop_management_work_detail(request: Request, task_id: str):
    gate = _admin_gate(request)
    if gate is not None:
        return gate
    return await _get(f"/api/admin/employee-autonomy/work-items/{task_id}")


@router.post("/{task_id}/review")
async def desktop_management_work_review(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
):
    gate = _admin_gate(request)
    if gate is not None:
        return gate
    return await _post(
        f"/api/admin/employee-autonomy/work-items/{task_id}/review",
        body,
    )


@router.post("/{task_id}/retry")
async def desktop_management_work_retry(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
):
    gate = _admin_gate(request)
    if gate is not None:
        return gate
    return await _post(
        f"/api/admin/employee-autonomy/work-items/{task_id}/retry",
        body,
    )


@router.post("/{task_id}/cancel")
async def desktop_management_work_cancel(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
):
    gate = _admin_gate(request)
    if gate is not None:
        return gate
    return await _post(
        f"/api/admin/employee-autonomy/work-items/{task_id}/cancel",
        body,
    )


@router.post("/{task_id}/reassign")
async def desktop_management_work_reassign(
    request: Request,
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
):
    gate = _admin_gate(request)
    if gate is not None:
        return gate
    return await _post(
        f"/api/admin/employee-autonomy/work-items/{task_id}/reassign",
        body,
    )
