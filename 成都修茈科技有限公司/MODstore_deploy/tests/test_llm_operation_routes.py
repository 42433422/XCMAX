from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from modstore_server import (
    llm_chat_proxy,
    llm_litellm_router,
    llm_operation_routes as routes,
)


@pytest.fixture
def catalog(monkeypatch):
    catalog = AsyncMock(
        return_value={
            "models_detailed": [
                {"id": "text", "capabilities": {"operations": ["chat"]}},
                {
                    "id": "custom/vision",
                    "capabilities": {"operations": ["chat", "vision"]},
                },
                {
                    "id": "custom/illustrator",
                    "capabilities": {"operations": ["image_generation"]},
                },
            ]
        }
    )
    monkeypatch.setattr(routes, "get_models_for_credentials", catalog)
    return catalog


@pytest.mark.asyncio
async def test_declared_capabilities_select_by_operation(catalog):
    assert (
        await routes.select_operation_model(1, "openai", "vision", "key", None)
        == "custom/vision"
    )
    assert (
        await routes.select_operation_model(
            1, "openai", "image_generation", "key", None
        )
        == "custom/illustrator"
    )
    assert not await routes.select_operation_model(
        1, "openai", "image_generation", "key", None, model="text"
    )


@pytest.mark.asyncio
async def test_byok_cannot_fall_through_to_paid_platform(monkeypatch):
    monkeypatch.setattr(routes, "read_state", lambda: {"default_provider": "openai"})
    monkeypatch.setattr(routes, "KNOWN_PROVIDERS", ("openai", "openrouter"))
    monkeypatch.setattr(
        routes,
        "resolve_credentials",
        lambda _, uid, p, **kw: (
            ("platform-key", None, "platform")
            if p == "openai"
            else ("account-key", None, "user_override")
        ),
    )
    select = AsyncMock(return_value=None)
    monkeypatch.setattr(routes, "select_operation_model", select)
    with pytest.raises(HTTPException) as err:
        await routes.resolve_operation_route(None, 1, "image_generation")
    assert err.value.detail["code"] == "NO_CAPABLE_MODEL"
    assert [call.args[1] for call in select.call_args_list] == ["openrouter"]


@pytest.mark.asyncio
async def test_vision_probe_uses_image_and_requires_expected_result(
    monkeypatch, catalog
):
    monkeypatch.setattr(routes, "read_state", lambda: {})
    monkeypatch.setattr(
        routes, "resolve_credentials", lambda *a, **kw: ("secret", None, "platform")
    )
    chat = AsyncMock(return_value={"ok": True, "content": "OK"})
    monkeypatch.setattr(llm_chat_proxy, "chat_dispatch", chat)
    result = await routes.probe_operation(None, 1, "openai", "custom/vision", "vision")
    assert result["ok"] is False
    assert chat.call_args.kwargs["messages"][0]["content"][1]["image_url"][
        "url"
    ].startswith("data:image/png;base64,")
    chat.return_value["content"] = "Red."
    result = await routes.probe_operation(None, 1, "openai", "custom/vision", "vision")
    assert result["ok"] is True
    assert "secret" not in repr(result)


def test_model_context_names_request_budget_without_credentials(monkeypatch):
    monkeypatch.setattr(
        llm_litellm_router, "model_limits", lambda *a: {"max_output_tokens": 4096}
    )
    route = routes.OperationRoute(
        "openai", "gpt-4o", "platform", "secret", "https://private"
    )
    msgs = [{"role": "user", "content": "hello"}]
    upstream = routes.model_runtime_messages(
        route, msgs, 512, SimpleNamespace(enabled=True, amount="0.10")
    )
    context = upstream[0]["content"]
    assert '"request_max_output_tokens": 512' in context
    assert '"model_max_output_tokens": 4096' in context
    assert '"reserved_cny": "0.10"' in context
    assert '"provider_remaining_quota_percent": null' in context
    assert "secret" not in context and "https://private" not in context
    assert upstream[1:] == msgs


def test_registry_describes_mimo_multimodal_without_promoting_it_to_asr(monkeypatch):
    monkeypatch.setattr(
        llm_litellm_router,
        "model_registry_entry",
        lambda *_: {
            "mode": "chat",
            "supports_vision": True,
            "supports_audio_input": True,
            "max_input_tokens": 1048576,
            "max_output_tokens": 131072,
        },
    )
    profile = routes.discover_model_capabilities("xiaomi", "mimo-v2.6-flash")
    assert profile["source"] == "litellm_registry"
    assert profile["category"] == "vlm"
    assert routes.supports_operation("xiaomi", "mimo-v2.6-flash", "vision")
    assert not routes.supports_operation("xiaomi", "mimo-v2.6-flash", "speech_to_text")
