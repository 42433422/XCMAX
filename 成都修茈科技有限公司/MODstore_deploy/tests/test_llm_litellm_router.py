"""LiteLLM Router 适配层与 chat_dispatch 接入测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modstore_server import llm_litellm_router as router_mod
from modstore_server import llm_router_config
from modstore_server.platform_model_config import PlatformApiKey


@pytest.fixture(autouse=True)
def _reset_router_state():
    router_mod.reset_cache()
    llm_router_config.reset_cache()
    yield
    router_mod.reset_cache()
    llm_router_config.reset_cache()


def _platform_key(provider: str, key: str = "sk-platform") -> PlatformApiKey:
    return PlatformApiKey(
        key,
        {
            "provider": provider,
            "base_url": "https://example.invalid/v1",
            "model": "",
            "display_name": "",
            "revision": "r1",
            "source": "stored",
        },
    )


def test_deployment_maps_openai_compatible_provider():
    dep = router_mod._deployment("primary", "deepseek", "deepseek-chat", "sk-test", None)

    assert dep is not None
    assert dep["litellm_params"]["model"] == "openai/deepseek-chat"
    assert dep["litellm_params"]["api_base"].endswith("/v1")


def test_deployment_maps_minimax_token_plan_to_anthropic():
    dep = router_mod._deployment("primary", "minimax", "MiniMax-M2.7", "sk-cp-token-plan", None)

    assert dep is not None
    assert dep["litellm_params"]["model"] == "anthropic/MiniMax-M2.7"
    assert dep["litellm_params"]["api_base"].endswith("/anthropic")


def test_deployment_rejects_cross_provider_platform_key():
    with pytest.raises(ValueError):
        router_mod._deployment("primary", "openai", "gpt-4o-mini", _platform_key("deepseek"), None)


def test_router_passes_mature_fallback_and_cooldown_params(monkeypatch):
    captured: dict[str, object] = {}

    class FakeRouter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(router_mod, "_load_litellm", lambda: SimpleNamespace(Router=FakeRouter))
    router_mod.reset_cache()
    deployments = [
        router_mod._deployment("modstore-primary", "openai", "gpt-4o-mini", "sk", None),
        router_mod._deployment("modstore-fallback-0", "deepseek", "deepseek-chat", "sk2", None),
    ]

    router_mod._get_router(deployments, ["modstore-fallback-0"])

    assert captured["fallbacks"] == [{"modstore-primary": ["modstore-fallback-0"]}]
    assert "num_retries" in captured
    assert "cooldown_time" in captured
    assert captured["routing_strategy"]


def test_env_platform_fallbacks_builds_chain(monkeypatch):
    monkeypatch.setenv(
        "MODSTORE_LLM_ROUTER_PLATFORM_FALLBACKS",
        "minimax/MiniMax-M2.7,deepseek/deepseek-chat,openai/gpt-4o-mini",
    )
    monkeypatch.setattr(router_mod, "platform_api_key", lambda provider: f"sk-{provider}")
    monkeypatch.setattr(
        router_mod, "platform_base_url", lambda provider: "https://example.invalid/v1"
    )

    rows = router_mod.env_platform_fallbacks("openai", "gpt-4o-mini")

    assert [(row["provider"], row["model"]) for row in rows] == [
        ("minimax", "MiniMax-M2.7"),
        ("deepseek", "deepseek-chat"),
    ]


def test_key_pool_only_applies_to_platform_keys(monkeypatch):
    monkeypatch.setenv("MODSTORE_LLM_KEY_POOL_OPENAI", "sk-a,sk-b")

    platform_pool = router_mod._key_pool("openai", _platform_key("openai", "sk-a"), None)
    assert [str(key) for key in platform_pool] == ["sk-b"]
    assert router_mod._key_pool("openai", "sk-user-byok", None) == []


def test_normalize_response_marks_fallback():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello", reasoning_content=None))],
        usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        model="deepseek-chat",
        _hidden_params={"additional_headers": {"x-litellm-attempted-fallbacks": "1"}},
    )

    out = router_mod._normalize_response(
        response, provider="openai", model="gpt-4o-mini", forbid_reasoning_fallback=False
    )

    assert out["ok"] is True
    assert out["content"] == "hello"
    assert out["fallback_used"] is True
    assert out["usage"]["total_tokens"] == 3


def test_normalize_response_rejects_reasoning_only_when_forbidden():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content="", reasoning_content="thinking"))
        ],
        usage={},
        model="deepseek-reasoner",
        _hidden_params={},
    )

    out = router_mod._normalize_response(
        response, provider="deepseek", model="deepseek-reasoner", forbid_reasoning_fallback=True
    )

    assert out["ok"] is False
    assert out["reasoning_trace"] == "thinking"


@pytest.mark.asyncio
async def test_chat_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(router_mod, "available", lambda: False)

    out = await router_mod.chat(
        "openai",
        api_key="sk",
        base_url=None,
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert out is None


@pytest.mark.asyncio
async def test_chat_normalizes_router_response(monkeypatch):
    class FakeRouter:
        async def acompletion(self, **_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="routed", reasoning_content=None)
                    )
                ],
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                model="gpt-4o-mini",
                _hidden_params={},
            )

    monkeypatch.setattr(router_mod, "available", lambda: True)
    monkeypatch.setattr(router_mod, "_get_router", lambda *_a, **_k: FakeRouter())

    out = await router_mod.chat(
        "openai",
        api_key="sk",
        base_url=None,
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert out is not None
    assert out["ok"] is True
    assert out["content"] == "routed"
    assert out["router"] == "litellm"


@pytest.mark.asyncio
async def test_stream_events_translate_chunks(monkeypatch):
    class FakeRouter:
        async def acompletion(self, **_kwargs):
            async def gen():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="he", tool_calls=None), finish_reason=None
                        )
                    ],
                    usage=None,
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=None, finish_reason="stop"),
                    ],
                    usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                )

            return gen()

    monkeypatch.setattr(router_mod, "available", lambda: True)
    monkeypatch.setattr(router_mod, "_get_router", lambda *_a, **_k: FakeRouter())

    events = router_mod.stream_events(
        "openai",
        api_key="sk",
        base_url=None,
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert events is not None
    out = [event async for event in events]

    assert {"type": "delta", "delta": "he"} in out
    assert any(event.get("type") == "usage" for event in out)


@pytest.mark.asyncio
async def test_chat_dispatch_prefers_litellm_router(monkeypatch):
    from modstore_server.llm_chat_proxy import chat_dispatch

    async def fake_router_chat(*_args, **_kwargs):
        return {"ok": True, "content": "router", "usage": {}}

    monkeypatch.setattr(router_mod, "chat", fake_router_chat)

    out = await chat_dispatch(
        "openai",
        api_key="sk",
        base_url=None,
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert out["content"] == "router"


@pytest.mark.asyncio
async def test_chat_dispatch_degrades_to_legacy_adapter(monkeypatch):
    from modstore_server import llm_chat_proxy

    async def fake_router_chat(*_args, **_kwargs):
        return None

    async def fake_openai(base_url, api_key, model, messages, **_kwargs):
        return {"ok": True, "content": "legacy", "usage": {}}

    monkeypatch.setattr(router_mod, "chat", fake_router_chat)
    monkeypatch.setattr(llm_chat_proxy, "chat_openai_compatible", fake_openai)

    out = await llm_chat_proxy.chat_dispatch(
        "openai",
        api_key="sk",
        base_url=None,
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert out["content"] == "legacy"


@pytest.mark.asyncio
async def test_chat_dispatch_rejects_cross_provider_platform_key(monkeypatch):
    from modstore_server.llm_chat_proxy import chat_dispatch

    async def fake_router_chat(*_args, **_kwargs):
        raise AssertionError("不应对跨供应商平台 Key 调用 Router")

    monkeypatch.setattr(router_mod, "chat", fake_router_chat)

    out = await chat_dispatch(
        "openai",
        api_key=_platform_key("deepseek"),
        base_url=None,
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert out["ok"] is False
    assert "平台密钥" in out["error"]


@pytest.mark.asyncio
async def test_chat_dispatch_stream_prefers_litellm_router(monkeypatch):
    from modstore_server import llm_chat_proxy

    async def fake_events(*_args, **_kwargs):
        yield {"type": "delta", "delta": "routed"}

    monkeypatch.setattr(router_mod, "stream_events", fake_events)

    out = [
        event
        async for event in llm_chat_proxy.chat_dispatch_stream(
            "openai",
            api_key="sk",
            base_url=None,
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
        )
    ]

    assert {"type": "delta", "delta": "routed"} in out
