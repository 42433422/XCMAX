"""LLMProviderRegistry — 按路由顺序与请求头选型。"""

from __future__ import annotations

import os
from typing import Any

from app.infrastructure.llm.providers.base import LLMProvider
from app.infrastructure.llm.providers.deepseek_legacy import DeepSeekLegacyProvider
from app.infrastructure.llm.providers.modstore_provider import ModstoreProvider
from app.infrastructure.llm.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.infrastructure.llm.providers.openai_sdk_provider import OpenAISdkProvider
from app.utils.operational_errors import RECOVERABLE_ERRORS

_DEFAULT_ORDER = ("modstore", "openai_compatible", "deepseek_legacy", "openai_sdk")
_BACKGROUND_PROFILES = frozenset({"background", "neuro", "autonomy"})
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


def _provider_is_configured(provider: LLMProvider | None) -> bool:
    """Treat a broken optional provider probe as unavailable, not fatal."""
    if provider is None:
        return False
    try:
        return bool(provider.is_configured)
    except RECOVERABLE_ERRORS:
        return False


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


def _coerce_internal_user_id(value: str | int | None) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def _resolve_background_market_provider(
    *,
    session_id: str | None = None,
    user_id: str | int | None = None,
) -> LLMProvider | None:
    """Resolve a persisted, owner-scoped market provider for background work.

    Request handlers normally supply a conversation service and its session
    adapter.  Neuro/autonomy workers run outside HTTP, so after a desktop
    restart they need to resume the persisted market binding explicitly.

    Global "newest session" fallback is deliberately limited to the
    single-user desktop runtime.  Server deployments must pass a session/user
    context or configure ``XCAGI_BACKGROUND_LLM_USER_ID``.
    """
    try:
        from app.fastapi_routes.market_account import latest_session_id_with_market_token
        from app.services.conversation.modstore_adapter import ModstorePlatformAdapter
        from app.utils.deployment import is_desktop_mode

        effective_user_id = _coerce_internal_user_id(user_id)
        if effective_user_id is None:
            effective_user_id = _coerce_internal_user_id(
                os.environ.get("XCAGI_BACKGROUND_LLM_USER_ID")
            )

        effective_session_id = str(session_id or "").strip()
        if not effective_session_id and (is_desktop_mode() or effective_user_id is not None):
            effective_session_id = latest_session_id_with_market_token(
                user_id=effective_user_id
            )
        if not effective_session_id:
            return None

        adapter = ModstorePlatformAdapter.from_session(session_id=effective_session_id)
        if not str(getattr(adapter, "auth_token", "") or "").strip():
            return None
        if not str(getattr(adapter, "platform_url", "") or "").strip():
            return None
        return ModstoreProvider(
            adapter,
            session_id=effective_session_id,
            credential_scope="desktop_session" if is_desktop_mode() else "session",
        )
    except RECOVERABLE_ERRORS:
        return None


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
        # Request/session adapters are local to this resolution.  Never retain
        # one user's token inside the process-global registry.
        providers = dict(self._providers)

        if conversation_service is not None:
            mod = getattr(conversation_service, "modstore_adapter", None)
            if mod is not None:
                providers["modstore"] = ModstoreProvider(mod)
            llm = getattr(conversation_service, "llm_adapter", None)
            if llm is not None:
                providers["openai_compatible"] = OpenAICompatibleProvider(llm)
            legacy_key = getattr(conversation_service, "api_key", None)
            if legacy_key:
                providers["deepseek_legacy"] = DeepSeekLegacyProvider(
                    api_key=str(legacy_key),
                    api_url=getattr(conversation_service, "api_url", None),
                    model=getattr(conversation_service, "model", None),
                )

        if header_provider:
            p = providers.get(_normalize_provider_id(header_provider))
            if _provider_is_configured(p):
                return _maybe_instrument(p)

        for pid in _routing_order():
            provider = providers.get(pid)
            if _provider_is_configured(provider):
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
    session_id: str | None = None,
    user_id: str | int | None = None,
) -> LLMProvider | None:
    """Resolve a provider without mixing request and background credentials."""
    header_provider = None
    if request is not None:
        headers = getattr(request, "headers", None)
        if headers is not None:
            header_provider = headers.get("X-LLM-Provider") or headers.get("x-llm-provider")
    provider = get_llm_registry().resolve(
        header_provider=header_provider,
        conversation_service=conversation_service,
    )
    if provider is not None:
        return provider
    if str(profile or "").strip().lower() in _BACKGROUND_PROFILES:
        return _maybe_instrument(
            _resolve_background_market_provider(session_id=session_id, user_id=user_id)
        )
    return None


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
                get_active_for_context=lambda session_id, user_id: _self.get_active_provider(
                    profile="neuro",
                    session_id=session_id,
                    user_id=user_id,
                ),
            )
        )
    except RECOVERABLE_ERRORS:
        pass


_register_llm_port_source()
