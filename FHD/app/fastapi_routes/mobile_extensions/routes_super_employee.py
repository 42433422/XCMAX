"""Super-employee mobile routes (strangler extract)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.fastapi_routes.mobile_api import get_mobile_user
from app.fastapi_routes.mobile_extensions.models import (
    ClaudeSuperEmployeeMobileMessageBody,
    CodexSuperEmployeeMobileMessageBody,
    CursorSuperEmployeeMobileMessageBody,
    TraeSuperEmployeeMobileMessageBody,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router: APIRouter = APIRouter()


def _parent():
    """Resolve patchable symbols from parent module (tests patch parent paths)."""
    from app.fastapi_routes import mobile_api_extensions as parent

    return parent


@router.get("/admin/codex-super-employee/messages")
async def mobile_admin_codex_super_employee_messages(
    request: Request,
    limit: int = Query(default=80, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的 Codex 超级员工对话记录（仅管理端）。"""
    _, err = _parent()._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = _parent()._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        messages = _parent().CodexSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return format_mobile_response(data={"messages": messages})
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_admin_codex_super_employee_messages")
        return JSONResponse(
            format_mobile_response(None, "超级员工服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.post("/admin/codex-super-employee/messages")
async def mobile_admin_codex_super_employee_invoke(
    request: Request,
    body: CodexSuperEmployeeMobileMessageBody,
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的软件内 Codex 调用入口（仅管理端）。"""
    _, err = _parent()._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = _parent()._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    text = (body.message or body.body or "").strip()
    if not text:
        return JSONResponse(
            format_mobile_response(None, "message 不能为空", success=False, code=400),
            status_code=400,
        )
    context = dict(body.context or {})
    context.setdefault("source", "mobile_im")
    context.setdefault("client_surface", "mobile")
    context.setdefault("target_devices", ["all"])
    # 本路由已收口为仅管理端可达；管理账号铸造工厂授权。
    if (
        str((_parent()._mobile_session_meta(request) or {}).get("account_kind") or "")
        .strip()
        .lower()
        == "admin"
    ):
        _wsid = str(getattr(body, "workspace_id", "") or context.get("workspace_id") or "xcmax")
        context = _parent().factory_context(workspace_id=_wsid, base=context)
    try:
        result = (
            _parent()
            .CodexSuperEmployeeService()
            .invoke(
                user_id=uid,
                message=text,
                context=context,
            )
        )
        return format_mobile_response(data=result)
    except ValueError:
        return JSONResponse(
            format_mobile_response(None, "超级员工请求无效", success=False, code=400),
            status_code=400,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_admin_codex_super_employee_invoke")
        return JSONResponse(
            format_mobile_response(None, "超级员工服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.get("/admin/claude-super-employee/messages")
async def mobile_admin_claude_super_employee_messages(
    request: Request,
    limit: int = Query(default=80, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的 Claude 超级员工对话记录（仅管理端）。"""
    _, err = _parent()._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = _parent()._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        messages = _parent().ClaudeSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return format_mobile_response(data={"messages": messages})
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_admin_claude_super_employee_messages")
        return JSONResponse(
            format_mobile_response(None, "超级员工服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.post("/admin/claude-super-employee/messages")
async def mobile_admin_claude_super_employee_invoke(
    request: Request,
    body: ClaudeSuperEmployeeMobileMessageBody,
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的软件内 Claude 调用入口（仅管理端）。"""
    _, err = _parent()._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = _parent()._mobile_request_user_id(request, user)
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
    # 本路由已收口为仅管理端可达；管理账号铸造工厂授权。
    if (
        str((_parent()._mobile_session_meta(request) or {}).get("account_kind") or "")
        .strip()
        .lower()
        == "admin"
    ):
        _wsid = str(getattr(body, "workspace_id", "") or context.get("workspace_id") or "xcmax")
        context = _parent().factory_context(workspace_id=_wsid, base=context)
    try:
        result = (
            _parent()
            .ClaudeSuperEmployeeService()
            .invoke(
                user_id=uid,
                message=text,
                context=context,
            )
        )
        return format_mobile_response(data=result)
    except ValueError:
        return JSONResponse(
            format_mobile_response(None, "超级员工请求无效", success=False, code=400),
            status_code=400,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_admin_claude_super_employee_invoke")
        return JSONResponse(
            format_mobile_response(None, "超级员工服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.get("/admin/cursor-super-employee/messages")
async def mobile_admin_cursor_super_employee_messages(
    request: Request,
    limit: int = Query(default=80, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的 Cursor 超级员工对话记录（仅管理端）。"""
    _, err = _parent()._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = _parent()._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        messages = _parent().CursorSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return format_mobile_response(data={"messages": messages})
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_admin_cursor_super_employee_messages")
        return JSONResponse(
            format_mobile_response(None, "超级员工服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.post("/admin/cursor-super-employee/messages")
async def mobile_admin_cursor_super_employee_invoke(
    request: Request,
    body: CursorSuperEmployeeMobileMessageBody,
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的软件内 Cursor 调用入口（仅管理端）。"""
    _, err = _parent()._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = _parent()._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    text = (body.message or body.body or "").strip()
    context = dict(body.context or {})
    context.setdefault("source", "mobile_im")
    context.setdefault("device_scope", "all_devices")
    context.setdefault("target_devices", ["all"])
    try:
        result = (
            _parent()
            .CursorSuperEmployeeService()
            .invoke(
                user_id=uid,
                message=text,
                context=context,
            )
        )
        return format_mobile_response(data=result)
    except ValueError:
        return JSONResponse(
            format_mobile_response(None, "超级员工请求无效", success=False, code=400),
            status_code=400,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_admin_cursor_super_employee_invoke")
        return JSONResponse(
            format_mobile_response(None, "超级员工服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.get("/admin/trae-super-employee/messages")
async def mobile_admin_trae_super_employee_messages(
    request: Request,
    limit: int = Query(default=80, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的 Trae 超级员工对话记录（仅管理端）。"""
    _, err = _parent()._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = _parent()._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        messages = _parent().TraeSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return format_mobile_response(data={"messages": messages})
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_admin_trae_super_employee_messages")
        return JSONResponse(
            format_mobile_response(None, "超级员工服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.post("/admin/trae-super-employee/messages")
async def mobile_admin_trae_super_employee_invoke(
    request: Request,
    body: TraeSuperEmployeeMobileMessageBody,
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的软件内 Trae 调用入口（仅管理端）。"""
    _, err = _parent()._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = _parent()._mobile_request_user_id(request, user)
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
    if (
        str((_parent()._mobile_session_meta(request) or {}).get("account_kind") or "")
        .strip()
        .lower()
        == "admin"
    ):
        _wsid = str(getattr(body, "workspace_id", "") or context.get("workspace_id") or "xcmax")
        context = _parent().factory_context(workspace_id=_wsid, base=context)
    try:
        result = (
            _parent()
            .TraeSuperEmployeeService()
            .invoke(
                user_id=uid,
                message=text,
                context=context,
            )
        )
        return format_mobile_response(data=result)
    except ValueError:
        return JSONResponse(
            format_mobile_response(None, "超级员工请求无效", success=False, code=400),
            status_code=400,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_admin_trae_super_employee_invoke")
        return JSONResponse(
            format_mobile_response(None, "超级员工服务暂不可用", success=False, code=500),
            status_code=500,
        )


# ── 超级员工 LAN SSE 流式直答 ──


def _super_employee_service_for_tool(tool: str):
    """根据工具名返回对应的 SuperEmployeeService 实例。"""
    tool_lower = (tool or "").strip().lower()
    if tool_lower == "codex":
        return _parent().CodexSuperEmployeeService()
    if tool_lower == "claude":
        return _parent().ClaudeSuperEmployeeService()
    if tool_lower == "cursor":
        return _parent().CursorSuperEmployeeService()
    if tool_lower == "trae":
        return _parent().TraeSuperEmployeeService()
    return None


async def _stream_super_employee_invoke(
    request: Request,
    tool: str,
    body: dict[str, Any],
    user,
):
    """超级员工 SSE 流式直答的共享实现。"""
    _, err = _parent()._require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = _parent()._mobile_request_user_id(request, user)
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
    if (
        str((_parent()._mobile_session_meta(request) or {}).get("account_kind") or "")
        .strip()
        .lower()
        == "admin"
    ):
        _wsid = str((body or {}).get("workspace_id") or context.get("workspace_id") or "xcmax")
        context = _parent().factory_context(workspace_id=_wsid, base=context)

    async def sse_gen():
        try:
            async for event in service.invoke_stream(
                user_id=uid,
                message=text,
                context=context,
            ):
                yield _parent()._sse_line(event)
        except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
            logger.exception("mobile_super_employee_stream failed: %s", exc)
            yield _parent()._sse_line({"type": "error", "message": "流式调用失败，请稍后重试"})

    return StreamingResponse(
        sse_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/admin/codex-super-employee/messages/stream")
async def mobile_admin_codex_super_employee_stream(
    request: Request,
    body: dict[str, Any],
    user=Depends(get_mobile_user),
):
    """移动端 Codex 超级员工 LAN SSE 流式直答。"""
    return await _stream_super_employee_invoke(request, "codex", body, user)


@router.post("/admin/claude-super-employee/messages/stream")
async def mobile_admin_claude_super_employee_stream(
    request: Request,
    body: dict[str, Any],
    user=Depends(get_mobile_user),
):
    """移动端 Claude 超级员工 LAN SSE 流式直答。"""
    return await _stream_super_employee_invoke(request, "claude", body, user)


@router.post("/admin/cursor-super-employee/messages/stream")
async def mobile_admin_cursor_super_employee_stream(
    request: Request,
    body: dict[str, Any],
    user=Depends(get_mobile_user),
):
    """移动端 Cursor 超级员工 LAN SSE 流式直答。"""
    return await _stream_super_employee_invoke(request, "cursor", body, user)


@router.post("/admin/trae-super-employee/messages/stream")
async def mobile_admin_trae_super_employee_stream(
    request: Request,
    body: dict[str, Any],
    user=Depends(get_mobile_user),
):
    """移动端 Trae 超级员工 LAN SSE 流式直答。"""
    return await _stream_super_employee_invoke(request, "trae", body, user)
