"""Migrated from legacy_conversation.py (v10)."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from app.fastapi_routes.domains.misc.helpers import (
    _message_to_dict,
    _session_to_dict,
)
from app.utils.json_safe import json_safe
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-conversation"], deprecated=True)


async def _authenticated_conversation_user(request: Request):
    """Bind legacy conversation reads/writes to a verified current user."""
    from app.fastapi_routes.mobile_api import get_mobile_user

    authorization = str(request.headers.get("Authorization") or "").strip() or None
    user = await get_mobile_user(request, authorization=authorization)
    try:
        user_id = int(getattr(user, "id", 0) or 0)
    except (TypeError, ValueError, AttributeError):
        user_id = 0
    if user is None or user_id <= 0 or not bool(getattr(user, "is_active", True)):
        raise HTTPException(status_code=401, detail="conversation authentication required")
    return user


def _require_owned_session(service, session_id: str, user) -> int:
    try:
        user_id = int(getattr(user, "id", 0) or 0)
    except (TypeError, ValueError, AttributeError):
        user_id = 0
    exists, owner_id = service.get_session_ownership(session_id)
    if not exists or user_id <= 0 or owner_id != user_id:
        # Do not reveal whether another user's session exists.
        raise HTTPException(status_code=404, detail="conversation not found")
    return user_id


def _trace_ai_message_save(payload: dict, *, body: dict) -> dict:
    if not isinstance(payload, dict) or payload.get("run_id") or payload.get("agent_run_id"):
        return payload
    try:
        from app.application.agent_orchestrator.chat_trace import create_chat_trace_run

        safe_body = {
            "session_id": str(body.get("session_id") or ""),
            "user_id": str(body.get("user_id") or "default"),
            "role": str(body.get("role") or ""),
            "intent": str(body.get("intent") or ""),
            "content_preview": str(body.get("content") or "")[:500],
        }
        message = str(body.get("content") or "message saved")
        run = create_chat_trace_run(
            {
                "success": bool(payload.get("success", False)),
                "response": str(payload.get("message") or "message saved"),
                "data": {"text": "message saved", "route_result": dict(payload)},
            },
            message=message,
            runtime_context={
                "route": "/api/ai/message/save",
                "source": "legacy_conversation",
                "action": "message_save",
                "request": safe_body,
            },
            user_id=safe_body["user_id"],
            source="legacy_conversation",
            channel="ai_message_save",
            intent="conversation_message_save",
        )
        traced = dict(payload)
        traced["run_id"] = run.run_id
        traced["agent_run_id"] = run.run_id
        return traced
    except Exception:  # noqa: BLE001 - tracing must not break legacy message persistence
        logger.exception("failed to attach AgentRun trace to /api/ai/message/save")
        return payload


@router.get("/api/conversations/{session_id}")
def conversations_get(
    session_id: str,
    limit: int = Query(default=50),
    user=Depends(_authenticated_conversation_user),
):
    try:
        from app.application.facades.conversation_facade import get_conversation_service

        service = get_conversation_service()
        _require_owned_session(service, session_id, user)
        messages = service.get_session_messages(session_id, limit)
        sessions = service.get_sessions(user_id=str(user.id), limit=1000)
        session_info = None
        for s in sessions:
            current = _session_to_dict(s)
            if current.get("session_id") == session_id:
                session_info = current
                break
        result = [_message_to_dict(m) for m in messages]
        return json_safe({"success": True, "session": session_info, "messages": result})
    except RECOVERABLE_ERRORS as e:
        logger.error("conversations get: %s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.delete("/api/conversations/{session_id}")
def conversations_delete(session_id: str, user=Depends(_authenticated_conversation_user)):
    try:
        from app.application.facades.conversation_facade import get_conversation_service

        service = get_conversation_service()
        _require_owned_session(service, session_id, user)
        success = service.delete_session(session_id)
        return {"success": success}
    except RECOVERABLE_ERRORS as e:
        logger.error("conversations delete: %s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.put("/api/conversations/{session_id}/title")
def conversations_title_put(
    session_id: str,
    body: dict = Body(default_factory=dict),
    user=Depends(_authenticated_conversation_user),
):
    from app.application.facades.conversation_facade import (
        get_conversation_service as get_conversation_app_service,
    )

    service = get_conversation_app_service()
    _require_owned_session(service, session_id, user)
    data = body or {}
    title = data.get("title", "")
    success = service.update_session_title(session_id, title)
    return {"success": success}


@router.get("/api/ai/analyze/export/{export_id}")
def ai_analyze_export(export_id: str):
    try:
        from app.application.facades.conversation_facade import get_data_analysis_service
        from app.utils.path_utils import get_upload_dir

        service = get_data_analysis_service()
        output_path = os.path.join(get_upload_dir(), f"report_{export_id}.xlsx")
        success = service.export_to_excel({}, output_path)
        if success and os.path.exists(output_path):
            return FileResponse(
                output_path,
                filename=f"分析报告_{export_id[:8]}.xlsx",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        return JSONResponse({"success": False, "message": "导出失败"}, status_code=500)
    except RECOVERABLE_ERRORS as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.post("/api/ai/message/save")
def ai_message_save(
    body: dict = Body(default_factory=dict),
    user=Depends(_authenticated_conversation_user),
):
    from app.application.facades.conversation_facade import (
        get_conversation_service as get_conversation_app_service,
    )

    service = get_conversation_app_service()
    if not body:
        return JSONResponse({"success": False, "message": "请求数据不能为空"}, status_code=400)
    session_id = body.get("session_id")
    user_raw = int(user.id)
    role = body.get("role")
    content = body.get("content")
    intent = body.get("intent", "")
    metadata = body.get("metadata", "")
    if not session_id:
        return JSONResponse({"success": False, "message": "会话 ID 不能为空"}, status_code=400)
    if not role:
        return JSONResponse({"success": False, "message": "角色不能为空"}, status_code=400)
    if role in ("ai", "bot"):
        role = "assistant"
    if role not in ("user", "assistant", "system"):
        return JSONResponse({"success": False, "message": f"无效的角色：{role}"}, status_code=400)
    if not content:
        return JSONResponse({"success": False, "message": "消息内容不能为空"}, status_code=400)

    exists, owner_id = service.get_session_ownership(str(session_id))
    if exists and owner_id != int(user.id):
        raise HTTPException(status_code=404, detail="conversation not found")
    user_id_str = str(user_raw)
    trusted_body = dict(body)
    trusted_body["user_id"] = user_id_str
    try:
        message_id = service.save_message(session_id, user_id_str, role, content, intent, metadata)
        return _trace_ai_message_save(
            {"success": True, "message_id": message_id}, body=trusted_body
        )
    except RECOVERABLE_ERRORS as e:
        traced = _trace_ai_message_save({"success": False, "message": str(e)}, body=trusted_body)
        return JSONResponse(traced, status_code=500)
