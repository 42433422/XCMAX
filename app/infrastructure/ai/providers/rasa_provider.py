"""RASA Provider（边缘档）。

包装 ``app.ai_engines.rasa.nlu_service.RasaNLUService``（嵌入式或远端 RASA 服务）。
归类为 edge 档：通常以局域网/同机房自托管 RASA server 形式部署。
仅提供 INTENT 能力。
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from app.infrastructure.ai.providers.base import BaseProvider, Capability, ProviderResult, Tier
from app.utils.metrics import record_ai_call

logger = logging.getLogger(__name__)


class RasaProvider(BaseProvider):
    name = "rasa"
    tier = Tier.EDGE
    capabilities = frozenset({Capability.INTENT})

    def __init__(self) -> None:
        self._service: Any | None = None

    def _get_service(self) -> Any:
        if self._service is None:
            from app.ai_engines.rasa.nlu_service import RasaNLUService

            self._service = RasaNLUService()
        return self._service

    def is_available(self) -> bool:
        try:
            return bool(self._get_service().is_available())
        except Exception:
            return False

    async def recognize_intent(
        self, message: str, context: list[dict[str, str]] | None = None, **kwargs: Any
    ) -> ProviderResult:
        started = perf_counter()
        try:
            raw = await self._get_service().parse_async(message)
            intent = (raw or {}).get("intent") or {}
            data = {
                "intent": intent.get("name"),
                "confidence": intent.get("confidence", 0.0),
                "entities": (raw or {}).get("entities", []),
                "source": "rasa",
            }
            latency = (perf_counter() - started) * 1000
            record_ai_call(self.name, "intent", "success", latency / 1000)
            return ProviderResult(True, Capability.INTENT, self.name, data=data, latency_ms=latency)
        except Exception as exc:
            record_ai_call(self.name, "intent", "error")
            logger.warning("rasa intent failed: %s", exc)
            return ProviderResult(False, Capability.INTENT, self.name, error=str(exc))
