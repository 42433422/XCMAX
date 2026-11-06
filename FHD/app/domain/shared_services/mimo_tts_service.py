"""小米 MiMo-V2.5 TTS（chat/completions + audio）。FHD /api/tts 首选引擎。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
from typing import Any

from app.domain.shared_services.tts_service import TtsUpstreamResponseError

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "mimo-v2.5-tts"
DEFAULT_VOICE = "冰糖"
DEFAULT_STYLE = "温和、清晰、专业的客服语气，语速适中，吐字清楚。"
DEFAULT_FORMAT = "wav"
DEFAULT_TIMEOUT_S = 8.0
_DEFAULT_ROOT = "https://token-plan-cn.xiaomimimo.com"


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def resolve_mimo_credentials() -> tuple[str | None, str]:
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


def synthesize_mimo_bytes(
    text: str,
    *,
    voice: str = DEFAULT_VOICE,
    style: str = DEFAULT_STYLE,
    audio_format: str = DEFAULT_FORMAT,
    model: str = DEFAULT_MODEL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> tuple[bytes, dict[str, Any]]:
    """同步合成，成功返回 (bytes, meta)；失败抛 RuntimeError。"""
    t = (text or "").strip()
    if not t:
        raise ValueError("text is empty")

    api_key, root = resolve_mimo_credentials()
    if not api_key:
        raise RuntimeError("mimo api key missing")

    voice_id = (voice or "").strip() or DEFAULT_VOICE
    fmt = (audio_format or DEFAULT_FORMAT).strip().lower() or DEFAULT_FORMAT
    payload: dict[str, Any] = {
        "model": (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "messages": [
            {"role": "user", "content": (style or DEFAULT_STYLE).strip() or DEFAULT_STYLE},
            {"role": "assistant", "content": t[:4000]},
        ],
        "audio": {"format": fmt, "voice": voice_id},
    }
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key,
        "Authorization": f"Bearer {api_key}",
    }
    url = f"{root}/v1/chat/completions"

    import httpx

    async def request() -> dict[str, Any]:
        # A per-read HTTP timeout alone lets a slow stream delay Edge indefinitely.
        async with asyncio.timeout(timeout_s):
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                try:
                    payload_json = resp.json()
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise TtsUpstreamResponseError("mimo-tts returned invalid JSON") from exc
                if not isinstance(payload_json, dict):
                    raise TtsUpstreamResponseError("mimo-tts returned non-object JSON")
                return payload_json

    data = asyncio.run(request())

    choices = data.get("choices") if isinstance(data, dict) else None
    choice0 = choices[0] if isinstance(choices, list) and choices else None
    message = choice0.get("message") if isinstance(choice0, dict) else None
    audio = message.get("audio") if isinstance(message, dict) else None
    b64 = audio.get("data") if isinstance(audio, dict) else None
    if not isinstance(b64, str) or not b64.strip():
        raise TtsUpstreamResponseError("mimo-tts response missing audio.data")
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TtsUpstreamResponseError("mimo-tts returned invalid audio.data") from exc
    if not raw:
        raise TtsUpstreamResponseError("mimo-tts returned empty audio")

    mime = "audio/wav" if fmt in ("wav", "wave") else f"audio/{fmt}"
    return raw, {
        "provider": "mimo",
        "model": payload["model"],
        "voice": voice_id,
        "format": fmt,
        "mime": mime,
    }
