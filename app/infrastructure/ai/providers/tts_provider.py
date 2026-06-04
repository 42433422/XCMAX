"""TTS Provider（边缘档）。

包装 ``app.services.tts_service.synthesize_to_data_uri``（edge-tts）。
edge-tts 缺失时 ``is_available()`` 返回 False。仅提供 TTS 能力。
"""

from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Any

from app.infrastructure.ai.providers.base import BaseProvider, Capability, ProviderResult, Tier
from app.utils.metrics import record_ai_call

logger = logging.getLogger(__name__)


class TTSProvider(BaseProvider):
    name = "edge_tts"
    tier = Tier.EDGE
    capabilities = frozenset({Capability.TTS})

    def is_available(self) -> bool:
        try:
            import edge_tts  # noqa: F401

            return True
        except Exception:
            return False

    async def synthesize(self, text: str, voice: str | None = None, **kwargs: Any) -> ProviderResult:
        from app.services.tts_service import synthesize_to_data_uri

        started = perf_counter()
        try:
            data = await asyncio.to_thread(
                synthesize_to_data_uri,
                text=text,
                voice=voice,
                lang=kwargs.get("lang", "zh"),
                rate=kwargs.get("rate"),
                pitch=kwargs.get("pitch"),
            )
            latency = (perf_counter() - started) * 1000
            record_ai_call(self.name, "tts", "success", latency / 1000)
            return ProviderResult(True, Capability.TTS, self.name, data=data, latency_ms=latency)
        except Exception as exc:
            record_ai_call(self.name, "tts", "error")
            logger.warning("edge_tts synthesize failed: %s", exc)
            return ProviderResult(False, Capability.TTS, self.name, error=str(exc))
