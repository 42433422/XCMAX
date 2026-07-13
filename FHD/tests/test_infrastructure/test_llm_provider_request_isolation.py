"""The global provider registry must never retain request-bound credentials."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from app.infrastructure.llm.providers import registry as registry_module


def test_concurrent_request_provider_resolution_does_not_cross_tokens(monkeypatch) -> None:
    registry = registry_module.LLMProviderRegistry()
    barrier = threading.Barrier(2)

    def _synchronized_order():
        barrier.wait(timeout=5)
        return ("modstore",)

    monkeypatch.setattr(registry_module, "_routing_order", _synchronized_order)

    def _resolve(token: str) -> str:
        service = SimpleNamespace(
            modstore_adapter=SimpleNamespace(auth_token=token),
            llm_adapter=None,
            api_key="",
        )
        provider = registry.resolve(conversation_service=service)
        assert provider is not None
        return provider._adapter.auth_token

    original_global_provider = registry._providers["modstore"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_resolve, "token-a")
        second = pool.submit(_resolve, "token-b")
        assert {first.result(timeout=10), second.result(timeout=10)} == {
            "token-a",
            "token-b",
        }

    assert registry._providers["modstore"] is original_global_provider


def test_request_provider_override_is_not_reused_by_no_token_service(monkeypatch) -> None:
    registry = registry_module.LLMProviderRegistry()
    monkeypatch.setattr(registry_module, "_routing_order", lambda: ("modstore",))

    token_service = SimpleNamespace(
        modstore_adapter=SimpleNamespace(auth_token="private-token"),
        llm_adapter=None,
        api_key="",
    )
    provider = registry.resolve(conversation_service=token_service)
    assert provider is not None
    assert provider._adapter.auth_token == "private-token"

    no_token_service = SimpleNamespace(
        modstore_adapter=None,
        llm_adapter=None,
        api_key="",
    )
    assert registry.resolve(conversation_service=no_token_service) is None
