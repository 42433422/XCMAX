"""Tests for app.infrastructure.llm.providers.registry — coverage ramp C3.3-b.

Covers the real provider registry API: register / get / resolve (header
override, configured-provider routing, fallback to None when nothing is
configured).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.infrastructure.llm.providers.registry import LLMProviderRegistry


def _provider(provider_id: str, configured: bool) -> SimpleNamespace:
    """A minimal stand-in matching the LLMProvider protocol surface used here."""
    return SimpleNamespace(provider_id=provider_id, is_configured=configured)


class TestLLMProviderRegistry:
    @pytest.fixture(autouse=True)
    def _disable_instrumentation(self, monkeypatch) -> None:
        # 本套件测 registry 注册/路由逻辑本身；关闭装饰层使身份断言聚焦路由边界。
        # 装饰行为由 test_instrumented_provider.py 专门覆盖。
        monkeypatch.setenv("XCAGI_GENAI_TRACE_ENABLED", "0")
        monkeypatch.setenv("XCAGI_GUARDRAILS_ENABLED", "0")

    def test_register_and_get_roundtrip(self) -> None:
        reg = LLMProviderRegistry()
        fake = _provider("fake", configured=True)
        reg.register("fake", fake)
        assert reg.get("fake") is fake

    def test_get_unknown_returns_none(self) -> None:
        reg = LLMProviderRegistry()
        # Unknown id must not raise and must return None (not a fallback object).
        assert reg.get("nonexistent-provider-xyz") is None

    def test_default_providers_present(self) -> None:
        reg = LLMProviderRegistry()
        # The built-in providers are always registered.
        for pid in (
            "deepseek_legacy",
            "openai_compatible",
            "openai_sdk",
            "modstore",
            "xiaomi",
        ):
            assert reg.get(pid) is not None

    def test_xcagi_mimo_provider_routes_to_xiaomi(self, monkeypatch) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_ROUTING_ORDER", raising=False)
        monkeypatch.setenv("XCAGI_LLM_PROVIDER", "mimo")
        monkeypatch.setenv("MIMO_API_KEY", "mimo-test-key")
        reg = LLMProviderRegistry()

        out = reg.resolve()

        assert out is not None
        assert out.provider_id == "xiaomi"
        assert out.is_configured is True

    def test_llm_provider_takes_precedence_over_xcagi_alias(self, monkeypatch) -> None:
        monkeypatch.delenv("LLM_ROUTING_ORDER", raising=False)
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("XCAGI_LLM_PROVIDER", "mimo")
        reg = LLMProviderRegistry()
        for pid in list(reg._providers):
            reg._providers[pid] = _provider(pid, configured=True)

        out = reg.resolve()

        assert out is not None
        assert out.provider_id == "openai_compatible"

    def test_resolve_header_override_when_configured(self) -> None:
        reg = LLMProviderRegistry()
        configured = _provider("custom", configured=True)
        reg.register("custom", configured)
        out = reg.resolve(header_provider="custom")
        assert out is configured

    def test_resolve_header_override_ignored_when_not_configured(self) -> None:
        reg = LLMProviderRegistry()
        # Header points at an unconfigured provider -> must NOT be selected.
        reg.register("custom", _provider("custom", configured=False))
        # Force all built-ins to unconfigured so resolve has nothing to return.
        for pid in list(reg._providers):
            reg._providers[pid] = _provider(pid, configured=False)
        out = reg.resolve(header_provider="custom")
        assert out is None

    def test_resolve_returns_none_when_nothing_configured(self) -> None:
        reg = LLMProviderRegistry()
        for pid in list(reg._providers):
            reg._providers[pid] = _provider(pid, configured=False)
        assert reg.resolve() is None

    def test_resolve_picks_first_configured_in_routing_order(self, monkeypatch) -> None:
        # Pin the routing order so the assertion is env-independent.
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("XCAGI_LLM_PROVIDER", raising=False)
        monkeypatch.setenv(
            "LLM_ROUTING_ORDER", "modstore,openai_compatible,deepseek_legacy,openai_sdk"
        )
        reg = LLMProviderRegistry()
        # Only openai_compatible is configured -> it must be the one resolved.
        for pid in list(reg._providers):
            reg._providers[pid] = _provider(pid, configured=(pid == "openai_compatible"))
        out = reg.resolve()
        assert out is not None
        assert out.provider_id == "openai_compatible"
