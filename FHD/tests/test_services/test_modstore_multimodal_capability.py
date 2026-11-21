from __future__ import annotations

import json

import httpx
import pytest

from app.domain.shared_services.conversation import modstore_adapter
from app.domain.shared_services.conversation.modstore_adapter import _catalog_model_vision_support


def test_catalog_marks_regular_llm_as_text_only() -> None:
    catalog = {
        "providers": [
            {
                "provider": "xiaomi",
                "models_detailed": [
                    {
                        "id": "mimo-v2.5-pro",
                        "category": "llm",
                        "capability": {"effective_category": "llm"},
                    }
                ],
            }
        ]
    }
    assert _catalog_model_vision_support(catalog, "xiaomi", "mimo-v2.5-pro") is False


def test_catalog_allows_vlm_and_known_vision_name() -> None:
    catalog = {
        "providers": [
            {
                "provider": "openai",
                "models_detailed": [{"id": "visual-model", "category": "vlm"}],
            }
        ]
    }
    assert _catalog_model_vision_support(catalog, "openai", "visual-model") is True
    assert _catalog_model_vision_support({}, "openai", "gpt-4o") is True


@pytest.mark.parametrize("vision_ack", [True, False])
def test_desktop_sends_native_image_only_after_account_vision_route(monkeypatch, vision_ack):
    requests = []
    adapter = modstore_adapter.ModstorePlatformAdapter(
        platform_url="https://example.test",
        auth_token="account-token",
    )
    adapter._use_account_default = True
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}
    messages = [{"role": "user", "content": [image]}]

    def respond(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "provider": "openai",
                    "model": "vision-model",
                    "route_token": "pinned-token",
                    "operation": "vision" if vision_ack else "chat",
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='data: {"content":"native image"}\n\ndata: [DONE]\n\n',
        )

    monkeypatch.setattr(
        modstore_adapter,
        "_httpx_sync_client",
        lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(respond),
            **kwargs,
        ),
    )
    if not vision_ack:
        with pytest.raises(ValueError):
            adapter.chat_completion_sync(messages)
        assert len(requests) == 1
        return
    result = adapter.chat_completion_sync(messages)
    assert result["choices"][0]["message"]["content"] == "native image"
    assert requests[0].url.params["operation"] == "vision"
    assert requests[1].url.path == "/api/llm/chat/stream"
    data = json.loads(requests[1].content)
    assert data["messages"] == messages
    assert data["model"] == "vision-model"
    assert data["route_token"] == "pinned-token"
    assert data["allow_failover"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [402, 429])
async def test_confirmed_image_rejection_keeps_its_definitive_status(monkeypatch, status):
    from fastapi import HTTPException

    adapter = modstore_adapter.ModstorePlatformAdapter(
        platform_url="https://example.test", auth_token="account-token"
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": False, "status": status})
        )
    ) as client:

        async def get_client():
            return client

        monkeypatch.setattr(adapter, "_get_client", get_client)
        with pytest.raises(HTTPException) as exc:
            await adapter.generate_image({"prompt": "test", "client_request_id": "image-test-key"})
        assert exc.value.status_code == status
