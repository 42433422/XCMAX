"""Cross-task stream cleanup must preserve the persisted budget reservation."""

from __future__ import annotations

import asyncio
import importlib
import json
from contextvars import Context

import pytest

from modstore_server import llm_litellm_router as router
from modstore_server import strategic_portfolio_usage as usage
from tests import test_strategic_stream_usage as stream_tests
from tests.test_strategic_stream_usage import _calls, _stream

mandate = stream_tests.mandate
pytestmark = [pytest.mark.filterwarnings(*stream_tests.ROUTER_SDK_WARNINGS)]


def _router_sse(monkeypatch, mandate):
    """Keep the real Router and SDK; pause only the upstream HTTP body."""
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import litellm
    from openai import DefaultAsyncHttpxClient

    transport_api = importlib.import_module(
        DefaultAsyncHttpxClient.__mro__[1].__module__.split(".")[0]
    )
    observed = {
        "waiting": asyncio.Event(),
        "closed": False,
        "cancelled": False,
        "clients": [],
        "responses": [],
        "requests": [],
    }

    class Body(transport_api.AsyncByteStream):
        async def __aiter__(self):
            chunk = {
                "id": "routed-close",
                "created": 0,
                "model": "approved-model",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": "routed"}, "finish_reason": None}],
            }
            yield ("data: " + json.dumps(chunk) + "\n\n").encode()
            observed["waiting"].set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                observed["cancelled"] = True
                raise

        async def aclose(self):
            observed["closed"] = True

    def respond(request):
        observed["requests"].append(request)
        state, calls = _calls(mandate)
        assert len(calls) == 1 and calls[0]["status"] == "pending" and not state["halted"]
        response = transport_api.Response(
            200, stream=Body(), headers={"content-type": "text/event-stream"}, request=request
        )
        observed["responses"].append(response)
        return response

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
        observed["clients"].append(client)
        return client

    monkeypatch.setattr(router, "available", lambda: True)
    monkeypatch.setattr(
        router,
        "_get_router",
        lambda deployments, _fallbacks: litellm.Router(model_list=deployments),
    )
    monkeypatch.setattr(router, "_budgeted_stream_client", metered_client)
    return observed


def _assert_closed_with_hold(observed, mandate):
    state, calls = _calls(mandate)
    assert len(observed["requests"]) == len(observed["clients"]) == len(calls) == 1
    assert observed["closed"] is True
    assert all(response.is_closed for response in observed["responses"])
    assert all(client.is_closed() for client in observed["clients"])
    assert calls[0]["status"] == "unknown" and state["halted"] is True
    assert calls[0]["reserved_tokens"] > 0 and calls[0]["reserved_cost_cents"] > 0
    assert "actual_tokens" not in calls[0] and "accrued_cost_cents" not in calls[0]
    assert usage._CALL.get() is None


@pytest.mark.asyncio
async def test_cross_context_close_does_not_leak_reservation(mandate, monkeypatch):
    observed = _router_sse(monkeypatch, mandate)
    with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
        stream = _stream()
        assert await anext(stream) == {"type": "delta", "delta": "routed"}
        assert usage._CALL.get() is None
    await asyncio.create_task(stream.aclose(), context=Context())
    _assert_closed_with_hold(observed, mandate)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_pending_read", [False, True])
async def test_real_router_closes_owned_client_and_incomplete_response(
    mandate, monkeypatch, cancel_pending_read
):
    observed = _router_sse(monkeypatch, mandate)
    with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
        stream = _stream()
        assert await anext(stream) == {"type": "delta", "delta": "routed"}
        if cancel_pending_read:
            task = asyncio.create_task(anext(stream))
            await asyncio.wait_for(observed["waiting"].wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert observed["cancelled"] is True
        await stream.aclose()
    _assert_closed_with_hold(observed, mandate)
