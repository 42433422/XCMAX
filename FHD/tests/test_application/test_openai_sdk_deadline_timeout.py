"""Use the installed official SDK with real response ownership and cancellation."""

from __future__ import annotations

import importlib
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from openai import DefaultHttpxClient, OpenAI, RateLimitError, Timeout

from app.application.tool_execution_deadline import invocation_deadline
from app.infrastructure.llm.providers import openai_sdk_provider as sdk


def test_sdk_timeout_preserves_transport_family_and_stricter_phase_limits():
    configured = httpx.Timeout(30, connect=1)
    configured.read = httpx.Timeout(5)
    result = sdk._bounded_sdk_timeout(configured, 10)
    assert isinstance(result, Timeout)
    assert result.as_dict() == {"connect": 1.0, "read": 5.0, "write": 10.0, "pool": 10.0}
    assert set(sdk._bounded_sdk_timeout(Timeout(None), 2).as_dict().values()) == {2}


def test_unknown_timeout_phase_cannot_silently_disable_the_deadline():
    configured = Timeout(30)
    configured.read = object()
    with pytest.raises(ValueError, match="invalid read timeout"):
        sdk._bounded_sdk_timeout(configured, 10)


@pytest.fixture
def native_sdk(monkeypatch):
    from app.infrastructure.llm import client

    # The public SDK chooses its transport family; tests work with either lock.
    transport = importlib.import_module(DefaultHttpxClient.__mro__[1].__module__.split(".")[0])
    state = SimpleNamespace(posts=[], status=200, body=None, before_headers=None, workers=[])

    def respond(request):
        state.posts.append(request)
        if state.before_headers is not None:
            state.before_headers()
        if state.status != 200:
            return transport.Response(state.status, json={"error": {"message": "limited"}})
        if state.body is not None:
            return transport.Response(200, stream=state.body)
        if json.loads(request.content).get("stream"):
            return transport.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
            )
        return transport.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "model": "fixed",
            },
        )

    state.client = OpenAI(
        api_key="synthetic-fixture",
        base_url="https://model.invalid/v1",
        http_client=DefaultHttpxClient(transport=transport.MockTransport(respond)),
        timeout=Timeout(120, connect=0.01, pool=None),
        max_retries=2,
    )
    _ = state.client.chat.completions.with_streaming_response
    monkeypatch.setattr(client, "get_llm_client", lambda: state.client)
    monkeypatch.setattr(client, "require_api_key", lambda: None)
    original_worker = sdk.StreamWorker

    def worker(*args, **kwargs):
        value = original_worker(*args, **kwargs)
        state.workers.append(value)
        return value

    monkeypatch.setattr(sdk, "StreamWorker", worker)
    state.provider, state.transport = sdk.OpenAISdkProvider(), transport

    async def invoke(streaming):
        if streaming:
            return [
                chunk async for chunk in state.provider.stream_chat_completion([], model="fixed")
            ]
        return await state.provider.chat_completion([], model="fixed")

    state.invoke = invoke
    yield state
    state.client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_sdk_deadline_bounds_phases_and_disables_hidden_retries(native_sdk, streaming):
    state = native_sdk
    state.status = 429
    with invocation_deadline(time.monotonic() + 2), pytest.raises(RateLimitError):
        await state.invoke(streaming)
    assert len(state.posts) == 1
    limits = state.posts[0].extensions["timeout"]
    assert limits["connect"] == 0.01
    assert all(0 < value <= 2 for value in limits.values())
    assert state.client.timeout == Timeout(120, connect=0.01, pool=None)
    assert state.client.max_retries == 2 and not state.client.is_closed()
    # Borrowed options stay unchanged; a later call cannot reopen an SDK retry loop.
    with pytest.raises(RateLimitError):
        await state.invoke(streaming)
    assert len(state.posts) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_deadline_closes_only_owned_body_and_does_not_replay_partial_output(
    native_sdk, streaming
):
    state = native_sdk
    entered, closed = threading.Event(), threading.Event()

    class Body(state.transport.SyncByteStream):
        def __iter__(self):
            if streaming:
                yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            entered.set()
            closed.wait(2)
            raise state.transport.ReadError("owned response closed")

        def close(self):
            closed.set()

    state.body = Body()
    started = time.monotonic()
    try:
        with invocation_deadline(started + 0.15), pytest.raises(TimeoutError):
            await state.invoke(streaming)
        assert time.monotonic() - started < 0.75
        assert entered.is_set() and closed.wait(0.5)
        assert state.workers[0].finished.wait(0.5)
        assert len(state.posts) == 1 and not state.client.is_closed()
    finally:
        closed.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_deadline_returns_before_blocked_headers_and_rejects_late_results(
    native_sdk, streaming
):
    state = native_sdk
    entered, released = threading.Event(), threading.Event()

    def block():
        entered.set()
        released.wait(2)

    state.before_headers = block
    started = time.monotonic()
    try:
        with invocation_deadline(started + 0.15), pytest.raises(TimeoutError):
            await state.invoke(streaming)
        assert time.monotonic() - started < 0.75
        assert entered.is_set() and not released.is_set()
        assert len(state.posts) == 1 and not state.client.is_closed()
    finally:
        released.set()
        assert state.workers[0].finished.wait(0.5)
