"""Mobile 超级员工 Codex/Claude/Cursor/Trae 消息与 SSE routes (split from mobile_api_extensions).

Included into ``extension_router``; handlers and helpers are re-exported from
``mobile_api_extensions`` for tests and patch compatibility.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.fastapi_routes.mobile_api import get_mobile_user
from app.fastapi_routes.mobile_extensions import _ext as mext
from app.utils.mobile_api import format_mobile_response

logger = logging.getLogger(__name__)

super_employee_router = APIRouter()

from app.fastapi_routes.mobile_extensions.employee_routes import _sse_line
from app.fastapi_routes.mobile_extensions.models import (
    ClaudeSuperEmployeeMobileMessageBody,
    CodexSuperEmployeeMobileMessageBody,
    CursorSuperEmployeeMobileMessageBody,
    TraeSuperEmployeeMobileMessageBody,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

RECOVERABLE_ERRORS = RECOVERABLE_ERRORS

@super_employee_router.get("/admin/codex-super-employee/messages")
async def mobile_admin_codex_super_employee_messages(
    request: Request,
    limit: int = Query(default=80, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的 Codex 超级员工对话记录（仅管理端）。"""
    _, err = mext._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = mext._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        messages = mext.CodexSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return format_mobile_response(data={"messages": messages})
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_admin_codex_super_employee_messages")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@super_employee_router.post("/admin/codex-super-employee/messages")
async def mobile_admin_codex_super_employee_invoke(
    request: Request,
    body: CodexSuperEmployeeMobileMessageBody,
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的软件内 Codex 调用入口（仅管理端）。"""
    _, err = mext._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = mext._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    text = (body.message or body.body or "").strip()
    context = dict(body.context or {})
    context.setdefault("source", "mobile_im")
    context.setdefault("client_surface", "mobile")
    context.setdefault("target_devices", ["all"])
    if not str(context.get("workspace_root") or "").strip():
        from app.application.relay_workspace import resolve_verified_relay_workspace_root

        root = resolve_verified_relay_workspace_root({"source": "mobile_im"})
        if root:
            context["workspace_root"] = root
    # 本路由已收口为仅管理端可达；管理账号铸造工厂授权。
    if (
        str((mext._mobile_session_meta(request) or {}).get("account_kind") or "").strip().lower()
        == "admin"
    ):
        _wsid = str(getattr(body, "workspace_id", "") or context.get("workspace_id") or "xcmax")
        context = mext.factory_context(workspace_id=_wsid, base=context)
    try:
        result = mext.CodexSuperEmployeeService().invoke(
            user_id=uid,
            message=text,
            context=context,
        )
        return format_mobile_response(data=result)
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400),
            status_code=400,
        )
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_admin_codex_super_employee_invoke")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@super_employee_router.get("/admin/claude-super-employee/messages")
async def mobile_admin_claude_super_employee_messages(
    request: Request,
    limit: int = Query(default=80, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的 Claude 超级员工对话记录（仅管理端）。"""
    _, err = mext._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = mext._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        messages = mext.ClaudeSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return format_mobile_response(data={"messages": messages})
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_admin_claude_super_employee_messages")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@super_employee_router.post("/admin/claude-super-employee/messages")
async def mobile_admin_claude_super_employee_invoke(
    request: Request,
    body: ClaudeSuperEmployeeMobileMessageBody,
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的软件内 Claude 调用入口（仅管理端）。"""
    _, err = mext._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = mext._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    text = (body.message or body.body or "").strip()
    context = dict(body.context or {})
    context.setdefault("source", "mobile_im")
    context.setdefault("client_surface", "mobile")
    context.setdefault("target_devices", ["all"])
    if not str(context.get("workspace_root") or "").strip():
        from app.application.relay_workspace import resolve_verified_relay_workspace_root

        root = resolve_verified_relay_workspace_root({"source": "mobile_im"})
        if root:
            context["workspace_root"] = root
    # 本路由已收口为仅管理端可达；管理账号铸造工厂授权。
    if (
        str((mext._mobile_session_meta(request) or {}).get("account_kind") or "").strip().lower()
        == "admin"
    ):
        _wsid = str(getattr(body, "workspace_id", "") or context.get("workspace_id") or "xcmax")
        context = mext.factory_context(workspace_id=_wsid, base=context)
    try:
        result = mext.ClaudeSuperEmployeeService().invoke(
            user_id=uid,
            message=text,
            context=context,
        )
        return format_mobile_response(data=result)
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400),
            status_code=400,
        )
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_admin_claude_super_employee_invoke")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@super_employee_router.get("/admin/cursor-super-employee/messages")
async def mobile_admin_cursor_super_employee_messages(
    request: Request,
    limit: int = Query(default=80, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的 Cursor 超级员工对话记录（仅管理端）。"""
    _, err = mext._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = mext._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        messages = mext.CursorSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return format_mobile_response(data={"messages": messages})
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_admin_cursor_super_employee_messages")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@super_employee_router.post("/admin/cursor-super-employee/messages")
async def mobile_admin_cursor_super_employee_invoke(
    request: Request,
    body: CursorSuperEmployeeMobileMessageBody,
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的软件内 Cursor 调用入口（仅管理端）。"""
    _, err = mext._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = mext._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    text = (body.message or body.body or "").strip()
    context = dict(body.context or {})
    context.setdefault("source", "mobile_im")
    context.setdefault("client_surface", "mobile")
    context.setdefault("device_scope", "all_devices")
    context.setdefault("target_devices", ["all"])
    if not str(context.get("workspace_root") or "").strip():
        from app.application.relay_workspace import resolve_verified_relay_workspace_root

        root = resolve_verified_relay_workspace_root({"source": "mobile_im"})
        if root:
            context["workspace_root"] = root
    # 与 Codex/Claude/Trae 对齐：管理账号铸造工厂授权。
    if (
        str((mext._mobile_session_meta(request) or {}).get("account_kind") or "").strip().lower()
        == "admin"
    ):
        _wsid = str(getattr(body, "workspace_id", "") or context.get("workspace_id") or "xcmax")
        context = mext.factory_context(workspace_id=_wsid, base=context)
    try:
        result = mext.CursorSuperEmployeeService().invoke(
            user_id=uid,
            message=text,
            context=context,
        )
        return format_mobile_response(data=result)
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400),
            status_code=400,
        )
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_admin_cursor_super_employee_invoke")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@super_employee_router.get("/admin/trae-super-employee/messages")
async def mobile_admin_trae_super_employee_messages(
    request: Request,
    limit: int = Query(default=80, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的 Trae 超级员工对话记录（仅管理端）。"""
    _, err = mext._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = mext._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        messages = mext.TraeSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return format_mobile_response(data={"messages": messages})
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_admin_trae_super_employee_messages")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@super_employee_router.post("/admin/trae-super-employee/messages")
async def mobile_admin_trae_super_employee_invoke(
    request: Request,
    body: TraeSuperEmployeeMobileMessageBody,
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的软件内 Trae 调用入口（仅管理端）。"""
    _, err = mext._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = mext._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    text = (body.message or body.body or "").strip()
    context = dict(body.context or {})
    context.setdefault("source", "mobile_im")
    context.setdefault("client_surface", "mobile")
    context.setdefault("device_scope", "all_devices")
    context.setdefault("target_devices", ["all"])
    if not str(context.get("workspace_root") or "").strip():
        from app.application.relay_workspace import resolve_verified_relay_workspace_root

        root = resolve_verified_relay_workspace_root({"source": "mobile_im"})
        if root:
            context["workspace_root"] = root
    if (
        str((mext._mobile_session_meta(request) or {}).get("account_kind") or "").strip().lower()
        == "admin"
    ):
        _wsid = str(getattr(body, "workspace_id", "") or context.get("workspace_id") or "xcmax")
        context = mext.factory_context(workspace_id=_wsid, base=context)
    try:
        result = mext.TraeSuperEmployeeService().invoke(
            user_id=uid,
            message=text,
            context=context,
        )
        return format_mobile_response(data=result)
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400),
            status_code=400,
        )
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_admin_trae_super_employee_invoke")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@super_employee_router.get("/admin/factory/workspaces")
async def mobile_admin_factory_workspaces(
    request: Request,
    user=Depends(get_mobile_user),
):
    """手机端可选工厂 Workspace（与桌面项目工厂同源注册表）。"""
    _, err = mext._require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    try:
        from app.application.workspaces import get_workspace_registry

        items = [
            {
                "id": ws.id,
                "label": ws.label,
                "isolation": ws.isolation,
                "default_branch": ws.default_branch,
                "vcs_kind": ws.vcs_kind,
                "root": str(ws.root),
            }
            for ws in get_workspace_registry().list()
        ]
        return format_mobile_response(data={"workspaces": items})
    except mext.RECOVERABLE_ERRORS:
        logger.exception("mobile_admin_factory_workspaces")
        return JSONResponse(
            format_mobile_response(None, "加载项目列表失败", success=False, code=500),
            status_code=500,
        )


# ── 超级员工 LAN SSE 流式直答 ──


def _super_employee_service_for_tool(tool: str):
    """根据工具名返回对应的 SuperEmployeeService 实例。"""
    tool_lower = (tool or "").strip().lower()
    if tool_lower == "codex":
        return mext.CodexSuperEmployeeService()
    if tool_lower == "claude":
        return mext.ClaudeSuperEmployeeService()
    if tool_lower == "cursor":
        return mext.CursorSuperEmployeeService()
    if tool_lower == "trae":
        return mext.TraeSuperEmployeeService()
    return None


async def _stream_super_employee_invoke(
    request: Request,
    tool: str,
    body: dict[str, Any],
    user,
):
    """超级员工 SSE 流式直答的共享实现。"""
    _, err = mext._require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = mext._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    service = _super_employee_service_for_tool(tool)
    if service is None:
        return JSONResponse(
            format_mobile_response(None, f"未知超级员工工具：{tool}", success=False, code=400),
            status_code=400,
        )
    text = str((body or {}).get("message") or (body or {}).get("body") or "").strip()
    if not text:
        return JSONResponse(
            format_mobile_response(None, "message 必填", success=False, code=400),
            status_code=400,
        )
    context = dict((body or {}).get("context") or {})
    context.setdefault("source", "mobile_im")
    context.setdefault("client_surface", "mobile")
    context.setdefault("target_devices", ["all"])
    # 手机局域网直连：注入本机工程根，便于只读问答读到真实仓库（非临时 scratch）。
    if not str(context.get("workspace_root") or "").strip():
        from app.application.relay_workspace import resolve_verified_relay_workspace_root

        root = resolve_verified_relay_workspace_root({"source": "mobile_im"})
        if root:
            context["workspace_root"] = root
    if (
        str((mext._mobile_session_meta(request) or {}).get("account_kind") or "").strip().lower()
        == "admin"
    ):
        _wsid = str((body or {}).get("workspace_id") or context.get("workspace_id") or "xcmax")
        context = mext.factory_context(workspace_id=_wsid, base=context)

    async def sse_gen():
        try:
            async for event in service.invoke_stream(
                user_id=uid,
                message=text,
                context=context,
            ):
                yield _sse_line(event)
        except Exception as exc:  # noqa: BLE001
            logger.exception("mobile_super_employee_stream failed: %s", exc)
            yield _sse_line({"type": "error", "message": f"流式调用失败：{exc}"})

    return StreamingResponse(
        sse_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@super_employee_router.post("/admin/codex-super-employee/messages/stream")
async def mobile_admin_codex_super_employee_stream(
    request: Request,
    body: dict[str, Any],
    user=Depends(get_mobile_user),
):
    """移动端 Codex 超级员工 LAN SSE 流式直答。"""
    return await _stream_super_employee_invoke(request, "codex", body, user)


@super_employee_router.post("/admin/claude-super-employee/messages/stream")
async def mobile_admin_claude_super_employee_stream(
    request: Request,
    body: dict[str, Any],
    user=Depends(get_mobile_user),
):
    """移动端 Claude 超级员工 LAN SSE 流式直答。"""
    return await _stream_super_employee_invoke(request, "claude", body, user)


@super_employee_router.post("/admin/cursor-super-employee/messages/stream")
async def mobile_admin_cursor_super_employee_stream(
    request: Request,
    body: dict[str, Any],
    user=Depends(get_mobile_user),
):
    """移动端 Cursor 超级员工 LAN SSE 流式直答。"""
    return await _stream_super_employee_invoke(request, "cursor", body, user)


@super_employee_router.post("/admin/trae-super-employee/messages/stream")
async def mobile_admin_trae_super_employee_stream(
    request: Request,
    body: dict[str, Any],
    user=Depends(get_mobile_user),
):
    """移动端 Trae 超级员工 LAN SSE 流式直答。"""
    return await _stream_super_employee_invoke(request, "trae", body, user)
