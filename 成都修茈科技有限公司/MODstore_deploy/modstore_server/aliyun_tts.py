"""阿里云百炼 / DashScope 语音合成（与前端 actions.voice_output.tts.provider=aliyun 对齐）。"""

from __future__ import annotations

import base64
from typing import Any, Dict, Optional, Tuple


def synthesize_aliyun_tts(
    text: str,
    api_key: str,
    *,
    voice_name: str = "",
    sample_rate: int = 24000,
) -> Tuple[Optional[bytes], str, Dict[str, Any]]:
    """使用 DashScope Sambert 同步 TTS。返回 (audio_bytes, error, meta)。"""
    t = (text or "").strip()
    if not t:
        return None, "empty text", {}
    if not api_key:
        return None, "missing api key", {}

    try:
        from dashscope.audio.tts import SpeechSynthesizer  # type: ignore[import-untyped]
    except ImportError:
        try:
            from dashscope.audio.tts_v2 import SpeechSynthesizer  # type: ignore[import-untyped]
        except ImportError:
            return (
                None,
                "请安装 dashscope: pip install dashscope（或 modstore 可选依赖 aliyun-tts）",
                {},
            )

    model = (voice_name or "").strip() or "sambert-zhichu-v1"
    if not model.startswith("sambert-") and not model.startswith("cosyvoice"):
        model = "sambert-zhichu-v1"

    try:
        result = SpeechSynthesizer.call(
            model=model,
            text=t[:2000],
            sample_rate=int(sample_rate) if sample_rate else 24000,
            api_key=api_key,
        )
    except Exception as e:  # noqa: BLE001
        return None, str(e), {}

    raw: Optional[bytes] = None
    try:
        if hasattr(result, "get_audio_data"):
            raw = result.get_audio_data()
    except Exception:
        raw = None
    if not raw and isinstance(result, dict):
        b64 = (
            result.get("output", {}).get("audio", {}).get("data")
            if isinstance(result.get("output"), dict)
            else None
        )
        if isinstance(b64, str):
            try:
                raw = base64.b64decode(b64)
            except Exception:
                raw = None
    if not raw:
        err = ""
        if hasattr(result, "get_response"):
            try:
                err = str(result.get_response())
            except Exception:
                err = repr(result)
        else:
            err = getattr(result, "message", None) or repr(result)
        return None, err or "TTS 未返回音频", {}

    return raw, "", {"model": model, "sample_rate": sample_rate}
