"""HTTP API for tenant-scoped AI tool registration and employee discovery."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app.application import agent_tool_lifecycle as service
from app.application.agent_tool_lifecycle import Actor, ToolLifecycleError
from app.infrastructure.tenant_scope import current_tenant_id
from app.utils.operational_errors import BOUNDARY_ERRORS

router = APIRouter(prefix="/api/agent-tools", tags=["agent-tools"])


def _fail(exc: ToolLifecycleError) -> JSONResponse:
    error: dict[str, Any] = {"code": exc.code, "message": exc.message}
    error.update(exc.extra)
    return JSONResponse({"ok": False, "error": error}, status_code=exc.status)


def _ok(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data}, status_code=status)


def _tenant() -> int:
    tenant = current_tenant_id()
    if tenant is None:
        raise ToolLifecycleError("tenant_required", "缺少已登录的企业范围", 401)
    return int(tenant)


def _header_auth_enabled() -> bool:
    return (os.environ.get("XCAGI_AGENT_TOOL_HEADER_AUTH") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _role_from_user(user: Any) -> str:
    for attr in ("role", "account_role", "tier"):
        value = str(getattr(user, attr, "") or "").strip().lower()
        if value in {"admin", "employee", "readonly"}:
            return value
    return "employee"


def actor_from_request(request: Request) -> Actor:
    """Resolve the actor from the server session. Client tenant_id is ignored."""
    tenant = _tenant()
    user = None
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user

        user = resolve_session_user(request)
    except BOUNDARY_ERRORS:
        user = None
    if user is not None and getattr(user, "id", None) is not None:
        role = _role_from_user(user)
        employee_id = str(getattr(user, "employee_id", "") or user.id)
        return Actor(str(user.id), role, None if role == "admin" else employee_id, tenant)
    if not _header_auth_enabled():
        raise ToolLifecycleError("auth_required", "请先登录后再管理工具", 401)
    role = str(request.headers.get("X-Actor-Role") or "").strip().lower()
    actor_id = str(request.headers.get("X-Actor-Id") or "").strip()
    if role not in {"admin", "employee", "readonly"} or not actor_id:
        raise ToolLifecycleError("auth_required", "请先登录后再管理工具", 401)
    employee_header = str(request.headers.get("X-Employee-Id") or "").strip()
    if role != "admin" and employee_header and employee_header != actor_id:
        raise ToolLifecycleError("forged_employee", "员工不存在", 404)
    employee_id = None if role == "admin" else actor_id
    return Actor(actor_id, role, employee_id, tenant)


def _run(action: Any) -> JSONResponse:
    try:
        return action()
    except ToolLifecycleError as exc:
        return _fail(exc)


@router.post("/employees")
def register_employee(request: Request, body: dict = Body(default_factory=dict)) -> JSONResponse:
    return _run(lambda: _ok(service.register_principal(actor_from_request(request), body), 201))


@router.get("/discovery")
def employee_discovery(request: Request) -> JSONResponse:
    return _run(lambda: _ok(service.discovery(actor_from_request(request))))


@router.get("/audit")
def audit_log(request: Request, tool_id: str | None = None) -> JSONResponse:
    return _run(lambda: _ok(service.list_audit(actor_from_request(request), tool_id)))


@router.post("/permissions")
def grant_or_deny(request: Request, body: dict = Body(default_factory=dict)) -> JSONResponse:
    return _run(lambda: _ok(service.set_permission(actor_from_request(request), body), 201))


@router.post("/permissions/{permission_id}/revoke")
def revoke_permission(request: Request, permission_id: str) -> JSONResponse:
    return _run(lambda: _ok(service.revoke_permission(actor_from_request(request), permission_id)))


@router.post("/calls/{call_id}/finish")
def finish_call(request: Request, call_id: str) -> JSONResponse:
    return _run(lambda: _ok(service.finish_call(actor_from_request(request), call_id)))


@router.post("")
def create_tool(request: Request, body: dict = Body(default_factory=dict)) -> JSONResponse:
    return _run(lambda: _ok(service.create_tool(actor_from_request(request), body), 201))


@router.get("")
def list_tools(request: Request) -> JSONResponse:
    return _run(
        lambda: _ok(service.list_tools(actor_from_request(request), dict(request.query_params)))
    )


@router.get("/{tool_id}")
def get_tool(request: Request, tool_id: str) -> JSONResponse:
    return _run(lambda: _ok(service.get_tool(actor_from_request(request), tool_id)))


@router.put("/{tool_id}")
def update_tool(
    request: Request, tool_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    return _run(lambda: _ok(service.update_tool(actor_from_request(request), tool_id, body)))


@router.post("/{tool_id}/validate")
def validate_tool(
    request: Request, tool_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    return _run(
        lambda: _ok(service.validate_tool_schema(actor_from_request(request), tool_id, body))
    )


@router.post("/{tool_id}/publish")
def publish_tool(
    request: Request, tool_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    return _run(lambda: _ok(service.publish_tool(actor_from_request(request), tool_id, body)))


@router.post("/{tool_id}/unpublish")
def unpublish_tool(request: Request, tool_id: str) -> JSONResponse:
    return _run(lambda: _ok(service.unpublish_tool(actor_from_request(request), tool_id)))


@router.post("/{tool_id}/offline")
def offline_tool(request: Request, tool_id: str) -> JSONResponse:
    return _run(lambda: _ok(service.offline_tool(actor_from_request(request), tool_id)))


@router.post("/{tool_id}/relist")
def relist_tool(request: Request, tool_id: str) -> JSONResponse:
    return _run(lambda: _ok(service.relist_tool(actor_from_request(request), tool_id)))


@router.post("/{tool_id}/rollback")
def rollback_tool(
    request: Request, tool_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    return _run(lambda: _ok(service.rollback_tool(actor_from_request(request), tool_id, body)))


@router.post("/{tool_id}/deprecate")
def deprecate_tool(
    request: Request, tool_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    return _run(lambda: _ok(service.deprecate_version(actor_from_request(request), tool_id, body)))


@router.post("/{tool_id}/invoke")
def invoke_tool(
    request: Request, tool_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    return _run(lambda: _ok(service.invoke_tool(actor_from_request(request), tool_id, body)))


@router.post("/{tool_id}/calls")
def begin_call(
    request: Request, tool_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    return _run(lambda: _ok(service.begin_call(actor_from_request(request), tool_id, body), 201))
