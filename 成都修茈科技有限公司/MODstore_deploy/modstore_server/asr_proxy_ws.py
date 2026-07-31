"""ASR WebSocket 代理：前端 → 本服务 → FunASR 或小米 MiMo ASR。

路径 ``/api/asr/funasr`` 保持不变（前端 FunASRBackend 仍连此路径）。

环境变量：
- ``MODSTORE_ASR_BACKEND``: ``mimo`` | ``funasr`` | ``auto``（默认 ``auto``）
  - ``mimo``：始终走小米 ``mimo-v2.5-asr``
  - ``funasr``：始终走本地 FunASR
  - ``auto``：优先 FunASR，不可达且已配 MiMo 密钥时回退云端 ASR
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/asr", tags=["asr"])

FUNASR_HOST = os.getenv("FUNASR_HOST", "")
FUNASR_PORT = int(os.getenv("FUNASR_PORT", "10095"))
FUNASR_USE_SSL = os.getenv("FUNASR_USE_SSL", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)


def _asr_backend_pref() -> str:
    raw = (os.getenv("MODSTORE_ASR_BACKEND") or "auto").strip().lower()
    if raw in {"mimo", "xiaomi", "cloud"}:
        return "mimo"
    if raw in {"funasr", "local"}:
        return "funasr"
    return "auto"


def _funasr_scheme() -> str:
    return "wss" if FUNASR_USE_SSL else "ws"


def _detect_funasr_host() -> list[str]:
    """Detect reachable FunASR host addresses from inside/outside Docker."""
    scheme = _funasr_scheme()
    host = FUNASR_HOST
    if host:
        return [f"{scheme}://{host}:{FUNASR_PORT}"]

    candidates = []
    try:
        socket.gethostbyname("host.docker.internal")
        candidates.append("host.docker.internal")
    except Exception:
        pass
    candidates.extend(["172.17.0.1", "127.0.0.1"])
    return [f"{scheme}://{h}:{FUNASR_PORT}" for h in candidates]


async def _try_connect_funasr(
    funasr_url: str,
    ssl_ctx,
    timeout: float = 2.5,
):
    import websockets

    connect_kw: dict = {"open_timeout": timeout, "close_timeout": 2}
    if ssl_ctx is not None:
        connect_kw["ssl"] = ssl_ctx
    try:
        return funasr_url, await asyncio.wait_for(
            websockets.connect(funasr_url, **connect_kw),
            timeout=timeout + 0.5,
        )
    except Exception as e:
        logger.info("FunASR connect failed to %s: %s", funasr_url, e)
        return None


async def _connect_funasr_parallel(funasr_urls: list[str], ssl_ctx):
    if not funasr_urls:
        return None
    if len(funasr_urls) == 1:
        return await _try_connect_funasr(funasr_urls[0], ssl_ctx)

    tasks = [asyncio.create_task(_try_connect_funasr(url, ssl_ctx)) for url in funasr_urls]
    try:
        while tasks:
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in done:
                result = t.result()
                if result is not None:
                    for p in pending:
                        p.cancel()
                    return result
            tasks = list(pending)
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
    return None


async def _proxy_to_mimo(client_ws: WebSocket) -> None:
    """缓冲前端 PCM，在停说时调用 MiMo ASR，并以 FunASR 兼容 JSON 回传。"""
    from modstore_server.mimo_asr_service import (
        is_configured,
        pcm16le_to_wav_bytes,
        transcribe_mimo_asr_async,
    )

    if not is_configured():
        try:
            await client_ws.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "message": "未配置小米 ASR 密钥（MIMO/XIAOMI_API_KEY）",
                    }
                )
            )
        except Exception:
            pass
        return

    try:
        await client_ws.send_text(json.dumps({"type": "connected", "backend": "mimo"}))
    except Exception:
        return

    pcm_chunks: list[bytes] = []
    sample_rate = 16000
    recognizing = False

    async def finalize_utterance() -> None:
        nonlocal pcm_chunks, recognizing
        if recognizing:
            return
        blob = b"".join(pcm_chunks)
        pcm_chunks = []
        if len(blob) < 3200:  # <100ms @16k mono s16le
            return
        recognizing = True
        try:
            wav = pcm16le_to_wav_bytes(blob, sample_rate=sample_rate)
            text, err, meta = await transcribe_mimo_asr_async(wav, mime_type="audio/wav")
            if err or not text:
                logger.warning("mimo-asr failed: %s meta=%s", err, meta)
                try:
                    await client_ws.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "message": f"云端 ASR 失败：{err or 'empty'}",
                            }
                        )
                    )
                except Exception:
                    pass
                return
            # FunASRBackend 认 mode 含 offline / 2pass-offline
            payload = {
                "mode": "2pass-offline",
                "text": text,
                "is_final": True,
                "backend": "mimo",
            }
            await client_ws.send_text(json.dumps(payload, ensure_ascii=False))
        finally:
            recognizing = False

    try:
        while True:
            msg = await client_ws.receive()
            if "bytes" in msg and msg["bytes"] is not None:
                pcm_chunks.append(bytes(msg["bytes"]))
                continue
            if "text" not in msg:
                continue
            raw = msg["text"]
            try:
                body = json.loads(raw) if isinstance(raw, str) else {}
            except Exception:
                continue
            if not isinstance(body, dict):
                continue
            fs = body.get("audio_fs") or body.get("sample_rate")
            if fs:
                try:
                    sample_rate = int(fs)
                except Exception:
                    pass
            if body.get("is_speaking") is False:
                await finalize_utterance()
    except WebSocketDisconnect:
        await finalize_utterance()
    except Exception as exc:
        logger.info("mimo asr proxy error: %s", exc)
        try:
            await client_ws.send_text(json.dumps({"type": "error", "message": str(exc)}))
        except Exception:
            pass


async def _proxy_to_funasr(client_ws: WebSocket) -> None:
    import ssl as _ssl

    funasr_urls = _detect_funasr_host()
    ssl_ctx = None
    if FUNASR_USE_SSL:
        ssl_ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = _ssl.CERT_NONE

    connect_result = await _connect_funasr_parallel(funasr_urls, ssl_ctx)
    if connect_result is None:
        logger.warning("FunASR 不可达，已尝试: %s", funasr_urls)
        try:
            await client_ws.send_text(json.dumps({"type": "error", "message": "FunASR 服务未启动"}))
        except Exception:
            pass
        return

    funasr_url, funasr_ws = connect_result
    logger.info("FunASR connected via %s", funasr_url)
    try:
        try:
            await client_ws.send_text(json.dumps({"type": "connected", "backend": "funasr"}))
        except Exception:
            return

        async def client_to_funasr():
            text_count = 0
            bytes_count = 0
            try:
                while True:
                    msg = await client_ws.receive()
                    if "text" in msg:
                        data = msg["text"]
                        text_count += 1
                        if text_count <= 3:
                            logger.info(
                                "client→funasr text[#%d]: %s",
                                text_count,
                                data[:200],
                            )
                        try:
                            await funasr_ws.send(data)
                        except Exception:
                            break
                    elif "bytes" in msg:
                        bytes_count += 1
                        if bytes_count <= 3:
                            logger.info(
                                "client→funasr bytes[#%d]: %d",
                                bytes_count,
                                len(msg["bytes"]),
                            )
                        try:
                            await funasr_ws.send(msg["bytes"])
                        except Exception:
                            break
            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.info("client_to_funasr error: %s", e)
            finally:
                logger.info(
                    "client_to_funasr ended. text=%d bytes=%d",
                    text_count,
                    bytes_count,
                )
                try:
                    await funasr_ws.send(json.dumps({"is_speaking": False}))
                    logger.info("sent is_speaking=false to funasr")
                except Exception:
                    pass

        async def funasr_to_client():
            msg_count = 0
            try:
                async for raw in funasr_ws:
                    msg_count += 1
                    if isinstance(raw, bytes):
                        logger.info(
                            "funasr→client bytes[#%d]: %d",
                            msg_count,
                            len(raw),
                        )
                        try:
                            await client_ws.send_bytes(raw)
                        except Exception:
                            break
                    else:
                        logger.info(
                            "funasr→client text[#%d]: %s",
                            msg_count,
                            raw[:500],
                        )
                        try:
                            await client_ws.send_text(raw)
                        except Exception:
                            break
            except Exception as e:
                logger.info("funasr_to_client error: %s", e)
            finally:
                logger.info(
                    "funasr_to_client ended. total_msgs=%d",
                    msg_count,
                )

        client_task = asyncio.create_task(client_to_funasr())
        funasr_task = asyncio.create_task(funasr_to_client())
        done, pending = await asyncio.wait(
            [client_task, funasr_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        # 客户端断开后 FunASR 仍会异步返回 offline 结果，须继续转发
        if client_task in done and not funasr_task.done():
            try:
                await asyncio.wait_for(funasr_task, timeout=12.0)
            except asyncio.TimeoutError:
                funasr_task.cancel()
                try:
                    await funasr_task
                except asyncio.CancelledError:
                    pass
        else:
            for t in pending:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
    finally:
        try:
            await funasr_ws.close()
        except Exception:
            pass


async def _funasr_reachable() -> bool:
    import ssl as _ssl

    funasr_urls = _detect_funasr_host()
    ssl_ctx = None
    if FUNASR_USE_SSL:
        ssl_ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = _ssl.CERT_NONE
    connect_result = await _connect_funasr_parallel(funasr_urls, ssl_ctx)
    if connect_result is None:
        return False
    try:
        await connect_result[1].close()
    except Exception:
        pass
    return True


async def _dispatch_asr_proxy(client_ws: WebSocket) -> None:
    pref = _asr_backend_pref()
    from modstore_server.mimo_asr_service import is_configured as mimo_ready

    if pref == "mimo":
        logger.info("ASR backend=mimo (forced)")
        await _proxy_to_mimo(client_ws)
        return

    if pref == "funasr":
        await _proxy_to_funasr(client_ws)
        return

    # auto: FunASR 可达则本地，否则云端 MiMo
    if await _funasr_reachable():
        await _proxy_to_funasr(client_ws)
        return
    if mimo_ready():
        logger.info("ASR auto: FunASR down, using mimo-v2.5-asr")
        await _proxy_to_mimo(client_ws)
        return
    try:
        await client_ws.send_text(json.dumps({"type": "error", "message": "FunASR 服务未启动"}))
    except Exception:
        pass


def _ws_bearer_token(ws: WebSocket, query_token: str) -> str:
    t = (query_token or "").strip()
    if t:
        return t
    auth = (ws.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


@router.websocket("/funasr")
async def asr_funasr_ws(
    ws: WebSocket,
    token: str = Query(""),
) -> None:
    await ws.accept()
    token = _ws_bearer_token(ws, token)
    if not token:
        try:
            await ws.send_text(json.dumps({"type": "error", "message": "请先登录后再使用语音识别"}))
        except Exception:
            pass
        await ws.close()
        return

    try:
        from modstore_server.auth_service import decode_access_token

        payload = decode_access_token(token)
        if not payload or not payload.get("sub"):
            try:
                await ws.send_text(json.dumps({"type": "error", "message": "认证无效"}))
            except Exception:
                pass
            await ws.close()
            return
    except Exception:
        try:
            await ws.send_text(json.dumps({"type": "error", "message": "认证失败"}))
        except Exception:
            pass
        await ws.close()
        return

    await _dispatch_asr_proxy(ws)
