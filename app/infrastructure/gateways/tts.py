"""TTS 网关。"""

from __future__ import annotations

from app.services import synthesize_to_data_uri  # noqa: F401
from app.services.tts_service import trigger_common_tts_warmup  # noqa: F401

__all__ = ["synthesize_to_data_uri", "trigger_common_tts_warmup"]
