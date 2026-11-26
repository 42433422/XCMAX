"""A broken receipt store or transport must not consume future model capacity."""

import asyncio
import json

import anyio
import httpx
import pytest
from starlette.requests import ClientDisconnect, Request

from app.infrastructure.billing import model_usage as ledger
from app.infrastructure.llm import model_admission
from app.infrastructure.xiaox.model_gateway import (
    MODEL_PATH,
    _finish,
    forward_responses,
    response_usage,
)
from tests.test_application.test_xiaox_model_gateway import gateway as gateway
from tests.test_application.test_xiaox_model_gateway import post


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("failure", ["storage", "response", "client"])
def test_failed_model_cleanup_releases_actual_capacity(gateway, monkeypatch, stream, failure):
    client, store, calls, _, app = gateway
    closed = []
    monkeypatch.setattr(model_admission, "_MODEL_INFLIGHT", 0)
    monkeypatch.setattr(model_admission, "_MODEL_BREAKERS", {})
    original_update = store.update

    def update(*args, **kwargs):
        if calls and failure == "storage":
            raise OSError("injected receipt store outage")
        return original_update(*args, **kwargs)

    monkeypatch.setattr(store, "update", update)

    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            if stream:
                payload = {
                    "type": "response.created",
                    "response": {"model": "local-agent", "status": "in_progress"},
                }
                yield f"data: {json.dumps(payload)}\n\n".encode()
            raise httpx.ReadError("injected provider disconnect")

        async def aclose(self):
            closed.append("response")
            if failure == "response":
                raise OSError("injected response close failure")

    class TrackedClient(httpx.AsyncClient):
        async def aclose(self):
            closed.append("client")
            await super().aclose()
            if failure == "client":
                raise OSError("injected client close failure")

    def provider(request):
        calls.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=BrokenStream()
        )

    app.state.xiaox_http_client_factory = lambda **kwargs: TrackedClient(
        transport=httpx.MockTransport(provider), **kwargs
    )
    with pytest.raises(OSError):
        post(client, stream=stream)

    assert closed == ["response", "client"]
    assert model_admission._MODEL_INFLIGHT == 0
    assert len(calls) == 1
    call = next(iter(store.binding.metadata["model_requests"].values()))
    assert call["state"] == ("reserved" if failure == "storage" else "unknown")
    assert store.run.metadata["reserved_cost_units"] > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "storage", "client"])
async def test_request_cancellation_keeps_unknown_usage_and_releases_capacity(
    gateway, monkeypatch, failure
):
    _, store, calls, _, app = gateway
    closed = []
    started = anyio.Event()
    cancellations = []
    monkeypatch.setattr(model_admission, "_MODEL_INFLIGHT", 0)
    monkeypatch.setattr(model_admission, "_MODEL_BREAKERS", {})
    original_update = store.update

    def update(*args, **kwargs):
        if calls and failure == "storage":
            raise OSError("injected receipt store outage")
        return original_update(*args, **kwargs)

    monkeypatch.setattr(store, "update", update)

    class TrackedClient(httpx.AsyncClient):
        async def aclose(self):
            await anyio.sleep(0)
            await super().aclose()
            closed.append("client")
            if failure == "client":
                raise OSError("injected client close failure")

    async def provider(request):
        calls.append(request)
        started.set()
        await anyio.sleep_forever()

    app.state.xiaox_http_client_factory = lambda **kwargs: TrackedClient(
        transport=httpx.MockTransport(provider), **kwargs
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://runtime.test"
    ) as client:

        async def send():
            with anyio.CancelScope() as cancellation:
                cancellations.append(cancellation)
                await client.post(
                    "/api/agent-runtime/xiaox/responses",
                    headers={"authorization": "Bearer model-secret"},
                    json={"model": "local-agent", "input": "test"},
                )

        async with anyio.create_task_group() as requests:
            requests.start_soon(send)
            with anyio.fail_after(10):
                await started.wait()
            cancellations[0].cancel()

    assert cancellations[0].cancelled_caught
    assert len(calls) == 1
    assert closed == ["client"]
    assert model_admission._MODEL_INFLIGHT == 0
    call = next(iter(store.binding.metadata["model_requests"].values()))
    assert call["state"] == ("reserved" if failure == "storage" else "unknown")
    if failure != "storage":
        assert store.binding.metadata["model_reconciliation_required"] is True
    assert store.run.metadata["reserved_cost_units"] > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("failure_at", ["header", "body"])
async def test_stream_send_failure_closes_iterator_and_transports(
    gateway, monkeypatch, cancelled, failure_at
):
    _, store, calls, _, app = gateway
    closed, iterated = [], []
    monkeypatch.setattr(model_admission, "_MODEL_INFLIGHT", 0)
    monkeypatch.setattr(model_admission, "_MODEL_BREAKERS", {})

    class PendingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            iterated.append(True)
            payload = {
                "type": "response.created",
                "response": {"model": "local-agent", "status": "in_progress"},
            }
            yield f"data: {json.dumps(payload)}\n\n".encode()

        async def aclose(self):
            closed.append("response")

    class TrackedClient(httpx.AsyncClient):
        async def aclose(self):
            await super().aclose()
            closed.append("client")

    def provider(request):
        calls.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=PendingStream()
        )

    app.state.xiaox_http_client_factory = lambda **kwargs: TrackedClient(
        transport=httpx.MockTransport(provider), **kwargs
    )
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": MODEL_PATH,
        "raw_path": MODEL_PATH.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"authorization", b"Bearer model-secret"),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 1),
        "server": ("runtime.test", 80),
    }

    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps({"model": "local-agent", "input": "test", "stream": True}).encode(),
            "more_body": False,
        }

    async def send(message):
        target = "http.response.start" if failure_at == "header" else "http.response.body"
        if message["type"] != target:
            return
        if cancelled:
            raise asyncio.CancelledError
        raise OSError("client disconnected during response send")

    response = await forward_responses(Request({**scope, "app": app}, receive))
    with pytest.raises(asyncio.CancelledError if cancelled else ClientDisconnect):
        await response(scope, receive, send)

    assert iterated == ([True] if failure_at == "body" else [])
    assert response.body_iterator.ag_frame is None
    assert closed == ["response", "client"]
    assert model_admission._MODEL_INFLIGHT == 0
    assert len(calls) == 1
    call = next(iter(store.binding.metadata["model_requests"].values()))
    assert call["state"] == "unknown"
    assert store.binding.metadata["model_reconciliation_required"] is True
    assert store.run.metadata["reserved_cost_units"] > 0


@pytest.mark.parametrize("other_state", [None, "reserved", "unknown"])
def test_original_late_usage_receipt_clears_only_resolved_model_hold(gateway, other_state):
    client, store, calls, response, app = gateway
    usage = response.pop("usage")
    assert post(client).status_code == 502
    request_id, original = next(iter(store.binding.metadata["model_requests"].items()))
    assert original["state"] == "unknown"
    if other_state is not None:
        store.binding.metadata["model_requests"]["other-original-request"] = {"state": other_state}
    known = response_usage({"usage": usage})
    for _ in range(2):
        _finish(store, store.run.run_id, request_id, usage=known, usage_key=original["usage_key"])
    assert store.binding.metadata.get("model_reconciliation_required", False) is (
        other_state is not None
    )
    assert len(calls) == len(store.run.llm_calls) == 1
    assert ledger.get_model_wallet("71")["balance_units"] == 98
    assert store.run.metadata["ai_cost_units_total"] == 2
    if other_state is None:
        from app.infrastructure.xiaox.model_gateway import _claim

        _claim(store, "model-secret", app.state.xiaox_model_route, "next-authorized-request")
    else:
        assert post(client).status_code == 409
