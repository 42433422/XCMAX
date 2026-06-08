"""语音 Speech-to-Speech WebSocket：单连接内 LLM 流式 + 分句 edge-TTS。

路径 ``/api/workbench/voice/s2s/ws``。客户端在 ASR 断句后发送 ``utterance``，
服务端推送 ``text_delta`` / ``audio_sentence``，降低多跳延迟。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from modstore_server.llm_billing import (
    JavaWalletClient,
    WalletHold,
    authorization_header,
    calculate_charge,
    enforce_risk_limits,
    estimate_preauthorization,
    new_request_id,
    save_failure_log,
    save_success_log,
    usage_from_response,
)
from modstore_server.llm_chat_proxy import chat_dispatch_stream
from modstore_server.llm_key_resolver import (
    KNOWN_PROVIDERS,
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    resolve_api_key,
    resolve_base_url,
)
from modstore_server.models import User, get_session_factory
from modstore_server.voice_s2s_sentence import VoiceStreamSentenceSplitter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workbench/voice", tags=["workbench-voice"])

try:
    import edge_tts  # noqa: F401

    _EDGE_TTS = edge_tts
except ImportError:
    _EDGE_TTS = None


def _rate_str(rate: float) -> str:
    from modstore_server.edge_tts_service import rate_str_from_float

    return rate_str_from_float(rate)


async def _stream_sentence_tts_chunks(
    ws: WebSocket,
    *,
    text: str,
    voice: str,
    rate_str: str,
    sentence_id: str,
    cancel: asyncio.Event,
) -> None:
    from modstore_server.edge_tts_service import stream_audio

    seq = 0
    async for chunk in stream_audio(text, voice, rate_str):
        if cancel.is_set():
            return
        if not chunk:
            continue
        await _send_json(
            ws,
            {
                "type": "audio_chunk",
                "sentence_id": sentence_id,
                "seq": seq,
                "text": text if seq == 0 else "",
                "data_b64": base64.b64encode(chunk).decode("ascii"),
                "mime": "audio/mpeg",
            },
        )
        seq += 1
    if not cancel.is_set():
        await _send_json(
            ws,
            {"type": "audio_sentence_end", "sentence_id": sentence_id, "text": text},
        )


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def _run_billed_s2s_turn(
    ws: WebSocket,
    *,
    user: User,
    db: Session,
    auth_header: str,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int | None,
    voice: str,
    rate: float,
    tts_enabled: bool,
    cancel: asyncio.Event,
) -> None:
    if provider not in KNOWN_PROVIDERS:
        await _send_json(ws, {"type": "error", "message": "unknown provider"})
        return

    api_key, key_source = resolve_api_key(db, user.id, provider)
    if not api_key:
        await _send_json(ws, {"type": "error", "message": f"供应商「{provider}」未配置 API Key"})
        return

    is_byok = key_source == "user_override"
    base = (
        resolve_base_url(db, user.id, provider)
        if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    model = model.strip()
    request_id = new_request_id()

    try:
        enforce_risk_limits(db, user.id, provider, model, messages, None)
    except Exception as exc:
        await _send_json(ws, {"type": "error", "message": str(exc)})
        return

    wallet = JavaWalletClient()
    if is_byok:
        hold = WalletHold(hold_no=f"byok-{request_id}", amount=Decimal("0"), enabled=False)
    else:
        preauth_amount = estimate_preauthorization(db, provider, model, messages, max_tokens)
        hold = await wallet.preauthorize(auth_header, preauth_amount, provider, model, request_id)

    parts: list[str] = []
    upstream_usage: dict[str, Any] = {}
    # 按自然停顿分段，避免 9 字硬切导致 TTS 读起来像被打断。
    splitter = VoiceStreamSentenceSplitter(
        early_clause=True,
        early_clause_min_len=14,
        first_chunk_len=0,
    )
    audio_queue: asyncio.Queue[tuple[str, str] | None] = asyncio.Queue()
    rate_str = _rate_str(rate)
    tts_voice = (voice or "zh-CN-XiaoxiaoNeural").strip()
    sentence_seq = 0

    async def audio_worker() -> None:
        nonlocal sentence_seq
        while True:
            item = await audio_queue.get()
            if item is None:
                break
            sid, sentence = item
            if cancel.is_set():
                continue
            if not tts_enabled or _EDGE_TTS is None:
                continue
            try:
                await _stream_sentence_tts_chunks(
                    ws,
                    text=sentence,
                    voice=tts_voice,
                    rate_str=rate_str,
                    sentence_id=sid,
                    cancel=cancel,
                )
            except Exception as exc:
                logger.warning("S2S TTS failed: %s", exc)

    audio_task = asyncio.create_task(audio_worker())

    try:
        async for ev in chat_dispatch_stream(
            provider,
            api_key=api_key,
            base_url=base,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        ):
            if cancel.is_set():
                break
            if ev.get("type") == "error":
                err = str(ev.get("error") or "upstream error")
                save_failure_log(
                    db,
                    user_id=user.id,
                    provider=provider,
                    model=model,
                    error=err,
                    hold_no=hold.hold_no,
                )
                try:
                    await wallet.release(auth_header, hold, err, request_id)
                except Exception:
                    logger.exception("S2S release hold failed")
                await _send_json(ws, {"type": "error", "message": err})
                return
            if ev.get("type") == "usage":
                upstream_usage = ev.get("usage") or {}
                continue
            if ev.get("type") == "delta":
                delta = str(ev.get("delta") or "")
                if not delta:
                    continue
                parts.append(delta)
                so_far = "".join(parts)
                await _send_json(ws, {"type": "text_delta", "delta": delta, "so_far": so_far})
                for sentence in splitter.feed(so_far):
                    sentence_seq += 1
                    await audio_queue.put((f"s{sentence_seq}", sentence))

        if cancel.is_set():
            try:
                await wallet.release(auth_header, hold, "cancelled", request_id)
            except Exception:
                pass
            await _send_json(ws, {"type": "cancelled"})
            return

        content = "".join(parts).strip() or "（无回复）"
        for sentence in splitter.finish(content):
            sentence_seq += 1
            await audio_queue.put((f"s{sentence_seq}", sentence))

        usage = usage_from_response(upstream_usage, messages, content)
        if is_byok:
            charge = Decimal("0")
        else:
            charge = calculate_charge(db, provider, model, usage)
            await wallet.settle(auth_header, hold, charge, request_id)
        save_success_log(
            db,
            user_id=user.id,
            provider=provider,
            model=model,
            messages=messages,
            content=content,
            usage=usage,
            charge=charge,
            hold_no=hold.hold_no,
            conversation_id=None,
        )
        await _send_json(
            ws,
            {
                "type": "text_done",
                "content": content,
                "billed": not is_byok,
            },
        )
        await _send_json(ws, {"type": "turn_done"})
    except Exception as exc:
        logger.exception("S2S turn failed")
        try:
            await wallet.release(auth_header, hold, str(exc), request_id)
        except Exception:
            pass
        await _send_json(ws, {"type": "error", "message": str(exc)})
    finally:
        await audio_queue.put(None)
        try:
            await asyncio.wait_for(audio_task, timeout=120.0)
        except asyncio.TimeoutError:
            audio_task.cancel()


@router.websocket("/s2s/ws")
async def voice_s2s_ws(
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
    cancel = asyncio.Event()
    turn_lock = asyncio.Lock()
    active_turn_id = ""
    pending_finalize: dict[str, str] = {}

    async def run_utterance_turn(msg: dict[str, Any], *, turn_id: str) -> None:
        nonlocal cancel, active_turn_id
        text = str(msg.get("text") or "").strip()
        if not text:
            await _send_json(ws, {"type": "error", "message": "text 不能为空"})
            return
        provider = str(msg.get("provider") or "").strip()
        model = str(msg.get("model") or "").strip()
        if not provider or not model:
            await _send_json(ws, {"type": "error", "message": "provider/model 必填"})
            return

        system = str(msg.get("system") or "").strip()
        history = msg.get("messages") if isinstance(msg.get("messages"), list) else []
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

        max_tokens = msg.get("max_tokens")
        try:
            max_tokens_i = int(max_tokens) if max_tokens is not None else 1024
        except (TypeError, ValueError):
            max_tokens_i = 1024

        voice = str(msg.get("voice") or "zh-CN-XiaoxiaoNeural")
        try:
            rate = float(msg.get("rate") or 1.0)
        except (TypeError, ValueError):
            rate = 1.0
        tts_enabled = msg.get("tts_enabled", True) is not False

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

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_json(ws, {"type": "error", "message": "invalid json"})
                continue

            mtype = str(msg.get("type") or "").strip()
            if mtype == "ping":
                await _send_json(ws, {"type": "pong"})
                continue
            if mtype == "cancel":
                cancel.set()
                await _send_json(ws, {"type": "cancelled", "turn_id": active_turn_id})
                continue

            if mtype == "utterance_finalize":
                tid = str(msg.get("turn_id") or active_turn_id).strip()
                final_text = str(msg.get("text") or "").strip()
                if not tid or not final_text:
                    continue
                pending = pending_finalize.get(tid, "")
                pending_finalize[tid] = final_text
                if pending and pending != final_text and len(final_text) - len(pending) > 3:
                    cancel.set()
                    cancel = asyncio.Event()
                    await run_utterance_turn(
                        {**msg, "type": "utterance", "text": final_text}, turn_id=tid
                    )
                continue

            if mtype not in ("utterance", "utterance_start"):
                continue

            turn_id = str(msg.get("turn_id") or "").strip() or f"t{int(time.time() * 1000)}"
            if mtype == "utterance_start":
                pending_finalize[turn_id] = str(msg.get("text") or "").strip()

            text = str(msg.get("text") or "").strip()
            if not text:
                await _send_json(ws, {"type": "error", "message": "text 不能为空"})
                continue

            await run_utterance_turn(msg, turn_id=turn_id)
    except WebSocketDisconnect:
        cancel.set()
    except Exception as exc:
        logger.exception("voice S2S ws error")
        try:
            await _send_json(ws, {"type": "error", "message": str(exc)})
        except Exception:
            pass
