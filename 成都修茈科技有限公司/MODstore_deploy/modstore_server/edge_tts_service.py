"""edge-tts 预热、并发限制与短句缓存（降低 TTS 首包延迟）。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import OrderedDict
from typing import AsyncIterator, Optional

_LOG = logging.getLogger(__name__)

try:
    import edge_tts as _edge_tts_mod

    _EDGE_TTS = _edge_tts_mod
except ImportError:  # pragma: no cover
    _EDGE_TTS = None

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_RATE_STR = "+0%"
WARMUP_TEXT = "你好，我在。"

_warmed_keys: set[tuple[str, str]] = set()
_warm_lock = asyncio.Lock()
_cache: OrderedDict[str, bytes] = OrderedDict()
_CACHE_MAX = 48
_CACHE_MAX_TEXT_LEN = 32
_sem = asyncio.Semaphore(4)


def rate_str_from_float(rate: float) -> str:
    pct = int(round((float(rate) - 1.0) * 80))
    pct = max(-50, min(80, pct))
    return f"{pct:+d}%"


def is_available() -> bool:
    return _EDGE_TTS is not None


def _cache_key(text: str, voice: str, rs: str) -> str:
    raw = f"{voice}\0{rs}\0{text}".encode()
    return hashlib.sha256(raw).hexdigest()[:20]


def get_cached(text: str, voice: str, rs: str) -> Optional[bytes]:
    if len(text) > _CACHE_MAX_TEXT_LEN:
        return None
    key = _cache_key(text, voice, rs)
    blob = _cache.get(key)
    if blob is not None:
        _cache.move_to_end(key)
    return blob


def put_cache(text: str, voice: str, rs: str, data: bytes) -> None:
    if len(text) > _CACHE_MAX_TEXT_LEN or not data:
        return
    key = _cache_key(text, voice, rs)
    _cache[key] = data
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


async def warm_voice(voice: str, rs: str) -> None:
    if _EDGE_TTS is None:
        return
    key = (voice, rs)
    if key in _warmed_keys:
        return
    async with _warm_lock:
        if key in _warmed_keys:
            return
        try:
            async with _sem:
                comm = _EDGE_TTS.Communicate(WARMUP_TEXT, voice=voice, rate=rs)
                async for chunk in comm.stream():
                    if chunk.get("type") == "audio" and chunk.get("data"):
                        put_cache(WARMUP_TEXT, voice, rs, chunk["data"])
                        break
        except Exception:
            _LOG.debug("edge-tts warm failed voice=%s", voice, exc_info=True)
        _warmed_keys.add(key)


async def warm_defaults() -> None:
    await warm_voice(DEFAULT_VOICE, DEFAULT_RATE_STR)


async def stream_audio(text: str, voice: str, rs: str) -> AsyncIterator[bytes]:
    if _EDGE_TTS is None:
        return
    t = (text or "").strip()
    if not t:
        return

    await warm_voice(voice, rs)
    cached = get_cached(t, voice, rs)
    if cached:
        yield cached
        return

    buf = bytearray()
    try:
        async with _sem:
            comm = _EDGE_TTS.Communicate(t, voice=voice, rate=rs)
            async for chunk in comm.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    data = chunk["data"]
                    buf.extend(data)
                    yield data
    except Exception:
        _LOG.warning("edge-tts stream failed text_len=%d voice=%s", len(t), voice, exc_info=True)
        raise

    if buf:
        put_cache(t, voice, rs, bytes(buf))
