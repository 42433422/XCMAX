"""
XCAGI 前端兼容 API — AI 聊天路由（统一对话 / 流式 / 批量）。
宿主保留 /api/ai/*；3d 门面见 /api/mod/xcagi-planner-bridge/chat*。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.application.planner_compat_service import (
    compat_chat_stream_async,
    execute_compat_chat,
    execute_compat_chat_batch,
)
from app.domain.ai.tier import assert_p2_elevated_claim_or_raise, resolve_ai_tier
from app.fastapi_routes.xcagi_compat_chat_helpers import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
)
from app.infrastructure.auth.dependencies import get_logged_in_user
from app.utils.operational_errors import RECOVERABLE_ERRORS

router = APIRouter(tags=["xcagi-compat"])
logger = logging.getLogger(__name__)


@router.get("/conversation/model-status", deprecated=False)
def conversation_model_status(request: Request, _user=Depends(get_logged_in_user)):
    """Read only this local session's server-resolved route; never run a model probe."""
    import httpx

    from app.application.modstore_conversation_app import create_modstore_openai_client_from_request
    from app.infrastructure.modstore_transport import MarketModelError

    headers = {"Cache-Control": "no-store"}
    client = create_modstore_openai_client_from_request(request)
    if not client.adapter.auth_token:
        raise HTTPException(
            status_code=401,
            detail="当前会话未绑定模型服务授权，请重新登录市场账号或联系管理员。",
            headers=headers,
        )
    try:
        metadata = client.adapter.resolve_default_route_metadata()
    except RECOVERABLE_ERRORS as exc:
        status = (
            exc.status_code
            if isinstance(exc, MarketModelError)
            else 504
            if isinstance(exc, httpx.TimeoutException)
            else 503
            if isinstance(exc, httpx.ConnectError)
            else 502
        )
        detail: str | dict[str, str] = str(MarketModelError({"status": status}))
        if getattr(exc, "code", None) in {"INVALID_CHAT_PREFERENCE", "NO_BYOK_CHAT_MODEL"}:
            detail = {
                "code": str(getattr(exc, "code", "INVALID_CHAT_PREFERENCE")),
                "message": "已保存的模型不支持聊天，请选择聊天模型或恢复跟随平台。",
                "recovery": "choose_chat_model_or_follow_platform",
            }
        raise HTTPException(status_code=status, detail=detail, headers=headers) from None
    return JSONResponse({"ok": True, **metadata}, headers=headers)


@router.put("/conversation/model-preference", deprecated=False)
def conversation_follow_platform(
    request: Request, body: dict = Body(...), _user=Depends(get_logged_in_user)
):
    from app.application.modstore_conversation_app import create_modstore_openai_client_from_request
    from app.infrastructure.modstore_transport import MarketModelError

    if body != {"mode": "platform"}:
        raise HTTPException(status_code=400, detail="仅支持明确恢复跟随平台默认模型。")
    client = create_modstore_openai_client_from_request(request)
    if not client.adapter.auth_token:
        raise HTTPException(
            status_code=401, detail="当前会话未绑定模型服务授权，请重新登录市场账号。"
        )
    try:
        client.adapter.follow_platform_default()
    except RECOVERABLE_ERRORS as exc:
        status = exc.status_code if isinstance(exc, MarketModelError) else 502
        raise HTTPException(
            status_code=status, detail=str(MarketModelError({"status": status}))
        ) from None
    return {"ok": True}


async def _chat_stream_with_slot_release(
    request: Request, body: XcagiCompatChatBody, *, ai_tier: str
):
    from app.middleware.chat_stream_limit import release_chat_stream_slot

    try:
        async for chunk in compat_chat_stream_async(request, body, ai_tier=ai_tier):
            yield chunk
    finally:
        release_chat_stream_slot()


@router.post("/ai/unified_chat/stream")
@router.post("/ai/chat/stream")
async def ai_unified_chat_stream(request: Request, body: XcagiCompatChatBody):
    from app.middleware.chat_stream_limit import acquire_chat_stream_slot

    if not acquire_chat_stream_slot():
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "code": "CHAT_STREAM_LIMIT",
                "message": "流式对话并发已满，请稍后重试",
            },
        )
    assert_p2_elevated_claim_or_raise(request)
    tier = resolve_ai_tier(request)
    return StreamingResponse(
        _chat_stream_with_slot_release(request, body, ai_tier=tier),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/ai/chat")
@router.post("/ai/chat/v2")
@router.post("/ai/unified_chat")
@router.post("/chat/send")
@router.post("/planner/chat")
async def ai_chat_unified_compat(request: Request, body: XcagiCompatChatBody) -> dict:
    return await execute_compat_chat(request, body)


@router.post("/ai/chat/batch")
@router.post("/ai/chat/v2/batch")
@router.post("/ai/unified_chat/batch")
async def ai_chat_batch_compat(request: Request, body: XcagiCompatChatBatchBody) -> dict:
    return await execute_compat_chat_batch(request, body)


@router.get("/ai/context")
def ai_context_get(user_id: str = Query(default="default")) -> dict:
    _ = user_id
    return {"success": True, "data": {}}


@router.post("/ai/context/clear")
def ai_context_clear(body: dict = Body(default_factory=dict)) -> dict:
    _ = body
    return {"success": True}


@router.get("/ai/config")
def ai_config_get() -> dict:
    return {"success": True, "data": {}}


@router.post("/tts/synthesize")
def tts_synthesize_stub(body: dict = Body(default_factory=dict)) -> dict:
    _ = body.get("text") or body.get("message")
    return {"success": False, "message": "TTS 未在 FHD 兼容层启用", "data": {}}
