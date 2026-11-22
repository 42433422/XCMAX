"""Gateway fallback receipts survive the actual Router / SDK stream wrappers."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import httpx
import pytest

from modstore_server import llm_chat_proxy, llm_key_resolver
from modstore_server import llm_litellm_router as router
from modstore_server import platform_model_transport
from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_usage as usage
from modstore_server.platform_model_config import PlatformApiKey
from tests import test_strategic_stream_usage as stream_tests

GATEWAY_MODEL = "xcmax-kimi-code"
real_router_runtime = stream_tests.real_router_runtime


@pytest.fixture
def gateway_mandate(tmp_path, monkeypatch, request):
    create_proposal = portfolio.create_portfolio_proposal

    def gateway_proposal(**kwargs):
        kwargs["limits"]["tariffs"][0].update(provider="litellm", model=GATEWAY_MODEL)
        return create_proposal(**kwargs)

    monkeypatch.setattr(portfolio, "create_portfolio_proposal", gateway_proposal)
    yield from stream_tests.mandate.__wrapped__(tmp_path, monkeypatch, request)


@pytest.mark.parametrize(
    "headers,used,count",
    [
        ({}, False, 0),
        ({"X-LiteLLM-Attempted-Fallbacks": "0"}, False, 0),
        ({"x-litellm-attempted-fallbacks": "1"}, True, 1),
        ({"LLM_Provider-X-LiteLLM-Attempted-Fallbacks": "2"}, True, 2),
        (
            {
                "x-litellm-attempted-fallbacks": 0,
                "llm_provider-x-litellm-attempted-fallbacks": "1",
            },
            True,
            1,
        ),
        ({"llm_provider-x-litellm-attempted-fallbacks": "unknown"}, True, None),
        ({"llm_provider-x-litellm-attempted-fallbacks": "-1"}, True, None),
        ({"llm_provider-x-litellm-attempted-fallbacks": None}, True, None),
    ],
)
def test_fallback_receipts_preserve_both_router_layers(headers, used, count):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="measured"))],
        usage={"prompt_tokens": 4, "completion_tokens": 2},
        model="returned-upstream-model",
        _hidden_params={"additional_headers": headers},
    )
    result = router._normalize_response(
        response, provider="litellm", model=GATEWAY_MODEL, forbid_reasoning_fallback=False
    )
    assert result["fallback_used"] is used
    assert result["fallback_count"] == count
    assert result["model"] == "returned-upstream-model"


@pytest.mark.asyncio
# LiteLLM 1.109.3 inspects Pydantic instance metadata while checking empty
# stream deltas. Scope its two deprecated accesses to this actual SDK contract.
@pytest.mark.filterwarnings(
    r"ignore:^Accessing the 'model_(computed_)?fields' attribute on the instance is deprecated\."
    r":pydantic.PydanticDeprecatedSince211"
    r":^litellm\.litellm_core_utils\.model_response_utils$"
)
@pytest.mark.parametrize(
    "fallback_header,receipt,unknown",
    [
        (None, "reported", True),
        ("0", "reported", False),
        ("1", "reported", True),
        ("unreported", "reported", True),
        ("0", "absent", True),
        ("0", "partial", True),
    ],
)
async def test_real_gateway_stream_keeps_unverified_attempts_reserved(
    gateway_mandate, monkeypatch, fallback_header, receipt, unknown, real_router_runtime
):
    from openai import DefaultAsyncHttpxClient

    litellm = real_router_runtime

    transport_api = importlib.import_module(
        DefaultAsyncHttpxClient.__mro__[1].__module__.split(".")[0]
    )
    wire_requests, router_requests, clients = [], [], []
    events = [
        {"choices": [{"index": 0, "delta": {"content": "routed"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    if receipt != "absent":
        events.append(
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 4 if receipt == "reported" else None,
                    "completion_tokens": 2,
                    "total_tokens": 6 if receipt == "reported" else None,
                },
            }
        )
    wire = (
        "".join(
            "data: "
            + json.dumps(
                {
                    "id": "gateway-receipt",
                    "created": 0,
                    "model": GATEWAY_MODEL,
                    "object": "chat.completion.chunk",
                    **event,
                }
            )
            + "\n\n"
            for event in events
        )
        + "data: [DONE]\n\n"
    )

    def respond(request):
        assert request.headers["authorization"] == (
            f"Bearer {llm_key_resolver.platform_api_key('litellm')}"
        )
        wire_requests.append(json.loads(request.content))
        assert stream_tests._calls(gateway_mandate)[1][0]["status"] == "pending"
        headers = {
            "content-type": "text/event-stream",
            "X-LiteLLM-Attempted-Retries": "0",
        }
        if fallback_header is not None:
            headers["X-LiteLLM-Attempted-Fallbacks"] = fallback_header
        return transport_api.Response(200, text=wire, headers=headers)

    original_client = router._budgeted_stream_client

    def metered_client(*args):
        client = original_client(
            *args,
            http_client=DefaultAsyncHttpxClient(
                transport=transport_api.MockTransport(respond),
                follow_redirects=False,
                trust_env=False,
            ),
        )
        clients.append(client)
        return client

    def actual_router(deployments, _fallbacks):
        actual = litellm.Router(model_list=deployments, num_retries=3)

        class Proxy:
            async def acompletion(self, **kwargs):
                router_requests.append(kwargs)
                response = await actual.acompletion(**kwargs)
                assert type(response).__name__ == "FallbackStreamWrapper"
                return response

        return Proxy()

    monkeypatch.setattr(router, "available", lambda: True)
    monkeypatch.setattr(router, "_get_router", actual_router)
    monkeypatch.setattr(router, "_budgeted_stream_client", metered_client)
    with usage.portfolio_usage_scope(gateway_mandate[0], "a", gateway_mandate[1]["lease_token"]):
        received = [
            event
            async for event in llm_chat_proxy.chat_dispatch_stream(
                "litellm",
                api_key="platform-test-key",
                base_url=None,
                model=GATEWAY_MODEL,
                messages=[{"role": "user", "content": "hello"}],
                max_tokens=20,
            )
        ]
    state, calls = stream_tests._calls(gateway_mandate)
    assert len(wire_requests) == len(router_requests) == len(calls) == 1, received
    assert router_requests[0]["num_retries"] == router_requests[0]["max_retries"] == 0
    assert router_requests[0]["disable_fallbacks"] is True
    assert router_requests[0]["enable_mid_stream_fallback_continuation"] is False
    assert wire_requests[0]["model"] == GATEWAY_MODEL
    assert wire_requests[0]["stream_options"] == {"include_usage": True}
    assert all(client.is_closed() for client in clients)
    assert state["halted"] is unknown, received
    assert calls[0]["status"] == ("unknown" if unknown else "settled"), received
    if unknown:
        assert calls[0]["reserved_tokens"] > 0 and calls[0]["reserved_cost_cents"] > 0
        assert "actual_tokens" not in calls[0] and "accrued_cost_cents" not in calls[0]
    else:
        assert calls[0]["actual_tokens"] == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "fallback_header,response_model,unknown",
    [
        (None, GATEWAY_MODEL, True),
        ("0", GATEWAY_MODEL, False),
        ("1", GATEWAY_MODEL, True),
        ("unreported", GATEWAY_MODEL, True),
        ("0", "different-upstream-model", True),
    ],
)
async def test_platform_key_gateway_receipts_keep_actual_route_identity(
    gateway_mandate, monkeypatch, stream, fallback_header, response_model, unknown
):
    key = PlatformApiKey(
        "platform-test-key",
        {
            "provider": "litellm",
            "base_url": "http://127.0.0.1:14000/v1",
            "model": "",
            "display_name": "Gateway",
            "revision": "r1",
            "source": "environment",
        },
    )
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _provider: key)
    monkeypatch.setattr(
        llm_key_resolver, "platform_base_url", lambda _provider: key.configuration["base_url"]
    )
    monkeypatch.setattr(router, "available", lambda: True)
    requests, clients = [], []

    def respond(request):
        requests.append(json.loads(request.content))
        assert stream_tests._calls(gateway_mandate)[1][0]["status"] == "pending"
        assert request.headers["authorization"] == "Bearer platform-test-key"
        headers = {"X-LiteLLM-Attempted-Retries": "0"}
        if fallback_header is not None:
            headers["X-LiteLLM-Attempted-Fallbacks"] = fallback_header
        measured = {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}
        if stream:
            frames = [
                {"model": response_model, "choices": [{"delta": {"content": "routed"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                {"usage": measured},
            ]
            wire = "".join("data: " + json.dumps(row) + "\n\n" for row in frames)
            return httpx.Response(200, text=wire + "data: [DONE]\n\n", headers=headers)
        return httpx.Response(
            200,
            json={
                "model": response_model,
                "choices": [{"message": {"content": "routed"}}],
                "usage": measured,
            },
            headers=headers,
        )

    original_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        client = original_client(
            *args,
            **{
                **kwargs,
                "transport": httpx.MockTransport(respond),
                "follow_redirects": False,
                "trust_env": False,
            },
        )
        clients.append(client)
        return client

    # Keep PlatformApiKey routing and the real pinned transport facade; only
    # replace the network boundary. The Router must not strip the key snapshot.
    monkeypatch.setattr(platform_model_transport.httpx, "AsyncClient", client_factory)
    with usage.portfolio_usage_scope(gateway_mandate[0], "a", gateway_mandate[1]["lease_token"]):
        kwargs = {
            "api_key": key,
            "base_url": None,
            "model": GATEWAY_MODEL,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 20,
        }
        if stream:
            events = [
                event async for event in llm_chat_proxy.chat_dispatch_stream("litellm", **kwargs)
            ]
            result = next(event for event in events if event["type"] == "usage")
        else:
            result = await llm_chat_proxy.chat_dispatch("litellm", **kwargs)
            assert result["ok"] is True
    state, calls = stream_tests._calls(gateway_mandate)
    assert len(requests) == len(clients) == len(calls) == 1
    assert all(client.is_closed for client in clients)
    assert requests[0]["model"] == GATEWAY_MODEL
    assert result["provider"] == "litellm" and result["model"] == response_model
    assert result["fallback_used"] is (fallback_header in {"1", "unreported"})
    assert result["fallback_count"] == (
        None if fallback_header == "unreported" else int(fallback_header or "0")
    )
    assert state["halted"] is unknown
    assert calls[0]["status"] == ("unknown" if unknown else "settled")
    if unknown:
        assert calls[0]["reserved_tokens"] > 0 and calls[0]["reserved_cost_cents"] > 0
        assert "actual_tokens" not in calls[0] and "accrued_cost_cents" not in calls[0]
    else:
        assert calls[0]["actual_tokens"] == 6
