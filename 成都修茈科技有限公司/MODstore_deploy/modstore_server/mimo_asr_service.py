"""小米 MiMo-V2.5 ASR（chat/completions + input_audio）。

用于在本地 FunASR 不可用时，按同样的前端协议提供云端识别。
"""

from __future__ import annotations

import base64
import io
import logging
import os
import struct
import wave
from typing import Any, Dict, Optional, Tuple

_LOG = logging.getLogger(__name__)

DEFAULT_MODEL = "mimo-v2.5-asr"
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


def pcm16le_to_wav_bytes(pcm: bytes, *, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """将 16-bit LE PCM 包成 WAV，供 MiMo ASR data URL 使用。"""
    if not pcm:
        return b""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(max(1, int(channels)))
        wf.setsampwidth(2)
        wf.setframerate(max(8000, int(sample_rate)))
        wf.writeframes(pcm)
    return buf.getvalue()


def _chat_completions_url(root: str) -> str:
    return f"{root.rstrip('/')}/v1/chat/completions"


def _extract_transcript(data: Dict[str, Any]) -> str:
    choice0 = (data.get("choices") or [None])[0] or {}
    message = choice0.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "".join(parts).strip()
    return str(content or "").strip()


async def transcribe_mimo_asr_async(
    audio_bytes: bytes,
    *,
    mime_type: str = "audio/wav",
    model: str = DEFAULT_MODEL,
    language: str = "auto",
    timeout_s: float = 45.0,
) -> Tuple[Optional[str], str, Dict[str, Any]]:
    """异步识别。返回 (text, error, meta)。"""
    if not audio_bytes:
        return None, "empty audio", {}

    api_key, root = resolve_mimo_credentials()
    if not api_key:
        return None, "missing mimo api key", {}

    mime = (mime_type or "audio/wav").strip() or "audio/wav"
    b64 = base64.b64encode(audio_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"
    model_id = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    payload: Dict[str, Any] = {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data_url},
                    }
                ],
            }
        ],
        "asr_options": {"language": (language or "auto").strip() or "auto"},
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
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("mimo-asr request failed: %s", exc)
        return None, str(exc), {"url": url, "model": model_id}

    text = _extract_transcript(data if isinstance(data, dict) else {})
    if not text:
        return None, "mimo-asr empty transcript", {"url": url, "model": model_id}
    return text, "", {"url": url, "model": model_id, "bytes": len(audio_bytes)}


def estimate_pcm_duration_ms(pcm: bytes, *, sample_rate: int = 16000) -> int:
    if sample_rate <= 0 or not pcm:
        return 0
    samples = len(pcm) // 2
    return int(samples * 1000 / sample_rate)


def looks_like_pcm16_header(data: bytes) -> bool:
    """粗判：非 JSON、长度偶数、非 RIFF。"""
    if not data or len(data) < 2 or len(data) % 2:
        return False
    if data[:4] == b"RIFF":
        return False
    if data[:1] in (b"{", b"["):
        return False
    # 避免把纯文本当 PCM
    try:
        data[:64].decode("utf-8")
        if all(32 <= b < 127 or b in (9, 10, 13) for b in data[:64]):
            return False
    except Exception:
        pass
    # 简单能量检查：全 0 不算有效语音
    if data == b"\x00" * len(data):
        return False
    _ = struct  # keep import used for future frame utils
    return True
