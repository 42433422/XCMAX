"""Exercise full ASGI response lifetime, correlation, isolation and failure semantics."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.middleware import neuro_http_trace as middleware
from app.middleware.neuro_http_trace import NeuroHttpTraceMiddleware, _redact_headers
from app.neuro_bus.tracer import get_trace_context


@pytest.fixture
def neuro_enabled(monkeypatch):
    monkeypatch.setattr(
        "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled", lambda: True
    )
    monkeypatch.setattr("app.neuro_bus.neuro_trace_config.should_sample_http", lambda: True)
    publish = MagicMock(return_value=True)
    monkeypatch.setattr("app.neuro_bus.application_neuro_bridge.publish_neuro_event", publish)
    return publish


def _scope(*, headers=(), path="/api/ai/chat/stream", kind="http"):
    return {
        "type": kind,
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "query_string": b"limit=10",
        "headers": list(headers),
        "client": ("127.0.0.1", 5000),
        "server": ("test", 80),
    }


async def _drive(app, *, scope=None, disconnected=False):
    messages = []

    async def receive():
        return {"type": "http.disconnect" if disconnected else "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    await NeuroHttpTraceMiddleware(app)(scope or _scope(), receive, send)
    return messages


async def _success(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"done"})


class TestRedactHeaders:
    """_redact_headers 纯函数测试。"""

    def test_sensitive_headers_are_redacted(self):
        headers = {
            "Authorization": "Bearer secret-token",
            "Cookie": "session=abc123",
            "Set-Cookie": "token=xyz",
            "X-API-Key": "key123",
            "X-Auth-Token": "auth-tok",
        }
        result = _redact_headers(headers)
        assert result["Authorization"] == "<redacted>"
        assert result["Cookie"] == "<redacted>"
        assert result["Set-Cookie"] == "<redacted>"
        assert result["X-API-Key"] == "<redacted>"
        assert result["X-Auth-Token"] == "<redacted>"

    def test_sensitive_headers_case_insensitive(self):
        result = _redact_headers(
            {"AUTHORIZATION": "Bearer secret", "Cookie": "s", "x-api-key": "k"}
        )
        assert result["AUTHORIZATION"] == "<redacted>"
        assert result["Cookie"] == "<redacted>"
        assert result["x-api-key"] == "<redacted>"

    def test_normal_headers_preserved(self):
        result = _redact_headers({"Content-Type": "application/json", "X-Request-ID": "abc"})
        assert result["Content-Type"] == "application/json"
        assert result["X-Request-ID"] == "abc"

    def test_long_header_value_truncated_to_200_chars(self):
        result = _redact_headers({"X-Long": "x" * 500})
        assert len(result["X-Long"]) == 200
        assert result["X-Long"] == "x" * 200

    def test_empty_headers_dict(self):
        assert _redact_headers({}) == {}

    def test_non_string_values_converted_to_str(self):
        result = _redact_headers({"X-Count": 42, "X-Flag": True, "X-None": None})
        assert result["X-Count"] == "42"
        assert result["X-Flag"] == "True"
        assert result["X-None"] == "None"

    def test_exception_during_items_returns_empty_dict(self):
        class _BrokenHeaders:
            def items(self):
                raise ValueError("boom")

        assert _redact_headers(_BrokenHeaders()) == {}

    def test_partial_iteration_exception_returns_partial_dict(self):
        class _PartialHeaders:
            def items(self):
                yield "X-Ok", "ok"
                raise ValueError("boom mid-iter")

        assert _redact_headers(_PartialHeaders()) == {"X-Ok": "ok"}


async def test_w3c_request_and_response_share_context(neuro_enabled):
    trace_id, parent_id = "1" * 32, "2" * 16
    scope = _scope(
        headers=[
            (b"traceparent", f"00-{trace_id}-{parent_id}-00".encode()),
            (b"x-request-id", b"test-request-123"),
        ]
    )
    before = get_trace_context()

    async def app(scope, receive, send):
        context = get_trace_context()
        assert context["trace_id"] == trace_id
        assert context["span_id"] != parent_id
        assert context["request_id"] == "test-request-123"
        assert scope["state"]["trace_id"] == trace_id
        await _success(scope, receive, send)

    messages = await _drive(app, scope=scope)
    headers = dict(messages[0]["headers"])
    assert headers[b"x-trace-id"].decode() == trace_id
    assert headers[b"x-request-id"] == b"test-request-123"
    assert headers[b"traceparent"].decode().endswith("-00")
    started, completed = [call.args[1] for call in neuro_enabled.call_args_list]
    assert started["parent_span_id"] == parent_id
    assert completed["trace_id"] == started["trace_id"]
    assert completed["span_id"] == started["span_id"]
    assert completed["duration_ms"] == completed["latency_ms"]
    assert get_trace_context() == before


@pytest.mark.parametrize("traceparent", ["garbage", "00-" + "0" * 32 + "-" + "1" * 16 + "-01"])
async def test_invalid_traceparent_gets_new_valid_trace(traceparent, neuro_enabled):
    messages = await _drive(
        _success, scope=_scope(headers=[(b"traceparent", traceparent.encode())])
    )
    headers = dict(messages[0]["headers"])
    assert len(headers[b"x-trace-id"]) == 32
    assert headers[b"x-trace-id"] != b"0" * 32
    assert len(headers[b"traceparent"]) == 55


@pytest.mark.parametrize("sampled", [False, True])
async def test_disabled_sampling_preserves_correlation(sampled, neuro_enabled, monkeypatch):
    monkeypatch.setattr("app.neuro_bus.neuro_trace_config.should_sample_http", lambda: sampled)

    async def app(scope, receive, send):
        assert get_trace_context()["trace_id"]
        await _success(scope, receive, send)

    await _drive(app)
    assert neuro_enabled.call_count == (2 if sampled else 0)


async def test_stream_completion_waits_for_last_byte(neuro_enabled, monkeypatch):
    ticks = [0]
    monkeypatch.setattr(middleware, "time", SimpleNamespace(perf_counter_ns=lambda: ticks[0]))

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        ticks[0] = 500_000_000
        await send({"type": "http.response.body", "body": b"data: first\n\n", "more_body": True})
        assert neuro_enabled.call_count == 1
        await asyncio.sleep(0)
        assert get_trace_context()["trace_id"] == scope["state"]["trace_id"]
        ticks[0] = 1_500_000_000
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    await _drive(app)
    assert neuro_enabled.call_args.args[0] == "http.request.completed"
    assert neuro_enabled.call_args.args[1]["duration_ms"] == 1500


async def test_stream_failure_after_headers_is_not_success(neuro_enabled):
    failure = TypeError("secret=private-value")

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"partial", "more_body": True})
        raise failure

    with pytest.raises(TypeError) as exc:
        await _drive(app)
    assert exc.value is failure
    assert neuro_enabled.call_count == 2
    event, detail = neuro_enabled.call_args.args
    assert event == "http.request.failed"
    assert detail["outcome"] == "error" and detail["error_type"] == "TypeError"
    assert "private-value" not in detail["error"]


@pytest.mark.parametrize("raises", [False, True])
async def test_disconnect_and_cancel_have_terminal_cancelled(neuro_enabled, raises):
    async def app(scope, receive, send):
        if raises:
            raise asyncio.CancelledError
        assert (await receive())["type"] == "http.disconnect"

    if raises:
        with pytest.raises(asyncio.CancelledError):
            await _drive(app)
    else:
        await _drive(app, disconnected=True)
    assert neuro_enabled.call_args.args[0] == "http.request.cancelled"
    assert neuro_enabled.call_args.args[1]["outcome"] == "cancelled"


async def test_incomplete_stream_is_not_success(neuro_enabled):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    await _drive(app)
    assert neuro_enabled.call_args.args[0] == "http.request.failed"


async def test_concurrent_requests_do_not_share_context(neuro_enabled):
    contexts = []
    both_started = asyncio.Event()

    async def app(scope, receive, send):
        original = get_trace_context()
        contexts.append(original)
        if len(contexts) == 2:
            both_started.set()
        await both_started.wait()
        assert get_trace_context() == original
        await _success(scope, receive, send)

    before = get_trace_context()
    await asyncio.gather(_drive(app), _drive(app))
    assert contexts[0]["trace_id"] != contexts[1]["trace_id"]
    assert contexts[0]["request_id"] != contexts[1]["request_id"]
    assert get_trace_context() == before


@pytest.mark.parametrize("failure_type", [RuntimeError, TypeError, AttributeError])
async def test_export_failure_preserves_application_error(neuro_enabled, failure_type):
    neuro_enabled.side_effect = failure_type("publisher unavailable")

    async def app(scope, receive, send):
        raise ValueError("original application error")

    with pytest.raises(ValueError, match="original application error"):
        await _drive(app)


async def test_non_http_scope_passes_through(neuro_enabled):
    async def app(scope, receive, send):
        assert scope["type"] == "websocket"

    await _drive(app, scope=_scope(kind="websocket"))
    neuro_enabled.assert_not_called()


async def test_starlette_middleware_stack_preserves_stream_context(neuro_enabled):
    import httpx
    from fastapi import FastAPI
    from starlette.responses import StreamingResponse

    app = FastAPI()

    @app.middleware("http")
    async def inner_base_http(request, call_next):
        return await call_next(request)

    app.add_middleware(NeuroHttpTraceMiddleware)

    @app.get("/stream")
    async def stream():
        before = get_trace_context()

        async def chunks():
            yield b"data: first\n\n"
            await asyncio.sleep(0)
            assert get_trace_context() == before
            yield b"data: last\n\n"

        return StreamingResponse(chunks(), media_type="text/event-stream")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/stream")
    assert response.text.endswith("data: last\n\n")
    assert neuro_enabled.call_args.args[0] == "http.request.completed"
    assert neuro_enabled.call_args.args[1]["trace_id"] == response.headers["X-Trace-ID"]


@pytest.mark.parametrize(
    "path,status,code", [("/bug", 500, "internal_error"), ("/denied", 403, "http_403")]
)
async def test_error_handler_retains_trace_after_context_unwinds(neuro_enabled, path, status, code):
    import httpx
    from fastapi import FastAPI, HTTPException

    from app.middleware.error_handler import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(NeuroHttpTraceMiddleware)

    @app.get("/bug")
    async def bug():
        raise TypeError("private backend error")

    @app.get("/denied")
    async def denied():
        raise HTTPException(403, "permission denied")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get(path)
    assert response.status_code == status
    assert response.json()["error_code"] == code
    assert response.json()["trace_id"] == response.headers["X-Trace-ID"]
    assert response.json()["span_id"] == neuro_enabled.call_args.args[1]["span_id"]
    assert "private backend error" not in response.text


async def test_http_scope_preserves_sdk_root_sampling_decision(neuro_enabled, monkeypatch):
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ParentBased

    from app.neuro_bus.tracer import NeuroTracer

    provider = TracerProvider(sampler=ParentBased(ALWAYS_OFF))
    monkeypatch.setattr(trace, "get_tracer", lambda *a, **kw: provider.get_tracer("sampling"))

    flags = []

    async def app(scope, receive, send):
        flags.append(get_trace_context()["trace_flags"])
        assert int(flags[0], 16) & 1 == 0
        child = NeuroTracer().start_span("child")
        assert not child._otel_span.is_recording()
        with child.context():
            assert int(get_trace_context()["trace_flags"], 16) & 1 == 0
        child.finish()
        await _success(scope, receive, send)

    try:
        response = await _drive(app)
        assert dict(response[0]["headers"])[b"traceparent"].endswith(("-" + flags[0]).encode())
    finally:
        provider.shutdown()


async def test_publisher_type_error_cannot_turn_success_into_failure(neuro_enabled):
    neuro_enabled.side_effect = TypeError("bad publisher")
    messages = await _drive(_success)
    assert messages[-1]["body"] == b"done"
