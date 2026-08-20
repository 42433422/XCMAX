"""小米 MiMo-V2.5 TTS（chat/completions + audio 参数）。

优先于 Edge 神经音；无密钥或调用失败时由调用方回退 edge-tts。
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, Optional, Tuple

from modstore_server.operational_errors import BOUNDARY_ERRORS

_LOG = logging.getLogger(__name__)

DEFAULT_MODEL = "mimo-v2.5-tts"
DEFAULT_VOICE = "冰糖"
DEFAULT_STYLE = "温和、清晰、专业的客服语气，语速适中，吐字清楚。"
DEFAULT_FORMAT = "wav"
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
            {"role": "assistant", "content": t[:4000]},
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
            data = resp.json()
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        _LOG.warning("mimo-tts request failed: %s", exc)
        return None, str(exc), {"url": url, "voice": voice_id}

    try:
        choice0 = (data.get("choices") or [None])[0] or {}
        message = choice0.get("message") or {}
        audio = message.get("audio") or {}
        b64 = audio.get("data") if isinstance(audio, dict) else None
        if not isinstance(b64, str) or not b64.strip():
            return None, "mimo-tts response missing audio.data", {"voice": voice_id}
        raw = base64.b64decode(b64)
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        return None, f"mimo-tts decode failed: {exc}", {"voice": voice_id}

    if not raw:
        return None, "mimo-tts returned empty audio", {"voice": voice_id}

    mime = "audio/wav" if fmt in ("wav", "wave") else f"audio/{fmt}"
    return (
        raw,
        "",
        {
            "model": payload["model"],
            "voice": voice_id,
            "format": fmt,
            "mime": mime,
            "provider": "mimo",
        },
    )


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
            {"role": "assistant", "content": t[:4000]},
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
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        _LOG.warning("mimo-tts async request failed: %s", exc)
        return None, str(exc), {"url": url, "voice": voice_id}

    try:
        choice0 = (data.get("choices") or [None])[0] or {}
        message = choice0.get("message") or {}
        audio = message.get("audio") or {}
        b64 = audio.get("data") if isinstance(audio, dict) else None
        if not isinstance(b64, str) or not b64.strip():
            return None, "mimo-tts response missing audio.data", {"voice": voice_id}
        raw = base64.b64decode(b64)
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        return None, f"mimo-tts decode failed: {exc}", {"voice": voice_id}

    if not raw:
        return None, "mimo-tts returned empty audio", {"voice": voice_id}

    mime = "audio/wav" if fmt in ("wav", "wave") else f"audio/{fmt}"
    return (
        raw,
        "",
        {
            "model": payload["model"],
            "voice": voice_id,
            "format": fmt,
            "mime": mime,
            "provider": "mimo",
        },
    )
