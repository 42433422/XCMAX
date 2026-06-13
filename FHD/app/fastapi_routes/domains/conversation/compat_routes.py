"""
XCAGI 前端兼容 API — AI 聊天路由（统一对话 / 流式 / 批量）。
宿主保留 /api/ai/*；3d 门面见 /api/mod/xcagi-planner-bridge/chat*。
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import StreamingResponse

from app.application.planner_compat_service import (
    compat_chat_stream_async,
    execute_compat_chat,
    execute_compat_chat_batch,
)
from app.domain.ai.tier import assert_p2_elevated_claim_or_raise, resolve_ai_tier
from app.fastapi_routes.domains.conversation.helpers import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
)
from app.utils.metrics import chat_stream_first_byte_seconds

router = APIRouter(tags=["xcagi-compat"])
logger = logging.getLogger(__name__)


async def _chat_stream_with_first_byte_metric(
    request: Request, body: XcagiCompatChatBody, *, ai_tier: str
):
    from app.middleware.chat_stream_limit import release_chat_stream_slot

    start = time.perf_counter()
    first_byte = True
    try:
        async for chunk in compat_chat_stream_async(request, body, ai_tier=ai_tier):
            if first_byte:
                chat_stream_first_byte_seconds.labels(model="compat", tenant_id="default").observe(
                    time.perf_counter() - start
                )
                first_byte = False
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
        _chat_stream_with_first_byte_metric(request, body, ai_tier=tier),
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
