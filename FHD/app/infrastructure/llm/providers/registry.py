"""LLMProviderRegistry — 按路由顺序与请求头选型。"""

from __future__ import annotations

import os
from typing import Any

from app.infrastructure.llm.providers.base import LLMProvider
from app.infrastructure.llm.providers.deepseek_legacy import DeepSeekLegacyProvider
from app.infrastructure.llm.providers.modstore_provider import ModstoreProvider
from app.infrastructure.llm.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
    XiaomiMimoProvider,
)
from app.infrastructure.llm.providers.openai_sdk_provider import OpenAISdkProvider
from app.utils.operational_errors import RECOVERABLE_ERRORS

_DEFAULT_ORDER = ("modstore", "openai_compatible", "deepseek_legacy", "openai_sdk")
_PROVIDER_ID_ALIASES = {
    "xcauto": "openai_compatible",
    "xcauto-account": "openai_compatible",
    "xcauto-default": "openai_compatible",
    "xiuci": "openai_compatible",
    "xiuci-account": "openai_compatible",
    "openai": "openai_compatible",
    "deepseek": "openai_compatible",
    "mimo": "xiaomi",
    "xiaomi-mimo": "xiaomi",
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
        forced = (
            (os.environ.get("LLM_PROVIDER") or os.environ.get("XCAGI_LLM_PROVIDER") or "")
            .strip()
            .lower()
        )
        if forced:
            return (_normalize_provider_id(forced),)
        return _DEFAULT_ORDER
    return tuple(_normalize_provider_id(p) for p in raw.split(",") if p.strip())


class LLMProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {
            "deepseek_legacy": DeepSeekLegacyProvider(),
            "openai_compatible": OpenAICompatibleProvider(),
            "xiaomi": XiaomiMimoProvider(),
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
    """profile 保留供未来按场景路由；当前与默认顺序一致。"""
    _ = profile
    header_provider = None
    if request is not None:
        headers = getattr(request, "headers", None)
        if headers is not None:
            header_provider = headers.get("X-LLM-Provider") or headers.get("x-llm-provider")
    return get_llm_registry().resolve(
        header_provider=header_provider,
        conversation_service=conversation_service,
    )


def _register_llm_port_source() -> None:
    """把本 registry 组装进 domain 层 ``LLMPort``（infrastructure→domain 为合法方向）。

    callable 经 ``sys.modules`` 晚绑定本模块属性，保证测试对
    ``get_llm_registry`` / ``get_active_provider`` 的 patch 仍然生效。
    """
    import sys

    try:
        from app.domain.neuro.cognition.llm_port import (
            LLMProviderSource,
            set_llm_provider_source,
        )

        _self = sys.modules[__name__]
        set_llm_provider_source(
            LLMProviderSource(
                get_by_id=lambda provider_id: _self.get_llm_registry().get(provider_id),
                get_active=lambda: _self.get_active_provider(),
            )
        )
    except RECOVERABLE_ERRORS:
        pass


_register_llm_port_source()
