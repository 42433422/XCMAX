"""Model transports stop oversized raw streams before the SSE parser accumulates them."""

from __future__ import annotations

import gzip
import importlib
import json
from types import SimpleNamespace

import httpx
import pytest

from modstore_server import llm_gateway_contract as contract
from modstore_server import platform_model_transport as transport
from modstore_server import strategic_portfolio_usage as usage
from tests import test_strategic_stream_usage as stream_tests

mandate = stream_tests.mandate


def _wire(monkeypatch, chunks, *, encoding=None):
    seen = {"requests": [], "clients": [], "read": 0, "closed": 0}
    client_type = httpx.AsyncClient

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            for chunk in chunks:
                seen["read"] += 1
                yield chunk

        async def aclose(self):
            seen["closed"] += 1

    def respond(request):
        usage.require_call_reservation()
        seen["requests"].append(request)
        headers = {"content-type": "text/event-stream"}
        if encoding:
            headers["content-encoding"] = encoding
        return httpx.Response(200, stream=Body(), headers=headers, request=request)

    def client(**kwargs):
        result = client_type(transport=httpx.MockTransport(respond), **kwargs)
        seen["clients"].append(result)
        return result

    monkeypatch.setattr(
        transport,
        "httpx",
        SimpleNamespace(
            AsyncClient=client, Response=httpx.Response, RequestError=httpx.RequestError
        ),
    )
    return seen


def _frames():
    return [
        ("data: " + json.dumps(frame, ensure_ascii=False) + "\n\n").encode()
        for frame in (
            {"choices": [{"delta": {"content": "真实结果"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {"usage": {"prompt_tokens": 10, "completion_tokens": 3}},
        )
    ] + [b"data: [DONE]\n\n"]


def _assert_unknown(mandate, seen):
    state, calls = stream_tests._calls(mandate)
    assert len(calls) == len(seen["requests"]) == 1
    assert state["halted"] and calls[0]["status"] == "unknown"
    assert calls[0]["reserved_tokens"] > 0 and calls[0]["reserved_cost_cents"] > 0
    assert "actual_tokens" not in calls[0]
    assert seen["closed"] == 1 and all(client.is_closed for client in seen["clients"])


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk", [b"data: " + b"x" * 58, b":" + b"x" * 61 + b"\n\n"])
async def test_native_stream_bounds_unfinished_sse_and_comment_flood(mandate, monkeypatch, chunk):
    monkeypatch.setattr(transport, "MAX_MODEL_STREAM_BYTES", 128, raising=False)
    seen = _wire(monkeypatch, [chunk] * 4)
    with (
        usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]),
        pytest.raises(contract.StreamLimitError, match="byte limit"),
    ):
        _ = [event async for event in stream_tests._stream()]
    assert seen["read"] == 3
    _assert_unknown(mandate, seen)


@pytest.mark.asyncio
async def test_native_stream_rejects_compression_before_reading(mandate, monkeypatch):
    seen = _wire(monkeypatch, [gzip.compress(b"".join(_frames()))], encoding="gzip")
    with (
        usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]),
        pytest.raises(contract.StreamLimitError, match="encoding"),
    ):
        _ = [event async for event in stream_tests._stream()]
    assert seen["read"] == 0
    assert seen["requests"][0].headers["accept-encoding"] == "identity"
    _assert_unknown(mandate, seen)


@pytest.mark.asyncio
async def test_native_stream_event_budget_stops_before_later_receipt(mandate, monkeypatch):
    monkeypatch.setattr(contract, "MAX_STREAM_EVENTS", 2)
    seen = _wire(monkeypatch, _frames())
    with (
        usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]),
        pytest.raises(contract.StreamLimitError, match="event limit"),
    ):
        _ = [event async for event in stream_tests._stream()]
    assert seen["read"] == 3
    _assert_unknown(mandate, seen)


@pytest.mark.asyncio
async def test_native_stream_accepts_exact_wire_boundary_with_original_usage(mandate, monkeypatch):
    chunks = _frames()
    monkeypatch.setattr(transport, "MAX_MODEL_STREAM_BYTES", sum(map(len, chunks)), raising=False)
    monkeypatch.setattr(contract, "MAX_STREAM_EVENTS", 3)
    seen = _wire(monkeypatch, chunks)
    with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
        events = [event async for event in stream_tests._stream()]
    assert [event["type"] for event in events] == ["delta", "finish", "usage"]
    assert events[0]["delta"] == "真实结果"
    state, calls = stream_tests._calls(mandate)
    assert not state["halted"] and calls[0]["status"] == "settled"
    assert calls[0]["actual_tokens"] == 13 and len(seen["requests"]) == 1
    assert seen["requests"][0].headers["accept-encoding"] == "identity"
    assert seen["read"] == 4 and seen["closed"] == 1
    assert all(client.is_closed for client in seen["clients"])


@pytest.mark.asyncio
@pytest.mark.parametrize("package", ["httpx", "httpx2"])
async def test_stream_bound_preserves_existing_client_hooks_headers_and_close(package):
    api = importlib.import_module(package)
    seen = {"hooks": [], "closed": 0, "requests": []}

    class Body(api.AsyncByteStream):
        async def __aiter__(self):
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            seen["closed"] += 1

    async def on_request(request):
        seen["hooks"].append("request")
        seen["requests"].append(request)

    async def on_response(response):
        seen["hooks"].append("response")
        assert response.headers["x-upstream"] == "original"

    client = api.AsyncClient(
        transport=api.MockTransport(
            lambda request: api.Response(
                200, stream=Body(), headers={"x-upstream": "original"}, request=request
            )
        ),
        event_hooks={"request": [on_request], "response": [on_response]},
        headers={"x-client": "original"},
    )
    assert transport.bound_model_stream_client(client) is client
    assert transport.bound_model_stream_client(client) is client
    async with client:
        async with client.stream("POST", "https://model.test/stream") as response:
            assert (
                b"".join([chunk async for chunk in response.aiter_bytes()]) == b"data: [DONE]\n\n"
            )
        await response.aclose()
    assert seen["hooks"] == ["request", "response"]
    assert seen["closed"] == 1 and client.is_closed
    assert seen["requests"][0].headers["accept-encoding"] == "identity"
    assert seen["requests"][0].headers["x-client"] == "original"
