from __future__ import annotations

from typing import Any

import pytest

from app.infrastructure.llm import invoke


class _Provider:
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.calls: list[dict[str, Any]] = []

    async def chat_completion(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return {"choices": [{"message": {"content": "{}"}}]}


@pytest.mark.asyncio
async def test_disable_reasoning_maps_to_xiaomi_thinking_parameter(monkeypatch) -> None:
    provider = _Provider("xiaomi")
    monkeypatch.setattr(invoke, "get_active_provider", lambda **_kwargs: provider)

    await invoke.chat_completion_openai_format(
        [{"role": "user", "content": "return json"}],
        reasoning_enabled=False,
    )

    assert provider.calls[0]["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_disable_reasoning_is_not_forwarded_to_other_providers(monkeypatch) -> None:
    provider = _Provider("openai_compatible")
    monkeypatch.setattr(invoke, "get_active_provider", lambda **_kwargs: provider)

    await invoke.chat_completion_openai_format(
        [{"role": "user", "content": "return json"}],
        reasoning_enabled=False,
    )

    assert "thinking" not in provider.calls[0]
