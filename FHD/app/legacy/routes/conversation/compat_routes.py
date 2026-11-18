"""
XCAGI 前端兼容 API — AI 聊天路由（统一对话 / 流式 / 批量）。
宿主保留 /api/ai/*；3d 门面见 /api/mod/xcagi-planner-bridge/chat*。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import aclosing
from typing import Any

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


def _replay_error_line(code: str, message: str) -> bytes:
    payload = {"type": "error", "code": code, "message": message}
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode() + b"\n\n"


async def _follow_replay(
    turn_id: str,
    after: str | int = 0,
    *,
    owner: str,
    tenant: str,
    idle_timeout: float = 600.0,
):
    """从回放缓冲跟随一个 turn，直到它落终态；客户端断开只会停止本协程。"""
    cursor = after
    started = time.monotonic()
    deadline = started + idle_timeout
    idle_ticks = 0
    while True:
        try:
            rows = chat_stream_replay.events_after(turn_id, cursor, owner=owner, tenant=tenant)
            for row in rows:
                cursor = row.get("seq") or cursor
                yield _replay_line(row)
            if chat_stream_replay.finish_status(turn_id, owner=owner, tenant=tenant):
                for row in chat_stream_replay.events_after(
                    turn_id, cursor, owner=owner, tenant=tenant
                ):
                    cursor = row.get("seq") or cursor
                    yield _replay_line(row)
                return
            # 租约消失且无终态：生产端已失联，明确落中断事件而不是空等到超时。
            if (
                time.monotonic() - started > chat_stream_replay.LEASE_TTL_SECONDS + 5
                and not chat_stream_replay.lease_alive(turn_id, owner=owner, tenant=tenant)
            ):
                yield _replay_error_line("STREAM_INTERRUPTED", "对话流已中断，请重试。")
                return
        except chat_stream_replay.ReplayBackendUnavailable:
            yield _replay_error_line("REPLAY_UNAVAILABLE", "断线续传服务暂不可用，请稍后重试。")
            return
        if time.monotonic() > deadline:
            yield b": replay idle timeout\n\n"
            return
        idle_ticks += 1
        if idle_ticks % 150 == 0:
            yield b": ping\n\n"
        await asyncio.sleep(0.1)


async def _stream_live(request: Request, body: XcagiCompatChatBody, *, ai_tier: str):
    """匿名请求直连上游事件流：不写回放，也就没有可被他人读取的续传入口。"""
    from app.middleware.chat_stream_limit import release_chat_stream_slot

    try:
        async for chunk in compat_chat_stream_async(request, body, ai_tier=ai_tier):
            yield chunk
    finally:
        release_chat_stream_slot()


async def _renew_replay_lease(runner: Any, producer: asyncio.Task[Any]) -> None:
    """The producer owns this heartbeat and awaits it on every exit path."""
    try:
        while not producer.done():
            await asyncio.sleep(max(1.0, chat_stream_replay.LEASE_TTL_SECONDS / 3))
            if producer.done():
                break
            renewal = asyncio.create_task(asyncio.to_thread(runner.reacquire))
            try:
                renewed = await asyncio.shield(renewal)
            finally:
                # Cancellation must not leave a Redis call running past task teardown.
                if not renewal.done():
                    await renewal
            if not renewed:
                raise chat_stream_replay.ReplayBackendUnavailable("生产权租约已失效")
    except RECOVERABLE_ERRORS:
        producer.cancel()


async def _produce_replay(
    request: Request,
    body: XcagiCompatChatBody,
    *,
    ai_tier: str,
    turn_id: str,
    owner: str,
    tenant: str,
    runner: Any = None,
) -> None:
    """后台消费真实事件流并写入回放缓冲；与 HTTP 连接生命周期无关。"""
    from app.middleware.chat_stream_limit import release_chat_stream_slot
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    producer = asyncio.current_task()
    heartbeat = (
        asyncio.create_task(_renew_replay_lease(runner, producer))
        if runner is not None and producer is not None
        else None
    )
    status = "done"
    try:
        async with aclosing(compat_chat_stream_async(request, body, ai_tier=ai_tier)) as stream:
            async for chunk in stream:
                for payload in _sse_payloads(chunk):
                    chat_stream_replay.append(
                        turn_id, payload, owner=owner, tenant=tenant, runner=runner
                    )
    except chat_stream_replay.ReplayBackendUnavailable:
        # 回放后端不可用：停止生产，租约过期后跟随方会收到中断事件。
        status = "error"
        logger.warning("chat stream replay backend unavailable", exc_info=True)
    except asyncio.CancelledError:
        status = "aborted"
        raise
    except RECOVERABLE_ERRORS as exc:
        status = "error"
        message = str(exc).strip() or exc.__class__.__name__
        try:
            chat_stream_replay.append(
                turn_id,
                {"type": "error", "message": message},
                owner=owner,
                tenant=tenant,
                runner=runner,
            )
        except chat_stream_replay.ReplayBackendUnavailable:
            pass
        logger.warning("chat stream producer failed", exc_info=True)
    finally:
        try:
            if heartbeat is not None:
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass
        finally:
            try:
                chat_stream_replay.mark_finished(
                    turn_id, status, owner=owner, tenant=tenant, runner=runner
                )
            except chat_stream_replay.ReplayBackendUnavailable:
                logger.warning("chat stream terminal state rejected after lease loss")
            finally:
                release_chat_stream_slot()


def _replay_unavailable_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "success": False,
            "code": "REPLAY_UNAVAILABLE",
            "message": "断线续传服务暂不可用，请稍后重试",
        },
    )


@router.post("/ai/unified_chat/stream")
@router.post("/ai/chat/stream")
async def ai_unified_chat_stream(request: Request, body: XcagiCompatChatBody):
    from app.middleware.chat_stream_limit import acquire_chat_stream_slot

    body = _prepare_compat_chat_body(request, body)
    context = body.context or {}
    turn_id = str(context.get("turn_id") or "")
    owner = str(context.get("local_user_id") or context.get("user_id") or "")
    tenant = str(context.get("tenant_id") or "")
    assert_p2_elevated_claim_or_raise(request)
    tier = resolve_ai_tier(request)

    # 匿名请求没有可校验归属：不写回放、不开续传，直接一次性流式返回。
    if not owner:
        if not acquire_chat_stream_slot():
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "code": "CHAT_STREAM_LIMIT",
                    "message": "流式对话并发已满，请稍后重试",
                },
            )
        return _sse_response(_stream_live(request, body, ai_tier=tier))

    try:
        claimed = chat_stream_replay.claim_runner(turn_id, owner=owner, tenant=tenant)
    except chat_stream_replay.ReplayBackendUnavailable:
        return _replay_unavailable_response()
    # 同一 turn 仍在生产：本次连接只跟随，不重复执行（断线重连）。
    if not claimed:
        return _sse_response(_follow_replay(turn_id, owner=owner, tenant=tenant))
    # 抢占已原子清除旧回放；此处不得再次清除新生产周期的数据。
    runner = chat_stream_replay.runner_for(turn_id, owner=owner, tenant=tenant)

    if not acquire_chat_stream_slot():
        chat_stream_replay.release_runner(turn_id, owner=owner, tenant=tenant, runner=runner)
        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "code": "CHAT_STREAM_LIMIT",
                "message": "流式对话并发已满，请稍后重试",
            },
        )
    asyncio.create_task(
        _produce_replay(
            request,
            body,
            ai_tier=tier,
            turn_id=turn_id,
            owner=owner,
            tenant=tenant,
            runner=runner,
        )
    )
    return _sse_response(_follow_replay(turn_id, owner=owner, tenant=tenant))


@router.get("/ai/chat/stream/resume")
async def ai_chat_stream_resume(
    request: Request,
    turn_id: str = Query(..., min_length=1),
    after: str = Query("0"),
):
    """断线后按 ``turn_id`` + 游标继续读取；仅限已登录且流属于当前主体。"""
    from app.infrastructure.auth.agent_principal import require_agent_principal

    principal = require_agent_principal(request, x_user_id=None)
    owner = str(principal.user_id)
    tenant = str(principal.tenant_id or "")
    try:
        has_replay = chat_stream_replay.has_replay(turn_id, owner=owner, tenant=tenant)
        status = chat_stream_replay.finish_status(turn_id, owner=owner, tenant=tenant)
    except chat_stream_replay.ReplayBackendUnavailable:
        raise HTTPException(status_code=503, detail="断线续传服务暂不可用，请稍后重试。") from None
    if not has_replay and not status:
        raise HTTPException(status_code=404, detail="没有可续传的流")
    return _sse_response(_follow_replay(turn_id, after, owner=owner, tenant=tenant))


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
