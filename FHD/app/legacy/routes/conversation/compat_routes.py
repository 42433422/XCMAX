"""
XCAGI 前端兼容 API — AI 聊天路由（统一对话 / 流式 / 批量）。
宿主保留 /api/ai/*；3d 门面见 /api/mod/xcagi-planner-bridge/chat*。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.application import chat_stream_replay
from app.application.planner_compat_service import (
    _prepare_compat_chat_body,
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
            raise HTTPException(status_code=400, detail=detail, headers=headers) from None
        if status in {502, 503, 504}:
            # 状态接口是“报告状态”，不是“探测上游”。市场超时/5xx 时返回
            # degraded 快照，避免前端把“上游暂时不可达”误判为本地接口故障。
            return JSONResponse(
                {
                    "ok": True,
                    "degraded": True,
                    "provider": "",
                    "model": "",
                    "route_source": "unavailable",
                    "key_source": "unavailable",
                    "reason": detail,
                },
                headers=headers,
            )
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


def _sse_response(events) -> StreamingResponse:
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse_payloads(chunk: bytes) -> list[dict]:
    """从后端产出的 SSE 字节块中取出 data 事件（其它内容不进回放缓冲）。"""
    if not isinstance(chunk, (bytes, bytearray)) or not bytes(chunk).startswith(b"data"):
        return []
    payloads: list[dict] = []
    for event in bytes(chunk).split(b"\n\n"):
        for line in event.splitlines():
            if not line.startswith(b"data: "):
                continue
            try:
                item = json.loads(line[6:])
            except (ValueError, UnicodeError):
                continue
            if isinstance(item, dict):
                payloads.append(item)
    return payloads


def _replay_line(row: dict) -> bytes:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    seq = str(row.get("seq") or 0).encode()
    return b"id: " + seq + b"\ndata: " + json.dumps(payload, ensure_ascii=False).encode() + b"\n\n"


async def _follow_replay(turn_id: str, after: int = 0, *, idle_timeout: float = 600.0):
    """从回放缓冲跟随一个 turn，直到它落终态；客户端断开只会停止本协程。"""
    cursor = max(0, int(after))
    deadline = time.monotonic() + idle_timeout
    idle_ticks = 0
    while True:
        rows = chat_stream_replay.events_after(turn_id, cursor)
        for row in rows:
            cursor = max(cursor, int(row.get("seq") or 0))
            yield _replay_line(row)
        if chat_stream_replay.finish_status(turn_id):
            for row in chat_stream_replay.events_after(turn_id, cursor):
                yield _replay_line(row)
            return
        if time.monotonic() > deadline:
            yield b": replay idle timeout\n\n"
            return
        idle_ticks += 1
        if idle_ticks % 150 == 0:
            yield b": ping\n\n"
        await asyncio.sleep(0.1)


async def _produce_replay(
    request: Request, body: XcagiCompatChatBody, *, ai_tier: str, turn_id: str
) -> None:
    """后台消费真实事件流并写入回放缓冲；与 HTTP 连接生命周期无关。"""
    from app.middleware.chat_stream_limit import release_chat_stream_slot
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    status = "done"
    try:
        async for chunk in compat_chat_stream_async(request, body, ai_tier=ai_tier):
            for payload in _sse_payloads(chunk):
                chat_stream_replay.append(turn_id, payload)
    except asyncio.CancelledError:
        status = "aborted"
        raise
    except RECOVERABLE_ERRORS as exc:
        status = "error"
        message = str(exc).strip() or exc.__class__.__name__
        chat_stream_replay.append(turn_id, {"type": "error", "message": message})
        logger.warning("chat stream producer failed", exc_info=True)
    finally:
        chat_stream_replay.mark_finished(turn_id, status)
        release_chat_stream_slot()


@router.post("/ai/unified_chat/stream")
@router.post("/ai/chat/stream")
async def ai_unified_chat_stream(request: Request, body: XcagiCompatChatBody):
    from app.middleware.chat_stream_limit import acquire_chat_stream_slot

    body = _prepare_compat_chat_body(request, body)
    turn_id = str((body.context or {}).get("turn_id") or "")
    assert_p2_elevated_claim_or_raise(request)
    tier = resolve_ai_tier(request)

    # 同一 turn 仍在生产：本次连接只跟随，不重复执行（断线重连）。
    if not chat_stream_replay.claim_runner(turn_id):
        return _sse_response(_follow_replay(turn_id))
    # 已结束的 turn 再次 POST 视为重试：清掉旧回放，重新执行。
    chat_stream_replay.clear(turn_id)
    chat_stream_replay.claim_runner(turn_id)

    if not acquire_chat_stream_slot():
        chat_stream_replay.release_runner(turn_id)
        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "code": "CHAT_STREAM_LIMIT",
                "message": "流式对话并发已满，请稍后重试",
            },
        )
    asyncio.create_task(_produce_replay(request, body, ai_tier=tier, turn_id=turn_id))
    return _sse_response(_follow_replay(turn_id))


@router.get("/ai/chat/stream/resume")
async def ai_chat_stream_resume(
    turn_id: str = Query(..., min_length=1),
    after: int = Query(0, ge=0),
):
    """断线后按 ``turn_id`` + 最后事件序号继续读取；已结束则直接回放终态。"""
    if not chat_stream_replay.has_replay(turn_id) and not chat_stream_replay.finish_status(turn_id):
        raise HTTPException(status_code=404, detail="没有可续传的流")
    return _sse_response(_follow_replay(turn_id, after))


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
