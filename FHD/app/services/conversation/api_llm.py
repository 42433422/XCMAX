"""LLM provider routing for the conversation API mixin."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _api_module():
    from app.services.conversation import api

    return api


class ConversationLlmMixin:
    if TYPE_CHECKING:
        _deepseek_async_client: Any
        _deepseek_async_loop: Any
        _last_llm_trace: Any
        api_key: Any
        api_url: Any
        model: Any
        modstore_adapter: Any

    async def _get_deepseek_async_client(self):
        import asyncio

        import httpx

        loop = asyncio.get_running_loop()
        if self._deepseek_async_loop is not loop:
            if self._deepseek_async_client is not None:
                try:
                    await self._deepseek_async_client.aclose()
                except RECOVERABLE_ERRORS:
                    logger.debug("suppressed exception", exc_info=True)
                self._deepseek_async_client = None
            self._deepseek_async_loop = loop
            self._deepseek_async_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=30),
            )
        return self._deepseek_async_client

    def _ensure_modstore_from_session(self) -> None:
        """Populate the MODstore adapter from the active signed-in session."""
        try:
            adapter = getattr(self, "modstore_adapter", None)
            if adapter is not None and getattr(adapter, "auth_token", None):
                return
            session_id = getattr(self, "_active_session_id", None) or ""
            if not session_id:
                return
            from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

            adapter = ModstorePlatformAdapter.from_session(session_id=session_id)
            if adapter is not None and getattr(adapter, "auth_token", None):
                self.modstore_adapter = adapter
                logger.info(
                    "已从 session 自动配置修茈市场平台 Token（%s chars, url=%s）",
                    len(adapter.auth_token),
                    adapter.platform_url,
                )
        except RECOVERABLE_ERRORS as error:
            logger.warning("从 session 配置市场适配器失败: %s", error)

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
            self._ensure_modstore_from_session()
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

    async def _call_deepseek_legacy(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs,
    ) -> dict[str, Any] | None:
        import httpx

        if not self.api_key:
            logger.error("DeepSeek API Key 未配置")
            return None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }
        started = time.perf_counter()
        try:
            client = await self._get_deepseek_async_client()
            response = await client.post(self.api_url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            if result.get("choices") and len(result["choices"]) > 0:
                latency_ms = (time.perf_counter() - started) * 1000.0
                usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
                api = _api_module()
                prompt_tokens = api._coerce_int(usage.get("prompt_tokens"))
                completion_tokens = api._coerce_int(usage.get("completion_tokens"))
                total_tokens = api._coerce_int(usage.get("total_tokens"))
                try:
                    from app.infrastructure.billing.model_usage import (
                        estimate_llm_cost_units,
                        record_model_usage,
                    )

                    cost_units = estimate_llm_cost_units(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                    )
                    record_model_usage(
                        provider_id="deepseek-legacy",
                        provider="deepseek",
                        model=str(self.model or ""),
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        cost_units=cost_units,
                        billing_status="metered" if cost_units else "unmetered",
                        billing_source="estimated_token_units",
                        source="conversation_service.deepseek_legacy",
                    )
                except RECOVERABLE_ERRORS:
                    logger.debug("record_model_usage failed", exc_info=True)
                try:
                    from app.neuro_bus.application_neuro_bridge import (
                        neuro_notify_ai_model_roundtrip,
                    )

                    neuro_notify_ai_model_roundtrip(
                        model=self.model,
                        latency_ms=latency_ms,
                        token_count=total_tokens,
                        user_id="",
                    )
                except RECOVERABLE_ERRORS:
                    logger.debug("neuro_notify_ai_model_roundtrip skipped", exc_info=True)
                return cast("dict[str, Any] | None", result)
            logger.warning("DeepSeek API 返回空响应：%s", result)
            return None
        except httpx.HTTPError as error:
            logger.error("DeepSeek API 请求失败：%s", error)
            return None
        except RECOVERABLE_ERRORS as error:
            logger.error("调用 DeepSeek API 异常：%s", error)
            return None

    call_deepseek_api = call_llm_api
