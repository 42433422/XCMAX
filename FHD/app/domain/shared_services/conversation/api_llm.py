"""LLM provider routing for the conversation API mixin."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _api_module():
    from app.domain.shared_services.conversation import api

    return api


class ConversationLlmMixin:
    if TYPE_CHECKING:
        _last_llm_trace: Any
        api_key: Any
        api_url: Any
        model: Any
        modstore_adapter: Any

    async def call_llm_api(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs,
    ) -> dict[str, Any] | None:
        """Call the active platform, direct, or legacy LLM provider."""
        started = time.perf_counter()
        try:
            from app.infrastructure.llm.providers.registry import get_active_provider

            provider = get_active_provider(conversation_service=self)
            if provider is None:
                logger.error("❌ 无可用的 LLM Provider（检查 LLM_ROUTING_ORDER / 密钥）")
                return None
            logger.info("🤖 [LLM] provider=%s", provider.provider_id)
            from app.application.agent_orchestrator.context_window_manager import (
                get_context_window_manager,
            )

            compression = await get_context_window_manager().compress(
                messages,
                user_id=str(getattr(getattr(self, "modstore_adapter", None), "user_id", "") or ""),
                provider=provider,
            )
            result = await provider.chat_completion(
                messages=compression.messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            if result:
                latency_ms = (time.perf_counter() - started) * 1000.0
                trace = _api_module()._build_llm_trace(
                    provider, result, latency_ms, compression=compression
                )
                result["_xcagi_trace"] = trace
                self._last_llm_trace = trace
                try:
                    from app.infrastructure.billing.model_usage import record_model_usage

                    record_model_usage(
                        provider_id=trace["provider_id"],
                        provider=trace["provider"],
                        model=trace["model"],
                        prompt_tokens=trace["prompt_tokens"],
                        completion_tokens=trace["completion_tokens"],
                        total_tokens=trace["total_tokens"],
                        cost_units=trace["cost_units"],
                        billing_status=trace["billing_status"],
                        billing_source=trace["billing_source"],
                        source="conversation_service",
                        user_id=str(
                            getattr(getattr(self, "modstore_adapter", None), "user_id", "") or ""
                        ),
                    )
                except RECOVERABLE_ERRORS:
                    logger.debug("record_model_usage failed", exc_info=True)
                try:
                    from app.neuro_bus.application_neuro_bridge import (
                        neuro_notify_ai_model_roundtrip,
                    )

                    neuro_notify_ai_model_roundtrip(
                        model=trace["model"] or trace["provider_id"],
                        latency_ms=latency_ms,
                        token_count=trace["total_tokens"],
                        user_id=str(
                            getattr(getattr(self, "modstore_adapter", None), "user_id", "") or ""
                        ),
                    )
                except RECOVERABLE_ERRORS:
                    pass
                if compression.tokens_saved > 0:
                    try:
                        from app.neuro_bus.application_neuro_bridge import (
                            neuro_notify_ai_model_roundtrip,
                        )

                        neuro_notify_ai_model_roundtrip(
                            model="context-window-manager",
                            latency_ms=compression.compression_latency_ms,
                            token_count=compression.tokens_saved,
                            user_id=str(
                                getattr(getattr(self, "modstore_adapter", None), "user_id", "")
                                or ""
                            ),
                        )
                    except RECOVERABLE_ERRORS:
                        pass
            return result
        except RECOVERABLE_ERRORS as error:
            logger.error("❌ LLM API调用异常: %s", error, exc_info=True)
            return None

    call_deepseek_api = call_llm_api
