"""DeepSeek Provider（云端档）。

收敛入口：包装 ``app.ai_engines.deepseek.intent_service.DeepseekIntentClassifier``
（其本身已从旧的 ``app.services.deepseek_intent_service`` 迁移而来），并复用
``infrastructure.llm.client`` 的云端 OpenAI 兼容客户端做 chat 能力。

具备 CHAT + INTENT 两种能力。缺密钥时 ``is_available()`` 返回 False。
"""

from __future__ import annotations

import logging
import os
from time import perf_counter
from typing import Any

from app.infrastructure.ai.providers.base import BaseProvider, Capability, ProviderResult, Tier
from app.utils.metrics import record_ai_call

logger = logging.getLogger(__name__)


class DeepSeekProvider(BaseProvider):
    name = "deepseek"
    tier = Tier.CLOUD
    capabilities = frozenset({Capability.CHAT, Capability.INTENT})

    def __init__(self) -> None:
        self._classifier: Any | None = None

    def is_available(self) -> bool:
        if (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip():
            return True
        return False

    def _get_classifier(self) -> Any:
        if self._classifier is None:
            from app.ai_engines.deepseek.intent_service import DeepseekIntentClassifier

            self._classifier = DeepseekIntentClassifier()
        return self._classifier

    async def recognize_intent(
        self, message: str, context: list[dict[str, str]] | None = None, **kwargs: Any
    ) -> ProviderResult:
        started = perf_counter()
        try:
            data = await self._get_classifier().recognize(message, context)
            latency = (perf_counter() - started) * 1000
            record_ai_call(self.name, "intent", "success", latency / 1000)
            return ProviderResult(True, Capability.INTENT, self.name, data=data, latency_ms=latency)
        except Exception as exc:
            record_ai_call(self.name, "intent", "error")
            logger.warning("deepseek intent failed: %s", exc)
            return ProviderResult(False, Capability.INTENT, self.name, error=str(exc))

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ProviderResult:
        from app.infrastructure.llm.client import get_llm_client, resolve_chat_model

        started = perf_counter()
        try:
            client = get_llm_client()
            if client is None:
                raise RuntimeError("offline 模式无云端客户端")
            model = kwargs.get("model") or resolve_chat_model()
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=kwargs.get("temperature", 0.3),
                max_tokens=kwargs.get("max_tokens", 1024),
            )
            content = resp.choices[0].message.content
            latency = (perf_counter() - started) * 1000
            record_ai_call(self.name, "chat", "success", latency / 1000)
            return ProviderResult(
                True, Capability.CHAT, self.name, data=content, latency_ms=latency,
                meta={"model": model},
            )
        except Exception as exc:
            record_ai_call(self.name, "chat", "error")
            logger.warning("deepseek chat failed: %s", exc)
            return ProviderResult(False, Capability.CHAT, self.name, error=str(exc))
