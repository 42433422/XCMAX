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


@pytest.mark.asyncio
@pytest.mark.parametrize("already_wrapped", [False, True])
async def test_explicit_owner_provider_is_traced_once_without_rerouting(
    monkeypatch, already_wrapped
):
    from app.infrastructure.llm import instrumented_provider as ip
    from app.neuro_bus.tracer import TraceContext

    provider = _Provider("owner-model")
    spans = []
    monkeypatch.setenv("XCAGI_GENAI_TRACE_ENABLED", "1")
    monkeypatch.setattr(
        ip.InstrumentedProvider, "_persist", staticmethod(lambda span: spans.append(span.to_dict()))
    )

    def forbidden(**kwargs):
        pytest.fail("A bound provider must not be resolved again")

    monkeypatch.setattr(invoke, "get_active_provider", forbidden)
    with TraceContext("a" * 32, "b" * 16, request_id="owner-request"):
        bound = ip.InstrumentedProvider(provider) if already_wrapped else provider
        await invoke.chat_completion_openai_format([], provider=bound, model="authorized")
    assert len(provider.calls) == len(spans) == 1
    assert spans[0]["trace_id"] == "a" * 32
    assert spans[0]["attributes"]["request_id"] == "owner-request"
    assert spans[0]["attributes"]["gen_ai.request.model"] == "authorized"


@pytest.mark.asyncio
async def test_legacy_transport_uncertainty_is_not_an_empty_success(monkeypatch):
    import httpx

    from app.infrastructure.llm.providers import deepseek_legacy as legacy

    error = httpx.ReadTimeout("receipt lost")
    calls = []

    def lose_response(request):
        calls.append(request)
        raise error

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        legacy.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(lose_response), **kwargs),
    )
    provider = legacy.DeepSeekLegacyProvider(
        api_key="synthetic-fixture", api_url="http://localhost/v1", model="authorized"
    )
    with pytest.raises(httpx.ReadTimeout) as caught:
        await provider.chat_completion([])
    assert caught.value is error and len(calls) == 1
