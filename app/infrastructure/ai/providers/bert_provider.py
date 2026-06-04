"""BERT Provider（本地档）。

包装 ``app.services.bert_intent_service.BertIntentService``（嵌入式 transformers）。
torch/transformers 缺失时 ``is_available()`` 返回 False，实现优雅降级。
仅提供 INTENT 能力。
"""

from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Any

from app.infrastructure.ai.providers.base import BaseProvider, Capability, ProviderResult, Tier
from app.utils.metrics import record_ai_call

logger = logging.getLogger(__name__)


class BertProvider(BaseProvider):
    name = "bert"
    tier = Tier.LOCAL
    capabilities = frozenset({Capability.INTENT})

    def __init__(self) -> None:
        self._service: Any | None = None

    def _deps_ok(self) -> bool:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401

            return True
        except Exception:
            return False

    def _get_service(self) -> Any:
        if self._service is None:
            from app.services.bert_intent_service import BertIntentService

            self._service = BertIntentService()
        return self._service

    def is_available(self) -> bool:
        if not self._deps_ok():
            return False
        try:
            return bool(self._get_service().classifier.is_available())
        except Exception:
            return False

    async def recognize_intent(
        self, message: str, context: list[dict[str, str]] | None = None, **kwargs: Any
    ) -> ProviderResult:
        started = perf_counter()
        try:
            data = await asyncio.to_thread(self._get_service().recognize, message, None)
            latency = (perf_counter() - started) * 1000
            record_ai_call(self.name, "intent", "success", latency / 1000)
            return ProviderResult(True, Capability.INTENT, self.name, data=data, latency_ms=latency)
        except Exception as exc:
            record_ai_call(self.name, "intent", "error")
            logger.warning("bert intent failed: %s", exc)
            return ProviderResult(False, Capability.INTENT, self.name, error=str(exc))
