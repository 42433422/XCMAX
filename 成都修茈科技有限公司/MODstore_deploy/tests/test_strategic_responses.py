"""Native Responses SDK traffic settles the existing SQL model-call ledger."""

from __future__ import annotations

import asyncio
import importlib
import json
from contextvars import Context

import pytest

from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_usage as budget
from modstore_server import strategic_responses as responses
from tests import test_strategic_stream_usage as stream_tests
from tests.test_strategic_stream_usage import _calls

mandate = stream_tests.mandate


def _payload(**changes):
    return {
        "model": "approved-model",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "Summarize orders"}]}
        ],
        "tools": [
            {
                "type": "function",
                "name": "read_orders",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "max_output_tokens": 20,
        **changes,
    }


def _result(meter="reported", status="completed"):
    result = {
        "id": "resp-orders",
        "object": "response",
        "created_at": 1,
        "status": status,
        "error": None,
        "incomplete_details": None,
        "model": "approved-model-snapshot",
        "output": [
            {
                "type": "function_call",
                "id": "fc-orders",
                "call_id": "call-orders",
                "name": "read_orders",
                "arguments": "{}",
                "status": "completed",
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13},
    }
    if meter == "absent":
        result.pop("usage")
    elif meter == "partial":
        result["usage"].pop("input_tokens")
    elif meter == "estimated":
        result["usage"]["estimated"] = True
    elif meter == "fallback":
        result["fallback_used"] = True
    return result


def _http(
    monkeypatch,
    mandate,
    *,
    meter="reported",
    finish=True,
    pause=False,
    status=200,
    provider="openai",
    headers=None,
    repeated_terminal=False,
):
    import openai

    client_type = openai.DefaultAsyncHttpxClient
    transport = importlib.import_module(client_type.__mro__[1].__module__.split(".")[0])
    seen = {
        "requests": [],
        "clients": [],
        "responses": [],
        "waiting": asyncio.Event(),
        "cancelled": False,
    }

    class Body(transport.AsyncByteStream):
        async def __aiter__(self):
            created = _result(status="in_progress")
            created["output"], created["usage"] = [], None
            frames = [
                {"type": "response.created", "sequence_number": 0, "response": created},
                {
                    "type": "response.function_call_arguments.delta",
                    "sequence_number": 1,
                    "item_id": "fc-orders",
                    "output_index": 0,
                    "delta": "{}",
                },
            ]
            if finish:
                frames.append(
                    {"type": "response.completed", "sequence_number": 2, "response": _result(meter)}
                )
            if repeated_terminal:
                frames.append(
                    {"type": "response.completed", "sequence_number": 3, "response": _result()}
                )
            for frame in frames:
                yield ("event: " + frame["type"] + "\ndata: " + json.dumps(frame) + "\n\n").encode()
            if pause:
                seen["waiting"].set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    seen["cancelled"] = True
                    raise

    def respond(request):
        seen["requests"].append(request)
        state, calls = _calls(mandate)
        assert len(calls) == len(seen["requests"])
        assert sum(call["status"] == "pending" for call in calls) == 1
        assert not state["halted"]
        budget.require_call_reservation(provider=provider, model="approved-model")
        assert request.url.path == "/v1/responses"
        assert request.headers["authorization"] == "Bearer platform-test-key"
        if status != 200:
            response = transport.Response(
                status, json={"error": {"message": "upstream unavailable"}}, request=request
            )
        elif json.loads(request.content).get("stream"):
            response = transport.Response(
                200, stream=Body(), headers={"content-type": "text/event-stream"}, request=request
            )
        else:
            response = transport.Response(200, json=_result(meter), request=request)
        if headers:
            response.headers.update(headers)
        seen["responses"].append(response)
        return response

    def client(**kwargs):
        assert kwargs == {"trust_env": False, "follow_redirects": False}
        return client_type(transport=transport.MockTransport(respond), **kwargs)

    original = responses._client

    def owned_client(*args):
        result = original(*args)
        assert result.max_retries == 0
        seen["clients"].append(result)
        return result

    monkeypatch.setattr(openai, "DefaultAsyncHttpxClient", client)
    monkeypatch.setattr(responses, "_client", owned_client)
    return seen


def _scope(mandate):
    return budget.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"])


def _closed(seen):
    assert all(response.is_closed for response in seen["responses"])
    assert all(client.is_closed() for client in seen["clients"])
    assert budget._CALL.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_native_sdk_preserves_function_protocol_and_settles_provider_usage(
    mandate, monkeypatch, stream
):
    seen = _http(monkeypatch, mandate)
    binding = {
        "grant_id": "approved-remote-grant",
        "event_id": "original-event",
        "task_id": "original-task",
        "subtask_id": "original-subtask",
        "attempt": 1,
        "phase": "execute",
    }
    with _scope(mandate):
        if stream:
            events = [
                event
                async for event in responses.budgeted_responses_stream(
                    _payload(), provider="openai", caller_binding=binding
                )
            ]
            assert [event["type"] for event in events] == [
                "response.created",
                "response.function_call_arguments.delta",
                "response.completed",
            ]
            result = events[-1]["response"]
        else:
            result = await responses.budgeted_responses(
                _payload(), provider="openai", caller_binding=binding
            )
    state, calls = _calls(mandate)
    request = json.loads(seen["requests"][0].content)
    assert request["input"] == _payload()["input"] and request["tools"] == _payload()["tools"]
    assert request["store"] is False and request["background"] is False
    assert request["service_tier"] == "default" and request["truncation"] == "disabled"
    assert request["max_output_tokens"] == 20
    assert result["output"][0]["call_id"] == "call-orders"
    assert not state["halted"] and len(calls) == len(seen["requests"]) == 1
    assert calls[0]["status"] == "settled" and calls[0]["actual_tokens"] == 13
    assert calls[0]["accrued_cost_cents"] == 1
    assert calls[0]["response_id"] == "resp-orders"
    assert calls[0]["upstream_model"] == "approved-model-snapshot"
    assert calls[0]["caller_binding"] == binding
    assert calls[0]["caller_binding_sha256"] == portfolio.digest(binding)
    assert "caller_binding" not in request
    _closed(seen)


@pytest.mark.asyncio
async def test_function_result_continuation_is_a_second_reserved_call(mandate, monkeypatch):
    seen = _http(monkeypatch, mandate)
    with _scope(mandate):
        first = await responses.budgeted_responses(_payload(), provider="openai")
        history = [
            *_payload()["input"],
            *first["output"],
            {"type": "function_call_output", "call_id": "call-orders", "output": "3 orders"},
        ]
        await responses.budgeted_responses(_payload(input=history), provider="openai")
    state, calls = _calls(mandate)
    assert not state["halted"] and len(calls) == len(seen["requests"]) == 2
    assert all(call["status"] == "settled" for call in calls)
    assert sum(call["actual_tokens"] for call in calls) == 26
    assert json.loads(seen["requests"][1].content)["input"][-1]["output"] == "3 orders"
    _closed(seen)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("meter", ["absent", "partial", "estimated", "fallback"])
async def test_missing_or_synthesized_measurement_keeps_the_sql_hold(
    mandate, monkeypatch, stream, meter
):
    seen = _http(monkeypatch, mandate, meter=meter)
    with _scope(mandate):
        if stream:
            _ = [
                event
                async for event in responses.budgeted_responses_stream(
                    _payload(), provider="openai"
                )
            ]
        else:
            await responses.budgeted_responses(_payload(), provider="openai")
    state, calls = _calls(mandate)
    assert state["halted"] and calls[0]["status"] == "unknown"
    assert calls[0]["reserved_tokens"] > 0 and calls[0]["reserved_cost_cents"] > 0
    assert "actual_tokens" not in calls[0]
    _closed(seen)


@pytest.mark.asyncio
async def test_stream_requires_terminal_response_even_with_normal_eof(mandate, monkeypatch):
    seen = _http(monkeypatch, mandate, finish=False)
    with _scope(mandate):
        _ = [
            event
            async for event in responses.budgeted_responses_stream(_payload(), provider="openai")
        ]
    state, calls = _calls(mandate)
    assert state["halted"] and calls[0]["status"] == "unknown"
    _closed(seen)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_pending", [False, True])
async def test_stream_cleanup_closes_sdk_and_preserves_unknown_spend(
    mandate, monkeypatch, cancel_pending
):
    seen = _http(monkeypatch, mandate, finish=False, pause=True)
    with _scope(mandate):
        source = responses.budgeted_responses_stream(_payload(), provider="openai")
        await anext(source)
        if cancel_pending:
            await anext(source)
            pending = asyncio.create_task(anext(source))
            await asyncio.wait_for(seen["waiting"].wait(), 2)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert seen["cancelled"]
    await asyncio.create_task(source.aclose(), context=Context())
    state, calls = _calls(mandate)
    assert state["halted"] and calls[0]["status"] == "unknown"
    _closed(seen)


@pytest.mark.asyncio
async def test_stream_honors_portfolio_stop_between_events(mandate, monkeypatch):
    seen = _http(monkeypatch, mandate)
    with _scope(mandate):
        source = responses.budgeted_responses_stream(_payload(), provider="openai")
        await anext(source)
        portfolio.stop_portfolio(mandate[0], owner_user_id=7, actor="admin:7", reason="stop")
        with pytest.raises(portfolio.PortfolioError):
            await anext(source)
        await source.aclose()
    assert _calls(mandate)[1][0]["status"] == "unknown"
    _closed(seen)


@pytest.mark.asyncio
async def test_upstream_error_is_not_silently_retried(mandate, monkeypatch):
    from openai import APIStatusError

    seen = _http(monkeypatch, mandate, status=503)
    with _scope(mandate), pytest.raises(APIStatusError):
        await responses.budgeted_responses(_payload(), provider="openai")
    assert len(seen["requests"]) == 1 and _calls(mandate)[1][0]["status"] == "unknown"
    _closed(seen)


@pytest.mark.asyncio
@pytest.mark.parametrize("first_usage", ["absent", "partial", "reported"])
async def test_second_terminal_cannot_replace_an_invalid_or_completed_original_receipt(
    mandate, monkeypatch, first_usage
):
    seen = _http(monkeypatch, mandate, meter=first_usage, repeated_terminal=True)
    with _scope(mandate):
        events = [
            event
            async for event in responses.budgeted_responses_stream(_payload(), provider="openai")
        ]
    assert sum(event["type"] == "response.completed" for event in events) == 2
    state, calls = _calls(mandate)
    assert len(seen["requests"]) == len(calls) == 1
    assert calls[0]["status"] == "unknown" and state["halted"]
    assert "actual_tokens" not in calls[0]
    _closed(seen)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"previous_response_id": "resp-prior"},
        {"store": True},
        {"background": True},
        {"caller_binding": {"grant_id": "untrusted-request-body"}},
        {"extra_body": {"num_retries": 3, "disable_fallbacks": False}},
        {"gateway_attempts_verified": True},
        {"tools": [{"type": "web_search"}]},
        {"input": [{"type": "item_reference", "id": "msg-prior"}]},
        {
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_image", "image_url": "https://example.test/image"}],
                }
            ]
        },
        {"model": "unapproved-model"},
    ],
)
async def test_only_explicit_approved_text_work_is_admitted(mandate, monkeypatch, changes):
    seen = _http(monkeypatch, mandate)
    with _scope(mandate), pytest.raises(portfolio.PortfolioError):
        await responses.budgeted_responses(_payload(**changes), provider="openai")
    assert not seen["requests"] and not _calls(mandate)[1]


@pytest.mark.asyncio
async def test_schema_bytes_cannot_exceed_the_approved_call_budget(mandate, monkeypatch):
    seen = _http(monkeypatch, mandate)
    with _scope(mandate), pytest.raises(portfolio.PortfolioError, match="token budget"):
        await responses.budgeted_responses(
            _payload(
                tools=[{"type": "function", "name": "read_orders", "description": "x" * 50_000}]
            ),
            provider="openai",
        )
    assert not seen["requests"] and not _calls(mandate)[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("mandate", ["litellm"], indirect=True)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "headers,verified",
    [
        ({"x-litellm-attempted-retries": "0", "x-litellm-attempted-fallbacks": "0"}, True),
        ({}, False),
        ({"x-litellm-attempted-retries": "1", "x-litellm-attempted-fallbacks": "0"}, False),
        ({"x-litellm-attempted-retries": "0", "x-litellm-attempted-fallbacks": "1"}, False),
        ({"x-litellm-attempted-retries": "0, 1", "x-litellm-attempted-fallbacks": "0"}, False),
        ({"x-litellm-attempted-retries": "0", "x-litellm-attempted-fallbacks": "unknown"}, False),
    ],
)
async def test_native_gateway_controls_and_raw_attempt_headers(
    mandate, monkeypatch, stream, headers, verified
):
    seen = _http(monkeypatch, mandate, provider="litellm", headers=headers)

    async def call():
        if stream:
            return [
                event
                async for event in responses.budgeted_responses_stream(
                    _payload(), provider="litellm"
                )
            ]
        return await responses.budgeted_responses(_payload(), provider="litellm")

    with _scope(mandate):
        if verified:
            await call()
        else:
            with pytest.raises(portfolio.PortfolioError, match="single original provider attempt"):
                await call()
    state, calls = _calls(mandate)
    assert len(seen["requests"]) == len(calls) == 1
    # The real SDK flattens only server-controlled extra_body into the wire body.
    body = json.loads(seen["requests"][0].content)
    assert body["num_retries"] == 0 and body["disable_fallbacks"] is True
    assert "extra_body" not in body and "gateway_attempts_verified" not in body
    if verified:
        assert calls[0]["status"] == "settled" and calls[0]["actual_tokens"] == 13
        assert calls[0]["upstream_model"] == "approved-model-snapshot"
        assert not state["halted"]
    else:
        assert calls[0]["status"] == "unknown" and state["halted"]
        assert "actual_tokens" not in calls[0]
    _closed(seen)
