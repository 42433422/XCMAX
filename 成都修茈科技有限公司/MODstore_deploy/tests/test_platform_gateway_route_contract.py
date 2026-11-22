"""Gateway defaults and health probes must describe the route actually used."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from modstore_server import (
    llm_api,
    llm_catalog,
    llm_chat_proxy,
    llm_key_resolver,
    llm_runtime_route,
)
from modstore_server.services import llm
from tests.platform_model_support import database as database
from tests.platform_model_support import isolated as isolated
from tests.platform_model_support import save


@pytest.mark.asyncio
@pytest.mark.parametrize("gateway_models", [["xcmax-doubao-code"], []])
async def test_bench_and_chat_share_gateway_catalog_default(database, monkeypatch, gateway_models):
    save("openai", model="legacy-pinned")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "gateway-test-key")

    async def catalog(_uid, provider, **_kwargs):
        models = gateway_models if provider == "litellm" else ["legacy-pinned"]
        return {"models": models, "runtime_models": models}

    monkeypatch.setattr(llm_catalog, "get_models_for_credentials", catalog)
    chat = await llm_api.resolve_default_llm_route(database, 0, platform_only=True)

    assert llm.resolve_platform_bench_llm() == (chat["provider"], chat["model"])


def test_bench_gateway_without_chat_models_does_not_invent_a_model(database, monkeypatch):
    monkeypatch.setenv("LITELLM_MASTER_KEY", "gateway-test-key")
    monkeypatch.setattr(
        llm_catalog,
        "get_models_for_credentials",
        AsyncMock(return_value={"models": ["text-embedding-3-small"], "runtime_models": []}),
    )

    assert llm.resolve_platform_bench_llm() == (None, None)


@pytest.mark.parametrize("runtime_override", [False, True])
def test_explicit_employee_routes_still_override_gateway(database, monkeypatch, runtime_override):
    save("openai", model="legacy-pinned")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "gateway-test-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BENCH_PROVIDER", "deepseek")
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BENCH_MODEL", "deepseek-reasoner")
    if runtime_override:
        llm_runtime_route.commit_runtime_route(
            "openai", "explicit-runtime", actor="test", reason="operator route"
        )
    catalog = AsyncMock(side_effect=AssertionError("explicit route must not load defaults"))
    monkeypatch.setattr(llm_catalog, "get_models_for_credentials", catalog)

    expected = (
        ("openai", "explicit-runtime") if runtime_override else ("deepseek", "deepseek-reasoner")
    )
    assert llm.resolve_platform_bench_llm() == expected
    catalog.assert_not_awaited()


def test_without_gateway_saved_default_keeps_legacy_precedence(database, monkeypatch):
    save("openai", model="legacy-pinned")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BENCH_PROVIDER", "deepseek")
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BENCH_MODEL", "deepseek-reasoner")

    assert llm.resolve_platform_bench_llm() == ("openai", "legacy-pinned")


@pytest.fixture
def probe_dispatch(monkeypatch):
    monkeypatch.setenv("MODSTORE_EMPLOYEE_PLATFORM_FALLBACK_ENABLED", "1")
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _provider: "test-key")
    monkeypatch.setattr(llm_key_resolver, "platform_base_url", lambda _provider: None)
    dispatch = AsyncMock()
    monkeypatch.setattr(llm_chat_proxy, "chat_dispatch", dispatch)
    return dispatch


@pytest.mark.asyncio
async def test_probe_primary_failure_cannot_be_hidden_by_healthy_fallback(probe_dispatch):
    async def primary_or_fallback(_provider, **kwargs):
        if kwargs.get("fallback_provider"):
            return {"ok": True, "content": "OK", "_fallback_used": True}
        return {"ok": False, "status": 503, "error": "gateway unavailable"}

    probe_dispatch.side_effect = primary_or_fallback
    health = await llm_runtime_route.probe_runtime_route("litellm", "xcmax-kimi-code")

    assert health["ok"] is False
    assert health["status"] == 503
    assert "fallback_provider" not in probe_dispatch.call_args.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route_metadata",
    [
        {"_fallback_used": True},
        {"fallback_used": True},
        {"provider": "minimax", "model": "MiniMax-M2.7"},
        {"_fallback_provider": "minimax", "_fallback_model": "MiniMax-M2.7"},
    ],
)
async def test_probe_rejects_success_from_another_route(probe_dispatch, route_metadata):
    probe_dispatch.return_value = {"ok": True, "content": "OK", **route_metadata}

    health = await llm_runtime_route.probe_runtime_route("litellm", "xcmax-kimi-code")

    assert health["ok"] is False
    assert health["status"] == "probe_route_mismatch"


@pytest.mark.asyncio
async def test_probe_accepts_primary_response_with_resolved_gateway_model(probe_dispatch):
    probe_dispatch.return_value = {
        "ok": True,
        "content": "OK",
        "provider": "litellm",
        "model": "upstream-model-version",
        "fallback_used": False,
    }

    health = await llm_runtime_route.probe_runtime_route("litellm", "xcmax-kimi-code")

    assert health["ok"] is True
    assert health["error"] == ""
