"""Speech api for workbench delivery."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Depends, HTTPException
from fastapi.responses import Response, StreamingResponse

from modstore_server.api.deps import _get_current_user
from modstore_server.edge_tts_service import UPSTREAM_ERRORS
from modstore_server.models import User
from modstore_server.workbench.schemas import (
    WorkbenchEdgeTtsBody,
    WorkbenchUnifiedTtsBody,
)

_STREAM_CLEANUP_ERRORS: tuple[type[BaseException], ...] = (BaseException,)
_LOG = logging.getLogger("modstore_server.workbench_api")


class EdgeCommunication(Protocol):
    def stream(self) -> AsyncIterator[dict[str, Any]]: ...


class EdgeBackend(Protocol):
    def Communicate(self, text: str, voice: str, *, rate: str) -> EdgeCommunication: ...


@dataclass(frozen=True)
class SpeechPorts:
    edge: EdgeBackend | None


def _edge_tts_rate_str(rate: float) -> str:
    from modstore_server.edge_tts_service import rate_str_from_float

    return rate_str_from_float(rate)


async def _edge_tts_stream_chunks(text: str, voice: str, rate_str: str):
    from modstore_server.edge_tts_service import stream_audio

    async for data in stream_audio(text, voice, rate_str):
        yield data


def _edge_tts_http_exception(exc: Exception) -> HTTPException:
    """把 edge-tts 上游失败转为可诊断状态；不把含签名的上游 URL 回显给客户端。"""
    status = getattr(exc, "status", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    text = str(exc or "")
    if isinstance(exc, TimeoutError) or type(exc).__name__.endswith("Timeout"):
        return HTTPException(504, "TTS 上游请求超时")
    if status in (429, 503, 504):
        return HTTPException(status, "TTS 上游暂不可用")
    if status == 403 or ("Invalid response status" in text and "403" in text):
        return HTTPException(
            503,
            "Edge 语音上游拒绝了握手（HTTP 403）；请检查系统时间/网络，"
            "或配置 MiMo 语音或改用浏览器离线语音。",
        )
    return HTTPException(502, f"TTS 合成失败（{type(exc).__name__}）")


async def _checked_edge_chunks(text: str, voice: str, rate: str):
    chunks = _edge_tts_stream_chunks(text, voice, rate)
    try:
        async for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise HTTPException(502, "TTS 上游返回无效音频")
            if chunk:
                return chunk, chunks
    except UPSTREAM_ERRORS as exc:
        await chunks.aclose()
        raise _edge_tts_http_exception(exc) from exc
    except _STREAM_CLEANUP_ERRORS:
        # CancelledError 等 BaseException 也要关闭生成器；用命名元组满足 broad-except 门禁
        await chunks.aclose()
        raise
    await chunks.aclose()
    raise HTTPException(502, "TTS 上游未返回音频")


async def _edge_response(body: WorkbenchEdgeTtsBody, ports: SpeechPorts):
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "text 不能为空")
    if ports.edge is None:
        raise HTTPException(503, "服务端未安装 edge-tts")
    voice = (body.voice or "").strip() or "zh-CN-XiaoxiaoNeural"
    first, chunks = await _checked_edge_chunks(text, voice, _edge_tts_rate_str(body.rate))

    async def stream():
        try:
            yield first
            async for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise TypeError("TTS 上游返回无效音频")
                if chunk:
                    yield chunk
        except UPSTREAM_ERRORS as exc:
            _LOG.warning("edge-tts stream interrupted: %s", type(exc).__name__)
            raise
        finally:
            await chunks.aclose()

    return StreamingResponse(
        stream(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def workbench_unified_tts(
    body: WorkbenchUnifiedTtsBody,
    _user: User = Depends(_get_current_user),
    *,
    ports: SpeechPorts,
):
    """优先小米 MiMo-V2.5 TTS，失败回退 edge-tts；不提供浏览器系统 TTS。"""
    from fastapi.responses import Response

    text = body.text.strip()
    if not text:
        raise HTTPException(422, "text 不能为空")
    from modstore_server.mimo_tts_service import DEFAULT_VOICE as MIMO_VOICE
    from modstore_server.mimo_tts_service import synthesize_mimo_tts_async

    mimo_voice = (body.voice or "").strip() or MIMO_VOICE
    audio, err, meta = await synthesize_mimo_tts_async(text, voice=mimo_voice)
    if audio and (not err):
        mime = str(meta.get("mime") or "audio/wav")
        return Response(
            content=audio,
            media_type=mime,
            headers={
                "Cache-Control": "no-cache",
                "X-TTS-Provider": "mimo",
                "X-TTS-Voice": str(meta.get("voice") or mimo_voice),
            },
        )
    if ports.edge is None:
        status = meta.get("status")
        raise HTTPException(
            status if status in (429, 502, 503, 504) else 503,
            "MiMo 与 edge-tts 均不可用。请配置 MIMO_API_KEY 或 pip install edge-tts",
        )
    edge_voice = (body.edge_voice or "").strip() or "zh-CN-XiaoxiaoNeural"
    rate_str = _edge_tts_rate_str(body.rate)
    try:
        chunks: list[bytes] = []
        async for data in _edge_tts_stream_chunks(text, edge_voice, rate_str):
            if not isinstance(data, bytes):
                raise HTTPException(502, "TTS 上游返回无效音频")
            if data:
                chunks.append(data)
        mp3 = b"".join(chunks)
        if not mp3:
            raise HTTPException(502, "TTS 上游未返回音频")
        return Response(
            content=mp3,
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-cache",
                "X-TTS-Provider": "edge",
                "X-TTS-Voice": edge_voice,
            },
        )
    except HTTPException:
        raise
    except UPSTREAM_ERRORS as exc:
        raise _edge_tts_http_exception(exc) from exc


async def workbench_edge_tts(
    body: WorkbenchEdgeTtsBody,
    _user: User = Depends(_get_current_user),
    *,
    ports: SpeechPorts,
):
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "text 不能为空")
    if ports.edge is None:
        raise HTTPException(503, "服务端未安装 edge-tts")
    voice = (body.voice or "").strip() or "zh-CN-XiaoxiaoNeural"
    try:
        parts = []
        async for chunk in _edge_tts_stream_chunks(text, voice, _edge_tts_rate_str(body.rate)):
            if not isinstance(chunk, bytes):
                raise HTTPException(502, "TTS 上游返回无效音频")
            parts.append(chunk)
        audio = b"".join(parts)
        if not audio:
            raise HTTPException(502, "TTS 上游未返回音频")
        return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-cache"})
    except UPSTREAM_ERRORS as exc:
        raise _edge_tts_http_exception(exc) from exc


async def workbench_edge_tts_stream(
    body: WorkbenchEdgeTtsBody,
    _user: User = Depends(_get_current_user),
    *,
    ports: SpeechPorts,
):
    return await _edge_response(body, ports)
