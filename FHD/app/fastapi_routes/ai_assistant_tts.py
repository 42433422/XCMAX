"""TTS compatibility endpoints split from the general AI-assistant router."""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import math
import re
from typing import Any

import aiohttp
import httpx
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.domain.shared_services.tts_service import (
    TtsUpstreamBlockedError,
    TtsUpstreamResponseError,
    edge_cooldown_remaining_seconds,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router = APIRouter()


def _trace(payload: dict[str, Any], *, route: str, action: str, body: dict[str, Any]):
    from app.fastapi_routes.ai_assistant import _trace_ai_assistant_route

    return _trace_ai_assistant_route(payload, route=route, action=action, body=body)


@router.post("/api/tts/translate")
def compat_tts_translate(payload: dict[str, Any] = Body(default_factory=dict)):
    """Translate a short Chinese subtitle to English for speech."""
    text = str(payload.get("text") or "").strip()
    if not text:
        return JSONResponse(
            {"success": False, "message": "text 不能为空", "data": {}}, status_code=400
        )
    target = str(payload.get("target") or "en").strip().lower()
    if target != "en":
        return JSONResponse(
            {"success": False, "message": "仅支持 target=en", "data": {}}, status_code=400
        )
    try:
        from app.application.tts_translate_app_service import translate_zh_to_en

        async def _run() -> str:
            result = await translate_zh_to_en(text, max_chars=500)
            if not result.get("success"):
                raise RuntimeError(str(result.get("message") or "translate failed"))
            return str(result.get("translation") or "").strip().strip('"').strip("'")

        try:
            translation = asyncio.run(_run())
        except RuntimeError as loop_error:
            if "asyncio.run()" not in str(loop_error):
                raise
            loop = asyncio.new_event_loop()
            try:
                translation = loop.run_until_complete(_run())
            finally:
                loop.close()
        if not translation:
            raise RuntimeError("empty translation")
        return JSONResponse(
            _trace(
                {
                    "success": True,
                    "message": "ok",
                    "data": {"translation": translation, "target": "en"},
                },
                route="/api/tts/translate",
                action="tts_translate",
                body=payload,
            )
        )
    except RECOVERABLE_ERRORS as error:
        logger.warning("TTS translate unavailable: %s", error)
        return JSONResponse(
            {"success": False, "message": "翻译暂不可用", "data": {}}, status_code=503
        )


@router.post("/api/tts")
def compat_tts(payload: dict[str, Any] = Body(default_factory=dict)):
    text = payload.get("text")
    fields = ("voice", "speakerId", "lang", "rate", "pitch")
    valid = isinstance(text, str) and 0 < len(text.strip()) <= 4000
    valid = valid and all(
        payload.get(field) is None
        or (isinstance(payload[field], str) and len(payload[field]) <= 120)
        for field in fields
    )
    for field, unit, lower, upper in (("rate", "%", -100, 100), ("pitch", "Hz", -100, 100)):
        value = payload.get(field)
        if value is not None:
            if (
                not isinstance(value, str)
                or not re.fullmatch(r"[+-][0-9]{1,3}" + unit, value)
                or not lower <= int(value[: -len(unit)]) <= upper
            ):
                valid = False
    if not valid or not isinstance(text, str):
        return JSONResponse(
            {"success": False, "message": "TTS 请求参数无效", "data": {}}, status_code=422
        )
    text = text.strip()
    speaker_id = payload.get("speakerId")
    lang = (payload.get("lang") or "zh").strip().lower()
    try:
        from app.application.facades.tts_facade import (
            synthesize_to_data_uri,
            trigger_common_tts_warmup,
        )

        trigger_common_tts_warmup()
        result = synthesize_to_data_uri(
            text=text,
            voice=payload.get("voice"),
            speaker_id=speaker_id,
            lang=lang,
            rate=payload.get("rate"),
            pitch=payload.get("pitch"),
        )
        audio = result.get("audioBase64") if isinstance(result, dict) else None
        if not isinstance(audio, str) or not re.match(
            r"^data:audio/[a-zA-Z0-9.+-]+;base64,", audio
        ):
            raise TtsUpstreamResponseError("TTS returned invalid audio data URI")
        try:
            decoded = base64.b64decode(audio.split(",", 1)[1], validate=True)
        except (binascii.Error, ValueError) as error:
            raise TtsUpstreamResponseError("TTS returned invalid audio data") from error
        if not decoded:
            raise TtsUpstreamResponseError("TTS returned empty audio")
        traced = _trace(
            {
                "success": True,
                "message": "ok",
                "data": {
                    "audioBase64": result.get("audioBase64"),
                    "voice": result.get("voice"),
                    "speakerId": speaker_id,
                    "lang": result.get("lang") or lang,
                    "provider": result.get("provider") or "edge",
                },
            },
            route="/api/tts",
            action="tts_synthesize",
            body=payload,
        )
        return JSONResponse(traced)
    except TtsUpstreamBlockedError as error:
        logger.warning("TTS 上游拒绝握手: %s", error)
        traced = _trace(
            {
                "success": False,
                "code": "TTS_UPSTREAM_FORBIDDEN",
                "message": str(error),
                "data": {
                    "reason": "edge_403",
                    "fallback": "offline_tts",
                },
            },
            route="/api/tts",
            action="tts_synthesize",
            body=payload,
        )
        return JSONResponse(
            traced,
            status_code=503,
            headers={
                "Retry-After": str(math.ceil(edge_cooldown_remaining_seconds())),
                "Cache-Control": "no-store",
            },
        )
    except (TtsUpstreamResponseError, httpx.HTTPError, aiohttp.ClientError, OSError) as error:
        status = getattr(error, "status", None) or getattr(
            getattr(error, "response", None), "status_code", None
        )
        if isinstance(error, (TimeoutError, httpx.TimeoutException, asyncio.TimeoutError)):
            status = 504
        elif status not in (429, 503, 504):
            status = 502
        logger.warning("TTS 上游不可用: %s (status=%s)", type(error).__name__, status)
        traced = _trace(
            {
                "success": False,
                "message": "TTS 服务暂不可用（已尝试 MiMo 与 Edge 神经音）",
                "data": {"reason": "tts_unavailable"},
            },
            route="/api/tts",
            action="tts_synthesize",
            body=payload,
        )
        return JSONResponse(traced, status_code=status)
