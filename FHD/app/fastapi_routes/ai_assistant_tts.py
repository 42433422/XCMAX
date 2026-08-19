"""TTS compatibility endpoints split from the general AI-assistant router."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

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
                {"success": True, "message": "ok", "data": {"translation": translation, "target": "en"}},
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
    text = str(payload.get("text") or "").strip()
    if not text:
        return JSONResponse(
            {"success": False, "message": "text 不能为空", "data": {}}, status_code=400
        )
    speaker_id = payload.get("speakerId")
    lang = str(payload.get("lang") or "zh").lower()
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
    except RECOVERABLE_ERRORS as error:
        logger.warning("TTS 不可用（MiMo/Edge）: %s", error)
        traced = _trace(
            {
                "success": False,
                "message": "TTS 服务暂不可用（已尝试 MiMo 与 Edge 神经音）",
                "data": {},
            },
            route="/api/tts",
            action="tts_synthesize",
            body=payload,
        )
        return JSONResponse(traced, status_code=503)
