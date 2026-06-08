"""统一语音 WebSocket：单连接 PCM → FunASR → LLM 流式 → edge-TTS 分片。

路径 ``/api/workbench/voice/unified/ws``。客户端发送二进制 PCM 与 JSON 控制消息；
服务端推送 ``asr_partial`` / ``asr_final`` / ``text_delta`` / ``audio_chunk`` 等。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from modstore_server.asr_proxy_ws import (
    FUNASR_USE_SSL,
    _connect_funasr_parallel,
    _detect_funasr_host,
)
from modstore_server.models import User, get_session_factory
from modstore_server.voice_s2s_ws import _run_billed_s2s_turn, _send_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workbench/voice", tags=["workbench-voice"])


def _extract_funasr_text(msg: dict[str, Any]) -> str:
    direct = str(msg.get("text") or "").strip()
    if direct:
        return direct
    sents = msg.get("stamp_sents")
    if isinstance(sents, list) and sents:
        return "".join(
            str(s.get("text_seg") or "").replace(" ", "") for s in sents if isinstance(s, dict)
        ).strip()
    return ""


def _funasr_mode(msg: dict[str, Any]) -> str:
    return str(msg.get("mode") or "")


@router.websocket("/unified/ws")
async def voice_unified_ws(
    ws: WebSocket,
    token: str = Query(""),
) -> None:
    await ws.accept()
    if not token:
        await _send_json(ws, {"type": "error", "message": "请先登录"})
        await ws.close()
        return

    try:
        from modstore_server.auth_service import decode_access_token

        payload = decode_access_token(token)
        sub = payload.get("sub") if payload else None
        if not sub:
            await _send_json(ws, {"type": "error", "message": "认证无效"})
            await ws.close()
            return
        user_id = int(sub)
    except Exception:
        await _send_json(ws, {"type": "error", "message": "认证失败"})
        await ws.close()
        return

    await _send_json(ws, {"type": "ready"})
    auth_header = f"Bearer {token}"

    import ssl as _ssl

    funasr_urls = _detect_funasr_host()
    ssl_ctx = None
    if FUNASR_USE_SSL:
        ssl_ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = _ssl.CERT_NONE

    connect_result = await _connect_funasr_parallel(funasr_urls, ssl_ctx)
    if connect_result is None:
        await _send_json(ws, {"type": "error", "message": "FunASR 服务未启动"})
        await ws.close()
        return

    _funasr_url, funasr_ws = connect_result
    logger.info("unified voice: FunASR via %s", _funasr_url)

    cancel = asyncio.Event()
    turn_lock = asyncio.Lock()
    session_sent = False
    active_turn_id = ""
    pending_finalize: dict[str, str] = {}

    async def ensure_funasr_session() -> None:
        nonlocal session_sent
        if session_sent:
            return
        await funasr_ws.send(
            json.dumps(
                {
                    "mode": "2pass",
                    "chunk_size": [5, 10, 5],
                    "chunk_interval": 10,
                    "encoder_chunk_look_back": 4,
                    "decoder_chunk_look_back": 0,
                    "wav_name": "mic",
                    "wav_format": "pcm",
                    "audio_fs": 16000,
                    "is_speaking": True,
                    "hotwords": "流式对话 流失 修茈 工作台 豆包 MODstore",
                    "itn": True,
                }
            )
        )
        session_sent = True

    async def run_llm_turn(body: dict[str, Any], *, turn_id: str) -> None:
        nonlocal cancel, active_turn_id
        text = str(body.get("text") or "").strip()
        provider = str(body.get("provider") or "").strip()
        model = str(body.get("model") or "").strip()
        if not text or not provider or not model:
            await _send_json(ws, {"type": "error", "message": "utterance 缺少 text/provider/model"})
            return
        system = str(body.get("system") or "").strip()
        history = body.get("messages") if isinstance(body.get("messages"), list) else []
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        for item in history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": text})
        try:
            max_tokens_i = int(body.get("max_tokens") or 1024)
        except (TypeError, ValueError):
            max_tokens_i = 1024
        voice = str(body.get("voice") or "zh-CN-XiaoxiaoNeural")
        try:
            rate = float(body.get("rate") or 1.0)
        except (TypeError, ValueError):
            rate = 1.0
        tts_enabled = body.get("tts_enabled", True) is not False

        async with turn_lock:
            if turn_id and turn_id != active_turn_id:
                cancel.set()
                cancel = asyncio.Event()
                active_turn_id = turn_id
            elif not turn_id:
                cancel.set()
                cancel = asyncio.Event()
            db = get_session_factory()()
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    await _send_json(ws, {"type": "error", "message": "用户不存在"})
                    return
                await _run_billed_s2s_turn(
                    ws,
                    user=user,
                    db=db,
                    auth_header=auth_header,
                    provider=provider,
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens_i,
                    voice=voice,
                    rate=rate,
                    tts_enabled=tts_enabled,
                    cancel=cancel,
                )
            finally:
                db.close()

    async def client_to_funasr() -> None:
        nonlocal cancel
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if "bytes" in msg and msg["bytes"]:
                    await ensure_funasr_session()
                    await funasr_ws.send(msg["bytes"])
                elif "text" in msg and msg["text"]:
                    try:
                        body = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        continue
                    mtype = str(body.get("type") or "")
                    if mtype == "ping":
                        await _send_json(ws, {"type": "pong"})
                        continue
                    if mtype == "cancel":
                        cancel.set()
                        await _send_json(ws, {"type": "cancelled"})
                        continue
                    if mtype == "speech_end":
                        await ensure_funasr_session()
                        try:
                            await funasr_ws.send(json.dumps({"is_speaking": False}))
                        except Exception:
                            pass
                        continue
                    if mtype == "utterance_finalize":
                        tid = str(body.get("turn_id") or active_turn_id).strip()
                        final_text = str(body.get("text") or "").strip()
                        if not tid or not final_text:
                            continue
                        pending = pending_finalize.get(tid, "")
                        pending_finalize[tid] = final_text
                        if pending and pending != final_text and len(final_text) - len(pending) > 3:
                            retry_body = {**body, "type": "end_utterance", "text": final_text}
                            await run_llm_turn(retry_body, turn_id=tid)
                        continue

                    if mtype in ("end_utterance", "utterance", "utterance_start"):
                        turn_id = (
                            str(body.get("turn_id") or "").strip() or f"t{int(time.time() * 1000)}"
                        )
                        if mtype == "utterance_start":
                            pending_finalize[turn_id] = str(body.get("text") or "").strip()
                        await run_llm_turn(body, turn_id=turn_id)
                        continue
                    if isinstance(body, dict) and "is_speaking" in body:
                        await ensure_funasr_session()
                        await funasr_ws.send(json.dumps(body))
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.info("unified client_to_funasr: %s", exc)

    async def funasr_to_client() -> None:
        try:
            async for raw in funasr_ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
                except Exception:
                    continue
                text = _extract_funasr_text(msg)
                mode = _funasr_mode(msg)
                is_offline = "offline" in mode or "2pass-offline" in mode
                is_online = "online" in mode or "2pass-online" in mode
                if not text:
                    continue
                if is_offline:
                    await _send_json(
                        ws,
                        {"type": "asr_final", "text": text, "segment_mode": "offline"},
                    )
                elif is_online:
                    await _send_json(
                        ws,
                        {"type": "asr_partial", "text": text, "segment_mode": "online"},
                    )
                else:
                    await _send_json(ws, {"type": "asr_partial", "text": text})
        except Exception as exc:
            logger.info("unified funasr_to_client: %s", exc)

    try:
        await _send_json(ws, {"type": "connected", "health": True})
        t1 = asyncio.create_task(client_to_funasr())
        t2 = asyncio.create_task(funasr_to_client())
        await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
        for t in (t1, t2):
            if not t.done():
                t.cancel()
    except WebSocketDisconnect:
        cancel.set()
    finally:
        try:
            await funasr_ws.close()
        except Exception:
            pass
