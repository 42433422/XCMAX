"""Real-behavior tests for app.middleware.neuro_http_trace (cov wave 2).

Covers _redact_headers (redaction / truncation / except branch) and the
neuro_http_trace_middleware sampling gate, started/completed/failed event
publication, and the nested except probes.

All external neuro_bus deps are patched at their *source* module paths
because the middleware imports them inside the function body.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.middleware.neuro_http_trace import (
    _redact_headers,
    neuro_http_trace_middleware,
)


# --------------------------------------------------------------------------- #
# _redact_headers
# --------------------------------------------------------------------------- #
def test_redact_headers_masks_sensitive_and_passes_through():
    headers = {
        "Authorization": "Bearer secret-token",
        "Cookie": "session=abc",
        "Set-Cookie": "x=y",
        "X-Api-Key": "k",
        "X-Auth-Token": "t",
        "Content-Type": "application/json",
        "X-Request-Id": "req-123",
    }
    out = _redact_headers(headers)

    # sensitive headers (case-insensitive match) are redacted
    assert out["Authorization"] == "<redacted>"
    assert out["Cookie"] == "<redacted>"
    assert out["Set-Cookie"] == "<redacted>"
    assert out["X-Api-Key"] == "<redacted>"
    assert out["X-Auth-Token"] == "<redacted>"
    # non-sensitive headers pass through untouched
    assert out["Content-Type"] == "application/json"
    assert out["X-Request-Id"] == "req-123"


def test_redact_headers_truncates_long_values():
    long_value = "v" * 500
    out = _redact_headers({"X-Long": long_value})
    # value is truncated to 200 chars
    assert out["X-Long"] == "v" * 200
    assert len(out["X-Long"]) == 200


def test_redact_headers_case_insensitive_lowercase_keys():
    # lowercase variants should also be caught by the skip set
    out = _redact_headers({"authorization": "Bearer z", "x-api-key": "k"})
    assert out["authorization"] == "<redacted>"
    assert out["x-api-key"] == "<redacted>"


def test_redact_headers_swallows_recoverable_error():
    class BoomHeaders:
        def items(self):
            raise ValueError("boom")  # ValueError ∈ RECOVERABLE_ERRORS

    # exception path returns the (empty) dict accumulated so far
    out = _redact_headers(BoomHeaders())
    assert out == {}


def test_redact_headers_empty():
    assert _redact_headers({}) == {}


# --------------------------------------------------------------------------- #
# Helpers / fakes for the middleware
# --------------------------------------------------------------------------- #
class _FakeURL:
    def __init__(self, path="/api/thing", query="a=1"):
        self.path = path
        self.query = query


class _FakeClient:
    def __init__(self, host="10.0.0.1"):
        self.host = host


class _FakeRequest:
    def __init__(self, path="/api/thing", query="a=1", method="GET", client=_FakeClient()):
        self.url = _FakeURL(path, query)
        self.method = method
        self.client = client
        self.headers = {"Content-Type": "application/json", "Authorization": "Bearer x"}


class _FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code


# --------------------------------------------------------------------------- #
# Sampling gate (lines 49-52)
# --------------------------------------------------------------------------- #
async def test_middleware_skips_when_stack_disabled():
    request = _FakeRequest()
    sentinel = _FakeResponse(204)

    async def call_next(_req):
        return sentinel

    with (
        patch(
            "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
            return_value=False,
        ),
        patch(
            "app.neuro_bus.neuro_trace_config.should_sample_http",
            return_value=True,
        ),
        patch("app.neuro_bus.application_neuro_bridge.publish_neuro_event") as pub,
    ):
        result = await neuro_http_trace_middleware(request, call_next)

    assert result is sentinel
    # gate short-circuits: no events published
    pub.assert_not_called()


async def test_middleware_skips_when_not_sampled():
    request = _FakeRequest()
    sentinel = _FakeResponse(200)

    async def call_next(_req):
        return sentinel

    with (
        patch(
            "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.neuro_trace_config.should_sample_http",
            return_value=False,
        ),
        patch("app.neuro_bus.application_neuro_bridge.publish_neuro_event") as pub,
    ):
        result = await neuro_http_trace_middleware(request, call_next)

    assert result is sentinel
    pub.assert_not_called()


async def test_middleware_gate_import_error_falls_through(monkeypatch):
    """If the gate imports raise a RECOVERABLE_ERROR, fall through to call_next."""
    request = _FakeRequest()
    sentinel = _FakeResponse(200)

    async def call_next(_req):
        return sentinel

    # is_neuro_stack_enabled raises a recoverable error -> except branch (51-52)
    with patch(
        "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
        side_effect=RuntimeError("gate exploded"),
    ):
        result = await neuro_http_trace_middleware(request, call_next)

    assert result is sentinel


# --------------------------------------------------------------------------- #
# Success path: started + completed events (lines 54-96)
# --------------------------------------------------------------------------- #
async def test_middleware_success_publishes_started_and_completed():
    request = _FakeRequest(path="/api/thing", query="a=1", method="POST")
    response = _FakeResponse(201)

    async def call_next(_req):
        return response

    events: list[tuple[str, dict]] = []

    def fake_publish(event_type, payload, domain="global"):
        events.append((event_type, payload, domain))
        return True

    with (
        patch(
            "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.neuro_trace_config.should_sample_http",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            side_effect=fake_publish,
        ),
    ):
        result = await neuro_http_trace_middleware(request, call_next)

    assert result is response

    types = [e[0] for e in events]
    assert types == ["http.request.started", "http.request.completed"]

    started_payload = events[0][1]
    assert started_payload["method"] == "POST"
    assert started_payload["path"] == "/api/thing"
    assert started_payload["query"] == "a=1"
    assert started_payload["client"] == "10.0.0.1"
    # headers redacted in started event
    assert started_payload["headers"]["Authorization"] == "<redacted>"
    assert "request_id" in started_payload
    assert events[0][2] == "global"

    completed_payload = events[1][1]
    assert completed_payload["status_code"] == 201
    assert completed_payload["method"] == "POST"
    assert isinstance(completed_payload["latency_ms"], float)
    # same request id flows through both events
    assert completed_payload["request_id"] == started_payload["request_id"]


async def test_middleware_started_publish_failure_is_swallowed():
    """publish on started raises -> except probe (74-75); request still proceeds."""
    request = _FakeRequest()
    response = _FakeResponse(200)

    async def call_next(_req):
        return response

    calls = {"n": 0}

    def flaky_publish(event_type, payload, domain="global"):
        calls["n"] += 1
        if event_type == "http.request.started":
            raise ValueError("started boom")  # recoverable
        return True

    with (
        patch(
            "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.neuro_trace_config.should_sample_http",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            side_effect=flaky_publish,
        ),
    ):
        result = await neuro_http_trace_middleware(request, call_next)

    # started failed but completed still attempted and response returned
    assert result is response
    assert calls["n"] == 2


async def test_middleware_completed_publish_failure_is_swallowed():
    """publish on completed raises -> except probe (94-95); response still returned."""
    request = _FakeRequest()
    response = _FakeResponse(200)

    async def call_next(_req):
        return response

    def flaky_publish(event_type, payload, domain="global"):
        if event_type == "http.request.completed":
            raise RuntimeError("completed boom")  # recoverable
        return True

    with (
        patch(
            "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.neuro_trace_config.should_sample_http",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            side_effect=flaky_publish,
        ),
    ):
        result = await neuro_http_trace_middleware(request, call_next)

    assert result is response


async def test_middleware_no_client_uses_empty_host():
    request = _FakeRequest(client=None)
    response = _FakeResponse(200)

    async def call_next(_req):
        return response

    events: list = []

    def fake_publish(event_type, payload, domain="global"):
        events.append((event_type, payload))
        return True

    with (
        patch(
            "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.neuro_trace_config.should_sample_http",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            side_effect=fake_publish,
        ),
    ):
        await neuro_http_trace_middleware(request, call_next)

    assert events[0][1]["client"] == ""


# --------------------------------------------------------------------------- #
# Failure path: failed event + re-raise (lines 97-115)
# --------------------------------------------------------------------------- #
async def test_middleware_failed_publishes_failed_event_and_reraises():
    request = _FakeRequest(path="/api/boom", method="DELETE")

    async def call_next(_req):
        raise ValueError("downstream broke")  # recoverable -> failed branch

    events: list = []

    def fake_publish(event_type, payload, domain="global"):
        events.append((event_type, payload))
        return True

    with (
        patch(
            "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.neuro_trace_config.should_sample_http",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            side_effect=fake_publish,
        ),
    ):
        with pytest.raises(ValueError, match="downstream broke"):
            await neuro_http_trace_middleware(request, call_next)

    types = [e[0] for e in events]
    assert types == ["http.request.started", "http.request.failed"]
    failed_payload = events[1][1]
    assert failed_payload["method"] == "DELETE"
    assert failed_payload["path"] == "/api/boom"
    assert "downstream broke" in failed_payload["error"]
    assert isinstance(failed_payload["latency_ms"], float)


async def test_middleware_failed_publish_failure_is_swallowed_but_original_reraises():
    """If publishing the failed event itself raises, the *original* error re-raises."""
    request = _FakeRequest()

    async def call_next(_req):
        raise RuntimeError("original downstream error")

    def flaky_publish(event_type, payload, domain="global"):
        if event_type == "http.request.failed":
            raise ValueError("publish failed-event boom")  # recoverable (113-114)
        return True

    with (
        patch(
            "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.neuro_trace_config.should_sample_http",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            side_effect=flaky_publish,
        ),
    ):
        # the failed-event publish error is swallowed; original RuntimeError re-raises
        with pytest.raises(RuntimeError, match="original downstream error"):
            await neuro_http_trace_middleware(request, call_next)


async def test_middleware_non_recoverable_downstream_error_propagates_unwrapped():
    """A non-recoverable error (e.g. base Exception) is NOT caught by the failed branch."""
    request = _FakeRequest()

    class WeirdError(BaseException):
        pass

    async def call_next(_req):
        raise WeirdError("not recoverable")

    events: list = []

    def fake_publish(event_type, payload, domain="global"):
        events.append(event_type)
        return True

    with (
        patch(
            "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.neuro_trace_config.should_sample_http",
            return_value=True,
        ),
        patch(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            side_effect=fake_publish,
        ),
    ):
        with pytest.raises(WeirdError, match="not recoverable"):
            await neuro_http_trace_middleware(request, call_next)

    # only the started event fired; failed branch did not run for a non-recoverable error
    assert events == ["http.request.started"]
