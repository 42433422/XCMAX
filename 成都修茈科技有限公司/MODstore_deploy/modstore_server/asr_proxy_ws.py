"""ASR WebSocket 代理：前端 → 本服务 → FunASR 服务端。

路径 ``/api/asr/funasr`` 接受前端 WebSocket 连接，将音频流转发到 FunASR
服务端（默认 ``ws://127.0.0.1:10095``），并将识别结果回传前端。

FunASR 服务端需独立部署（Docker），参见 ``docs/runbooks/funasr-deploy.md``。
若 FunASR 未启动，前端会自动降级到浏览器端 Whisper 或 Chrome Web Speech API。
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
            await client_ws.send_text(json.dumps({"type": "connected"}))
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

    await _proxy_to_funasr(ws)
