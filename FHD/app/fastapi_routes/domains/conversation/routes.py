"""Migrated from legacy_conversation.py (v10)."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-conversation"], deprecated=True)


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
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - tracing must not break legacy message persistence
        logger.exception("failed to attach AgentRun trace to /api/ai/message/save")
        return payload


def _history_actor(request: Request) -> str:
    from app.application.task_conversation_store import durable_user_id
    from app.infrastructure.auth.dependencies import resolve_session_user

    actor = durable_user_id(getattr(resolve_session_user(request), "id", None))
    if actor is None:
        raise HTTPException(status_code=401, detail="请先登录后再访问会话。")
    return str(actor)


@router.get("/api/conversations/{session_id}")
def conversations_get(request: Request, session_id: str, limit: int = Query(default=50)):
    from app.application.task_conversation_store import task_conversation_store
    from app.request_active_mod_ctx import get_request_active_mod_id

    return task_conversation_store.get_history(
        session_id=session_id.strip(),
        user_id=int(_history_actor(request)),
        mod_id=get_request_active_mod_id() or "",
    )


@router.delete("/api/conversations/{session_id}")
def conversations_delete(request: Request, session_id: str):
    owner = _history_actor(request)
    try:
        from app.application.facades.conversation_facade import get_conversation_service

        service = get_conversation_service()
        success = service.delete_session(session_id, user_id=owner)
        return {"success": success}
    except RECOVERABLE_ERRORS as e:
        logger.error("conversations delete: %s", e)
        return JSONResponse({"success": False, "message": "删除会话失败"}, status_code=500)


@router.put("/api/conversations/{session_id}/title")
def conversations_title_put(
    request: Request, session_id: str, body: dict = Body(default_factory=dict)
):
    from app.application.facades.conversation_facade import (
        get_conversation_service as get_conversation_app_service,
    )

    service = get_conversation_app_service()
    data = body or {}
    title = data.get("title", "")
    success = service.update_session_title(session_id, title, user_id=_history_actor(request))
    return {"success": success}


@router.get("/api/ai/analyze/export/{export_id}")
def ai_analyze_export(export_id: str):
    try:
        from app.application.facades.conversation_facade import get_data_analysis_service
        from app.utils.path_io.path_utils import get_upload_dir

        safe_export_id = "".join(
            char for char in str(export_id)[:64] if char.isalnum() or char in {"-", "_"}
        )
        if not safe_export_id or safe_export_id != export_id:
            return JSONResponse({"success": False, "message": "导出编号无效"}, status_code=400)
        service = get_data_analysis_service()
        upload_root = os.path.realpath(os.path.abspath(get_upload_dir()))
        output_path = os.path.realpath(
            os.path.abspath(os.path.join(upload_root, f"report_{safe_export_id}.xlsx"))
        )
        upload_prefix = upload_root.rstrip(os.sep) + os.sep
        if output_path != upload_root and not output_path.startswith(upload_prefix):
            return JSONResponse({"success": False, "message": "导出编号无效"}, status_code=400)
        success = service.export_to_excel({}, output_path)
        if success and os.path.exists(output_path):
            return FileResponse(
                output_path,
                filename=f"分析报告_{safe_export_id[:8]}.xlsx",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        return JSONResponse({"success": False, "message": "导出失败"}, status_code=500)
    except RECOVERABLE_ERRORS:
        logger.exception("analysis export failed")
        return JSONResponse({"success": False, "message": "导出失败"}, status_code=500)


@router.post("/api/ai/message/save")
def ai_message_save(request: Request, body: dict = Body(default_factory=dict)):
    from app.application.facades.conversation_facade import (
        get_conversation_service as get_conversation_app_service,
    )

    service = get_conversation_app_service()
    if not body:
        return JSONResponse({"success": False, "message": "请求数据不能为空"}, status_code=400)
    session_id = body.get("session_id")
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

    user_id_str = _history_actor(request)
    body = {**body, "user_id": user_id_str}
    try:
        message_id = service.save_message(session_id, user_id_str, role, content, intent, metadata)
        return _trace_ai_message_save({"success": True, "message_id": message_id}, body=body)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="无权写入该会话。") from exc
    except RECOVERABLE_ERRORS:
        logger.exception("conversation message save failed")
        traced = _trace_ai_message_save({"success": False, "message": "消息保存失败"}, body=body)
        return JSONResponse(traced, status_code=500)
