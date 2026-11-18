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
@pytest.mark.parametrize("fallback", [False, True])
async def test_chat_normalizes_router_response(monkeypatch, fallback):
    class FakeRouter:
        async def acompletion(self, **_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="routed", reasoning_content=None)
                    )
                ],
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                model="deepseek-chat" if fallback else "gpt-4o-mini",
                _hidden_params={
                    "model_id": "modstore-fallback-0" if fallback else "modstore-primary",
                    "additional_headers": {"x-litellm-attempted-fallbacks": int(fallback)},
                },
            )

    monkeypatch.setattr(router_mod, "available", lambda: True)
    monkeypatch.setattr(router_mod, "_get_router", lambda *_a, **_k: FakeRouter())

    out = await router_mod.chat(
        "openai",
        api_key="sk",
        base_url=None,
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        fallbacks=[{"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-backup"}],
    )

    assert out is not None
    assert out["ok"] is True
    assert out["content"] == "routed"
    assert out["router"] == "litellm"
    assert out["provider"] == ("deepseek" if fallback else "openai")
    assert out["model"] == ("deepseek-chat" if fallback else "gpt-4o-mini")
    assert out["fallback_used"] is fallback


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

    captured = {}

    async def fake_events(*_args, **kwargs):
        captured.update(kwargs)
        yield {"type": "delta", "delta": "routed"}

    monkeypatch.setattr(router_mod, "stream_events", fake_events)
    tools = [{"type": "function", "function": {"name": "get_weather"}}]

    out = [
        event
        async for event in llm_chat_proxy.chat_dispatch_stream(
            "openai",
            api_key="sk",
            base_url=None,
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            tools=tools,
            tool_choice="auto",
        )
    ]

    assert {"type": "delta", "delta": "routed"} in out
    assert captured["tools"] == tools
    assert captured["tool_choice"] == "auto"


@pytest.mark.parametrize("object_fragments", [False, True])
def test_stream_tool_fragments_complete_once_in_index_order(object_fragments):
    pending = {}

    def chunk(calls, finish=None):
        if object_fragments:
            calls = [
                SimpleNamespace(**{**call, "function": SimpleNamespace(**call["function"])})
                for call in calls
            ]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=calls), finish_reason=finish
                )
            ]
        )

    first = chunk(
        [
            {"index": 1, "id": "call-b", "function": {"name": "second", "arguments": '{"b":'}},
            {"index": 0, "id": "call-a", "function": {"name": "weather", "arguments": '{"city":'}},
        ]
    )
    assert router_mod._stream_delta_events(first, pending) == []
    last = chunk(
        [
            {"index": 0, "function": {"arguments": '"北京"}'}},
            {"index": 1, "function": {"arguments": "2}"}},
        ],
        "tool_calls",
    )
    events = router_mod._stream_delta_events(last, pending)
    calls = events[0]["choices"][0]["delta"]["tool_calls"]
    assert [call["id"] for call in calls] == ["call-a", "call-b"]
    assert calls[0]["function"] == {"name": "weather", "arguments": '{"city":"北京"}'}
    assert calls[1]["function"] == {"name": "second", "arguments": '{"b":2}'}
    assert pending == {}
    assert not any(
        e["type"] == "toolcall"
        for e in router_mod._stream_delta_events(chunk([], "tool_calls"), pending)
    )


def test_managed_minimax_keeps_saved_endpoint_over_environment(monkeypatch):
    monkeypatch.setenv("MINIMAX_ANTHROPIC_BASE_URL", "https://old-gateway.invalid/anthropic")
    key = _platform_key("minimax", "sk-cp-token-plan")
    key = PlatformApiKey(
        str(key), {**key.configuration, "base_url": "https://saved-gateway.invalid/anthropic"}
    )
    dep = router_mod._deployment("primary", "minimax", "MiniMax-M2.7", key, None)
    assert dep["litellm_params"]["api_base"] == "https://saved-gateway.invalid/anthropic"


def test_usage_conversion_does_not_swallow_programming_assertions():
    class BrokenUsage:
        def model_dump(self):
            raise AssertionError("implementation bug")

    with pytest.raises(AssertionError, match="implementation bug"):
        router_mod._usage_dict(SimpleNamespace(usage=BrokenUsage()))


def test_cache_credential_fingerprint_is_keyed_and_rotation_sensitive(monkeypatch):
    monkeypatch.setattr(router_mod, "_CACHE_FINGERPRINT_KEY", b"a" * 32)
    first = router_mod._key_fingerprint("dummy-credential-one")
    assert first == router_mod._key_fingerprint("dummy-credential-one")
    assert first != router_mod._key_fingerprint("dummy-credential-two")
    assert "dummy-credential" not in first
    monkeypatch.setattr(router_mod, "_CACHE_FINGERPRINT_KEY", b"b" * 32)
    assert first != router_mod._key_fingerprint("dummy-credential-one")


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["stored", "env"])
async def test_platform_credentials_never_enter_unpinned_router(source, monkeypatch):
    def forbidden():
        raise AssertionError("platform transport must not depend on optional Router availability")

    monkeypatch.setattr(router_mod, "available", forbidden)
    key = _platform_key("openai")
    key = PlatformApiKey(str(key), {**key.configuration, "source": source})
    assert router_mod._build_specs("openai", "gpt", key, None, None) is None
    assert (
        router_mod._build_specs(
            "openai",
            "gpt",
            "byok",
            None,
            [{"provider": "openai", "model": "backup", "api_key": key}],
        )
        is None
    )
    for api_key, fallbacks in (
        (key, None),
        ("byok", [{"provider": "openai", "model": "backup", "api_key": key}]),
    ):
        args = dict(api_key=api_key, base_url=None, model="gpt", messages=[], fallbacks=fallbacks)
        assert await router_mod.chat("openai", **args) is None
        assert router_mod.stream_events("openai", **args) is None


@pytest.mark.asyncio
async def test_mapped_upstream_error_remains_normalized(monkeypatch):
    openai = pytest.importorskip("openai")
    import httpx

    class Router:
        async def acompletion(self, **kwargs):
            raise openai.APIConnectionError(
                request=httpx.Request("POST", "https://example.invalid")
            )

    monkeypatch.setattr(router_mod, "available", lambda: True)
    monkeypatch.setattr(router_mod, "_get_router", lambda *a: Router())
    result = await router_mod.chat(
        "openai", api_key="dummy", base_url=None, model="gpt", messages=[]
    )
    assert result["ok"] is False
    assert result["error"]
