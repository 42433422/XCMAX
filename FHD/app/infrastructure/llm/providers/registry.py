"""LLMProviderRegistry — 按路由顺序与请求头选型。"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.infrastructure.llm.providers.base import LLMProvider
from app.infrastructure.llm.providers.deepseek_legacy import DeepSeekLegacyProvider
from app.infrastructure.llm.providers.modstore_provider import ModstoreProvider
from app.infrastructure.llm.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.infrastructure.llm.providers.openai_sdk_provider import OpenAISdkProvider
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_DEFAULT_ORDER = ("modstore", "openai_compatible", "deepseek_legacy", "openai_sdk")
_PROVIDER_ID_ALIASES = {
    "xcauto": "openai_compatible",
    "xcauto-account": "openai_compatible",
    "xcauto-default": "openai_compatible",
    "xiuci": "openai_compatible",
    "xiuci-account": "openai_compatible",
    "openai": "openai_compatible",
    "deepseek": "openai_compatible",
}


def _maybe_instrument(provider: LLMProvider | None) -> LLMProvider | None:
    """返回前包 InstrumentedProvider（装饰层自身异常时原样返回，fail-open）。"""
    if provider is None:
        return None
    try:
        from app.infrastructure.llm.instrumented_provider import wrap_provider

        return wrap_provider(provider)
    except RECOVERABLE_ERRORS:
        return provider


def _normalize_provider_id(provider_id: str | None) -> str:
    text = str(provider_id or "").strip().lower()
    return _PROVIDER_ID_ALIASES.get(text, text)


def _routing_order() -> tuple[str, ...]:
    raw = (os.environ.get("LLM_ROUTING_ORDER") or "").strip()
    if not raw:
        forced = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
        if forced:
            return (_normalize_provider_id(forced),)
        return _DEFAULT_ORDER
    return tuple(_normalize_provider_id(p) for p in raw.split(",") if p.strip())


class LLMProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {
            "deepseek_legacy": DeepSeekLegacyProvider(),
            "openai_compatible": OpenAICompatibleProvider(),
            "openai_sdk": OpenAISdkProvider(),
            "modstore": ModstoreProvider(),
        }

    def register(self, provider_id: str, provider: LLMProvider) -> None:
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> LLMProvider | None:
        return _maybe_instrument(self._providers.get(_normalize_provider_id(provider_id)))

    def resolve(
        self,
        *,
        header_provider: str | None = None,
        conversation_service: Any | None = None,
    ) -> LLMProvider | None:
        if header_provider:
            p = self._providers.get(_normalize_provider_id(header_provider))
            if p and p.is_configured:
                return _maybe_instrument(p)

        if conversation_service is not None:
            mod = getattr(conversation_service, "modstore_adapter", None)
            if mod is not None:
                self._providers["modstore"] = ModstoreProvider(mod)
            llm = getattr(conversation_service, "llm_adapter", None)
            if llm is not None:
                self._providers["openai_compatible"] = OpenAICompatibleProvider(llm)
            legacy_key = getattr(conversation_service, "api_key", None)
            if legacy_key:
                self._providers["deepseek_legacy"] = DeepSeekLegacyProvider(
                    api_key=str(legacy_key),
                    api_url=getattr(conversation_service, "api_url", None),
                    model=getattr(conversation_service, "model", None),
                )

        for pid in _routing_order():
            provider = self._providers.get(pid)
            if provider and provider.is_configured:
                return _maybe_instrument(provider)
        return None


_registry: LLMProviderRegistry | None = None


def get_llm_registry() -> LLMProviderRegistry:
    global _registry
    if _registry is None:
        _registry = LLMProviderRegistry()
    return _registry


def get_active_provider(
    *,
    request: Any | None = None,
    conversation_service: Any | None = None,
    profile: str | None = None,
) -> LLMProvider | None:
    """根据 profile 选择 LLM provider。

    向后兼容策略：

    - ``profile=None``：走原逻辑（header override → routing order fallback），
      行为与未引入 ModelRouter 前完全一致。
    - ``profile="small"`` / ``"large"`` / ``"reasoning"`` / ``"fast"``：调用
      :class:`app.infrastructure.llm.model_router.ModelRouter` 决策模型 tier，
      并把 :class:`RoutingDecision` 挂载到返回的 provider 上
      （属性名 ``_routing_decision``），调用方可读取该属性覆盖实际请求体中的
      ``model`` 字段。``ModelRouter.enabled=False`` 时退化为 ``profile=None``
      行为（不挂载 decision）。

    Note:
        本函数不替换 provider 实例——所有内置 provider 共享同一 ``base_url``，
        仅 ``model`` 字段不同；调用方（如 ``OpenAICompatibleProvider.chat_completion``）
        应读取 ``_routing_decision.model_name`` 覆盖请求体。
    """
    header_provider = None
    if request is not None:
        headers = getattr(request, "headers", None)
        if headers is not None:
            header_provider = headers.get("X-LLM-Provider") or headers.get("x-llm-provider")
    provider = get_llm_registry().resolve(
        header_provider=header_provider,
        conversation_service=conversation_service,
    )
    if provider is None:
        return None

    # profile=None 保持原行为
    if profile is None:
        return provider

    # 落地 profile：交给 ModelRouter 决策，并把 decision 挂载到 provider 上
    try:
        from app.infrastructure.llm.model_router import (
            RoutingRequest,
            get_model_router,
        )

        router = get_model_router()
        if not router.enabled:
            # 路由未启用 → 不挂 decision，调用方走 provider 默认 model
            return provider

        # 从 request 对象 best-effort 抽取 message（不强制要求结构）
        message = ""
        if request is not None:
            for attr in ("message", "body", "query", "text"):
                try:
                    val = getattr(request, attr, None)
                except RECOVERABLE_ERRORS:
                    val = None
                if isinstance(val, str) and val:
                    message = val
                    break

        decision = router.route(
            RoutingRequest(message=message, profile=str(profile).strip().lower() or None)
        )
        try:
            provider._routing_decision = decision  # type: ignore[attr-defined]
        except RECOVERABLE_ERRORS:
            # 装饰层 / 不可变对象等场景下挂载失败不阻断返回 provider
            logger.debug("attach _routing_decision to provider failed", exc_info=True)
    except RECOVERABLE_ERRORS:
        logger.debug("ModelRouter 落地 profile 失败，回退默认 provider", exc_info=True)
    return provider
