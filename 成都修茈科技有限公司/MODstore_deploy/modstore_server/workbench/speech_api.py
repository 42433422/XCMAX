"""Speech api for workbench delivery."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse

from modstore_server.api.deps import _get_current_user
from modstore_server.models import User
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.workbench.schemas import (
    WorkbenchEdgeTtsBody,
    WorkbenchUnifiedTtsBody,
)

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
        raise HTTPException(400, "text 不能为空")
    try:
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
    except RECOVERABLE_ERRORS:
        pass
    if ports.edge is None:
        raise HTTPException(
            503,
            "MiMo 与 edge-tts 均不可用。请配置 MIMO_API_KEY 或 pip install edge-tts",
        )
    edge_voice = (body.edge_voice or "zh-CN-XiaoxiaoNeural").strip()
    rate_str = _edge_tts_rate_str(body.rate)
    try:
        chunks: list[bytes] = []
        async for data in _edge_tts_stream_chunks(text, edge_voice, rate_str):
            if data:
                chunks.append(data)
        mp3 = b"".join(chunks)
        if not mp3:
            raise RuntimeError("edge-tts empty")
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
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(502, f"TTS 合成失败: {exc}") from exc


async def workbench_edge_tts(
    body: WorkbenchEdgeTtsBody,
    _user: User = Depends(_get_current_user),
    *,
    ports: SpeechPorts,
):
    if ports.edge is None:
        raise HTTPException(
            503,
            "服务端未安装 edge-tts。请在部署环境执行: pip install 'modstore[web]' 或 pip install edge-tts",
        )
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "text 不能为空")
    voice = (body.voice or "zh-CN-XiaoxiaoNeural").strip()
    rate_str = _edge_tts_rate_str(body.rate)
    try:
        return StreamingResponse(
            _edge_tts_stream_chunks(text, voice, rate_str),
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except HTTPException:
        raise
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(502, f"TTS 合成失败: {exc}") from exc


async def workbench_edge_tts_stream(
    body: WorkbenchEdgeTtsBody,
    _user: User = Depends(_get_current_user),
    *,
    ports: SpeechPorts,
):
    if ports.edge is None:
        raise HTTPException(
            503,
            "服务端未安装 edge-tts。请在部署环境执行: pip install 'modstore[web]' 或 pip install edge-tts",
        )
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "text 不能为空")
    voice = (body.voice or "zh-CN-XiaoxiaoNeural").strip()
    rate_str = _edge_tts_rate_str(body.rate)
    try:
        return StreamingResponse(
            _edge_tts_stream_chunks(text, voice, rate_str),
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except HTTPException:
        raise
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(502, f"TTS 合成失败: {exc}") from exc
