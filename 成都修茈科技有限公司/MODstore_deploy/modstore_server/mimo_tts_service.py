"""小米 MiMo-V2.5 TTS（chat/completions + audio 参数）。

优先于 Edge 神经音；无密钥或调用失败时由调用方回退 edge-tts。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

_LOG = logging.getLogger(__name__)

DEFAULT_MODEL = "mimo-v2.5-tts"
DEFAULT_VOICE = "冰糖"
DEFAULT_STYLE = "温和、清晰、专业的客服语气，语速适中，吐字清楚。"
DEFAULT_FORMAT = "wav"
MAX_TEXT_LENGTH = 4000
_DEFAULT_ROOT = "https://token-plan-cn.xiaomimimo.com"


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def resolve_mimo_credentials() -> Tuple[Optional[str], str]:
    key = _env("XIAOMI_API_KEY") or _env("MIMO_API_KEY") or _env("XIAOMI_MIMO_API_KEY")
    root = (
        _env("XIAOMI_BASE_URL")
        or _env("MIMO_BASE_URL")
        or _env("XIAOMI_MIMO_BASE_URL")
        or _DEFAULT_ROOT
    )
    root = root.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return (key or None), root


def is_configured() -> bool:
    key, _ = resolve_mimo_credentials()
    return bool(key)


def _chat_completions_url(root: str) -> str:
    return f"{root.rstrip('/')}/v1/chat/completions"


def _decode_response(
    data: Any, voice: str, fmt: str, model: str
) -> Tuple[Optional[bytes], str, Dict[str, Any]]:
    choices = data.get("choices") if isinstance(data, dict) else None
    choice = choices[0] if isinstance(choices, list) and choices else None
    message = choice.get("message") if isinstance(choice, dict) else None
    audio = message.get("audio") if isinstance(message, dict) else None
    encoded = audio.get("data") if isinstance(audio, dict) else None
    if not isinstance(encoded, str) or not encoded:
        return None, "mimo-tts response missing audio.data", {"voice": voice, "status": 502}
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None, "mimo-tts invalid audio.data", {"voice": voice, "status": 502}
    if not raw:
        return None, "mimo-tts returned empty audio", {"voice": voice, "status": 502}
    mime = "audio/wav" if fmt in ("wav", "wave") else f"audio/{fmt}"
    return (
        raw,
        "",
        {"model": model, "voice": voice, "format": fmt, "mime": mime, "provider": "mimo"},
    )


def _request_failure(exc: Exception, voice: str) -> Tuple[Optional[bytes], str, Dict[str, Any]]:
    import httpx

    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(exc, httpx.TimeoutException):
        status = 504
    elif status not in (429, 503, 504):
        status = 502
    return None, "mimo-tts request failed", {"voice": voice, "status": status}


def synthesize_mimo_tts(
    text: str,
    *,
    voice: str = DEFAULT_VOICE,
    style: str = DEFAULT_STYLE,
    audio_format: str = DEFAULT_FORMAT,
    model: str = DEFAULT_MODEL,
    timeout_s: float = 45.0,
) -> Tuple[Optional[bytes], str, Dict[str, Any]]:
    """同步合成。返回 (audio_bytes, error, meta)。"""
    t = (text or "").strip()
    if not t:
        return None, "empty text", {}
    if len(t) > MAX_TEXT_LENGTH:
        return None, "mimo-tts text exceeds 4000 characters", {}

    api_key, root = resolve_mimo_credentials()
    if not api_key:
        return None, "missing mimo api key", {}

    voice_id = (voice or "").strip() or DEFAULT_VOICE
    fmt = (audio_format or DEFAULT_FORMAT).strip().lower() or DEFAULT_FORMAT
    payload: Dict[str, Any] = {
        "model": (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "messages": [
            {
                "role": "user",
                "content": (style or DEFAULT_STYLE).strip() or DEFAULT_STYLE,
            },
            {"role": "assistant", "content": t},
        ],
        "audio": {"format": fmt, "voice": voice_id},
    }
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key,
        "Authorization": f"Bearer {api_key}",
    }
    url = _chat_completions_url(root)

    try:
        import httpx
    except ImportError:
        return None, "httpx not installed", {}

    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        _LOG.warning("mimo-tts request failed: %s", type(exc).__name__)
        return _request_failure(exc, voice_id)
    try:
        data = resp.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "mimo-tts invalid JSON", {"voice": voice_id, "status": 502}
    return _decode_response(data, voice_id, fmt, payload["model"])


async def synthesize_mimo_tts_async(
    text: str,
    *,
    voice: str = DEFAULT_VOICE,
    style: str = DEFAULT_STYLE,
    audio_format: str = DEFAULT_FORMAT,
    model: str = DEFAULT_MODEL,
    timeout_s: float = 45.0,
) -> Tuple[Optional[bytes], str, Dict[str, Any]]:
    """异步合成（供 FastAPI 路由使用）。"""
    t = (text or "").strip()
    if not t:
        return None, "empty text", {}
    if len(t) > MAX_TEXT_LENGTH:
        return None, "mimo-tts text exceeds 4000 characters", {}

    api_key, root = resolve_mimo_credentials()
    if not api_key:
        return None, "missing mimo api key", {}

    voice_id = (voice or "").strip() or DEFAULT_VOICE
    fmt = (audio_format or DEFAULT_FORMAT).strip().lower() or DEFAULT_FORMAT
    payload: Dict[str, Any] = {
        "model": (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "messages": [
            {
                "role": "user",
                "content": (style or DEFAULT_STYLE).strip() or DEFAULT_STYLE,
            },
            {"role": "assistant", "content": t},
        ],
        "audio": {"format": fmt, "voice": voice_id},
    }
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key,
        "Authorization": f"Bearer {api_key}",
    }
    url = _chat_completions_url(root)

    try:
        import httpx
    except ImportError:
        return None, "httpx not installed", {}

    try:
        async with asyncio.timeout(timeout_s):
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
    except TimeoutError:
        return None, "mimo-tts request timed out", {"voice": voice_id, "status": 504}
    except httpx.HTTPError as exc:
        _LOG.warning("mimo-tts async request failed: %s", type(exc).__name__)
        return _request_failure(exc, voice_id)
    try:
        data = resp.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "mimo-tts invalid JSON", {"voice": voice_id, "status": 502}
    return _decode_response(data, voice_id, fmt, payload["model"])
