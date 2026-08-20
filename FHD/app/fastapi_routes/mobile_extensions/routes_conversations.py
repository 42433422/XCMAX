"""Conversation state mobile routes (strangler extract)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_api import get_mobile_user
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router: APIRouter = APIRouter()

# ── 会话状态管理（非群聊的个人 AI 会话） ──


def _conversation_state_uid(user: Any) -> int:
    uid = int(getattr(user, "id", 0) or 0)
    return uid if uid > 0 else 0


@router.put("/conversations/{conversation_id}/pin")
async def mobile_conversation_toggle_pin(conversation_id: str, user=Depends(get_mobile_user)):
    uid = _conversation_state_uid(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.application.conversation_state_service import ConversationStateService

        return format_mobile_response(
            data=ConversationStateService().toggle_pinned(
                user_id=uid, conversation_id=conversation_id
            )
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_conversation_toggle_pin")
        return JSONResponse(
            format_mobile_response(None, "会话操作失败", success=False, code=500), status_code=500
        )


@router.post("/conversations/{conversation_id}/mark-unread")
async def mobile_conversation_mark_unread(conversation_id: str, user=Depends(get_mobile_user)):
    uid = _conversation_state_uid(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.application.conversation_state_service import ConversationStateService

        return format_mobile_response(
            data=ConversationStateService().mark_unread(
                user_id=uid, conversation_id=conversation_id
            )
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_conversation_mark_unread")
        return JSONResponse(
            format_mobile_response(None, "会话操作失败", success=False, code=500), status_code=500
        )


@router.post("/conversations/{conversation_id}/mark-read")
async def mobile_conversation_mark_read(conversation_id: str, user=Depends(get_mobile_user)):
    uid = _conversation_state_uid(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.application.conversation_state_service import ConversationStateService

        return format_mobile_response(
            data=ConversationStateService().mark_read(user_id=uid, conversation_id=conversation_id)
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_conversation_mark_read")
        return JSONResponse(
            format_mobile_response(None, "会话操作失败", success=False, code=500), status_code=500
        )


@router.put("/conversations/{conversation_id}/followed")
async def mobile_conversation_toggle_followed(conversation_id: str, user=Depends(get_mobile_user)):
    uid = _conversation_state_uid(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.application.conversation_state_service import ConversationStateService

        return format_mobile_response(
            data=ConversationStateService().toggle_followed(
                user_id=uid, conversation_id=conversation_id
            )
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_conversation_toggle_followed")
        return JSONResponse(
            format_mobile_response(None, "会话操作失败", success=False, code=500), status_code=500
        )


@router.put("/conversations/{conversation_id}/hidden")
async def mobile_conversation_toggle_hidden(conversation_id: str, user=Depends(get_mobile_user)):
    uid = _conversation_state_uid(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.application.conversation_state_service import ConversationStateService

        return format_mobile_response(
            data=ConversationStateService().toggle_hidden(
                user_id=uid, conversation_id=conversation_id
            )
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_conversation_toggle_hidden")
        return JSONResponse(
            format_mobile_response(None, "会话操作失败", success=False, code=500), status_code=500
        )


@router.delete("/conversations/{conversation_id}")
async def mobile_conversation_delete(conversation_id: str, user=Depends(get_mobile_user)):
    uid = _conversation_state_uid(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.application.conversation_state_service import ConversationStateService

        return format_mobile_response(
            data=ConversationStateService().delete(user_id=uid, conversation_id=conversation_id)
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_conversation_delete")
        return JSONResponse(
            format_mobile_response(None, "会话操作失败", success=False, code=500), status_code=500
        )
