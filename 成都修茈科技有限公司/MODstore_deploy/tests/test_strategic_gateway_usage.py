"""Meter actual Router/direct HTTP requests through the shared LiteLLM proxy."""

from __future__ import annotations

import importlib
import json

import httpx
import pytest
from sqlalchemy import select

import modstore_server.llm_chat_proxy as llm_chat_proxy
import modstore_server.llm_key_resolver as llm_key_resolver
import modstore_server.llm_litellm_router as router
import modstore_server.platform_model_transport as platform_model_transport
import modstore_server.strategic_portfolio_usage as usage
import tests.test_strategic_company_resources as company_fixtures
import tests.test_strategic_stream_usage as stream_fixtures
from modstore_server.db.llm_chat import LlmClientRequest

mandate = stream_fixtures.mandate
real_router_runtime = stream_fixtures.real_router_runtime
_calls = stream_fixtures._calls
configured = company_fixtures.configured
database = company_fixtures.database


def _response(stream, model):
    common = {"id": "gateway-receipt", "created": 0, "model": model}
    measured = {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}
    if not stream:
        return json.dumps(
            {
                **common,
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "actual reply"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": measured,
                # A JSON assertion cannot replace the native HTTP receipt.
                "gateway_attempts_verified": True,
            }
        )
    frames = [
        {"choices": [{"index": 0, "delta": {"content": "actual reply"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": measured, "gateway_attempts_verified": True},
    ]
    return (
        "".join(
            "data: " + json.dumps({**common, "object": "chat.completion.chunk", **frame}) + "\n\n"
            for frame in frames
        )
        + "data: [DONE]\n\n"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mandate", ["litellm"], indirect=True)
@pytest.mark.parametrize("route", ["direct", "router"])
@pytest.mark.parametrize("stream", [False, True], ids=["completion", "stream"])
@pytest.mark.parametrize(
    "receipt", ["single", "missing", "retry", "fallback", "malformed", "alias"]
)
async def test_gateway_real_wire_preserves_unknown_attempts(
    mandate, monkeypatch, route, stream, receipt, real_router_runtime
):
    headers = {"x-litellm-attempted-retries": "0", "x-litellm-attempted-fallbacks": "0"}
    if receipt == "missing":
        headers.pop("x-litellm-attempted-retries")
    if receipt == "retry":
        headers["x-litellm-attempted-retries"] = "1"
    if receipt == "fallback":
        headers["x-litellm-attempted-fallbacks"] = "1"
    if receipt == "malformed":
        headers["x-litellm-attempted-retries"] = "not-a-count"
    model = "different-upstream-model" if receipt == "alias" else "approved-model"
    payload = _response(stream, model)
    wire, clients = [], []

    def responder(transport):
        def respond(request):
            wire.append(json.loads(request.content))
            assert _calls(mandate)[1][0]["status"] == "pending"
            return transport.Response(
                200,
                text=payload,
                headers={
                    **headers,
                    "content-type": "text/event-stream" if stream else "application/json",
                },
            )

        return respond

    if route == "direct":
        client_type = httpx.AsyncClient

        def client_factory(**kwargs):
            client = client_type(transport=httpx.MockTransport(responder(httpx)), **kwargs)
            clients.append(client)
            return client

        monkeypatch.setattr(platform_model_transport.httpx, "AsyncClient", client_factory)
    else:
        from openai import DefaultAsyncHttpxClient

        transport = importlib.import_module(
            DefaultAsyncHttpxClient.__mro__[1].__module__.split(".")[0]
        )
        original_client = router._budgeted_stream_client

        def metered_client(*args, **kwargs):
            client = original_client(
                *args,
                **kwargs,
                http_client=DefaultAsyncHttpxClient(
                    transport=transport.MockTransport(responder(transport)), trust_env=False
                ),
            )
            clients.append(client)
            return client

        def actual_router(deployments, fallbacks):
            actual = real_router_runtime.Router(model_list=deployments, num_retries=3)

            class Proxy:
                async def acompletion(self, **kwargs):
                    # Never let a regression perform an unmocked network call.
                    assert kwargs.get("client") is not None
                    return await actual.acompletion(**kwargs)

            return Proxy()

        monkeypatch.setattr(router, "available", lambda: True)
        monkeypatch.setattr(router, "_get_router", actual_router)
        monkeypatch.setattr(router, "_budgeted_stream_client", metered_client)

    kwargs = {
        "api_key": "platform-test-key",
        "base_url": None,
        "model": "approved-model",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 20,
    }
    with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
        if stream:
            result = [
                event async for event in llm_chat_proxy.chat_dispatch_stream("litellm", **kwargs)
            ]
        else:
            result = await llm_chat_proxy.chat_dispatch("litellm", **kwargs)
    state, calls = _calls(mandate)
    assert len(wire) == len(calls) == 1, result
    assert wire[0]["num_retries"] == 0
    assert wire[0]["disable_fallbacks"] is True
    assert wire[0]["model"] == "approved-model"
    assert "extra_body" not in wire[0] and "gateway_attempts_verified" not in wire[0]
    assert all(
        client.is_closed() if callable(client.is_closed) else client.is_closed for client in clients
    )
    known = receipt == "single"
    assert calls[0]["status"] == ("settled" if known else "unknown"), result
    assert state["halted"] is not known, result
    if known:
        assert calls[0]["actual_tokens"] == 6
    else:
        assert "actual_tokens" not in calls[0]
        assert calls[0]["reserved_tokens"] > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("verified", [False, True], ids=["unknown", "single"])
async def test_gateway_planning_receipt_settles_original_company_and_call_rows(
    configured, monkeypatch, verified
):
    identity = company_fixtures.budget(
        configured,
        tariffs=[
            {
                "provider": "litellm",
                "model": "approved-model",
                "input_cents_per_million": 100,
                "output_cents_per_million": 100,
                "source": "approved-test-tariff",
            }
        ],
    )
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _: "platform-test-key")
    monkeypatch.setattr(llm_key_resolver, "platform_base_url", lambda _: None)
    monkeypatch.setattr(router, "available", lambda: False)
    wire = []

    def respond(request):
        wire.append(json.loads(request.content))
        assert company_fixtures.totals(identity)["slots"] == 1
        assert company_fixtures.totals(identity)["held"]["tokens"] > 0
        with configured() as session:
            assert session.scalars(select(LlmClientRequest.state)).all() == [
                "processing",
                "processing",
            ]
        return httpx.Response(
            200,
            text=_response(False, "approved-model"),
            headers=(
                {"x-litellm-attempted-retries": "0", "x-litellm-attempted-fallbacks": "0"}
                if verified
                else {}
            ),
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        platform_model_transport.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    admission = await usage.planning_admission("litellm", "approved-model", owner_user_id=7)
    assert admission["company_budget_id"] == identity
    with usage.planning_usage_scope(7, admission) as context:
        await llm_chat_proxy.chat_dispatch(
            "litellm",
            api_key="platform-test-key",
            base_url=None,
            model="approved-model",
            messages=[{"role": "user", "content": "next approved objective"}],
            max_tokens=20,
        )
    assert len(wire) == 1 and wire[0]["num_retries"] == 0
    assert wire[0]["disable_fallbacks"] is True
    assert context["receipts"][0]["status"] == ("settled" if verified else "unknown")
    totals = company_fixtures.totals(identity)
    assert totals["spent"]["tokens"] == (6 if verified else 0)
    assert (totals["held"]["tokens"] > 0) is not verified
    assert totals["slots"] == (0 if verified else 1)
    with configured() as session:
        assert session.scalars(select(LlmClientRequest.state)).all() == [
            "completed" if verified else "unknown",
            "completed" if verified else "unknown",
        ]
