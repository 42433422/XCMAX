"""Real SDK traffic and SQL receipts for account-bound native Responses."""

from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from modstore_server import llm_billing as billing
from modstore_server import llm_billing_recovery as recovery
from modstore_server import llm_client_requests as ledger
from modstore_server import llm_responses as responses
from modstore_server import llm_responses_transport as transport
from modstore_server.db.llm_chat import LlmCallLog, LlmClientRequest
from modstore_server.llm_billing_values import WalletHold
from modstore_server.llm_crypto import decrypt_secret, encrypt_secret
from modstore_server.llm_gateway_contract import codex_route_contract
from modstore_server.llm_key_resolver import ChatRouteSnapshot, chat_route_token
from modstore_server.llm_model_concurrency import (
    concurrency_key,
)
from modstore_server.llm_model_concurrency import controller as concurrency
from tests.platform_model_support import isolated as isolated
from tests.test_llm_client_requests import db as db

KEY = "responses-test-original-request"
COUNTERS = {"x-litellm-attempted-retries": "0", "x-litellm-attempted-fallbacks": "0"}
CAPABILITIES = {
    "context_window": 128000,
    "max_output_tokens": 4096,
    "upstream_vendor": "deepseek",
    "response_model": "deepseek-chat",
    "source": "litellm_model_info",
}


def _payload(**changes):
    return {
        "model": "litellm/account-model",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "Inspect orders"}]}],
        "tools": [
            {
                "type": "function",
                "name": "read_orders",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "max_output_tokens": 32,
        **changes,
    }


def _result(**changes):
    return {
        "id": "resp-orders",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "model": "deepseek-chat",
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
        "usage": {"input_tokens": 13, "output_tokens": 3, "total_tokens": 16},
        **changes,
    }


def _request(token, key=KEY):
    return Request(
        {
            "type": "http",
            "headers": [
                (b"authorization", b"Bearer session-test-only"),
                (b"idempotency-key", key.encode()),
                (b"x-xcmax-route-token", token.encode()),
            ],
            "client": ("testclient", 1234),
        }
    )


async def _consume(response):
    if isinstance(response, responses.JSONResponse):
        return json.loads(response.body), []
    frames = [frame async for frame in response.body_iterator]
    events = [
        json.loads((frame.decode() if isinstance(frame, bytes) else frame).split("\ndata: ", 1)[1])
        for frame in frames
    ]
    terminal = next(
        (event["response"] for event in reversed(events) if event["type"] in responses._TERMINALS),
        None,
    )
    return terminal, events


@pytest.fixture
def billed(db, monkeypatch):
    route = ChatRouteSnapshot(
        "litellm",
        "account-model",
        "platform_gateway",
        "platform",
        "revision-a",
        "server-only-model-key",
        "https://gateway.example.test/v1",
    )
    contract = {
        "runtime": codex_route_contract("litellm", "account-model", CAPABILITIES),
        "model_capabilities": dict(CAPABILITIES),
    }
    wallet = SimpleNamespace(
        enabled=True,
        validate_pat=Mock(),
        preauthorize=AsyncMock(return_value=WalletHold("wallet-hold-7", Decimal(".05"), True)),
        settle=AsyncMock(),
        release=AsyncMock(),
        read_hold=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(responses, "JavaWalletClient", lambda **kwargs: wallet)
    monkeypatch.setattr(recovery, "JavaWalletClient", lambda **kwargs: wallet)
    monkeypatch.setattr(responses, "assert_llm_chat_allowed", AsyncMock())
    monkeypatch.setattr(responses, "enforce_risk_limits", Mock())
    state = {
        "route": route,
        "contract": contract,
        "wallet": wallet,
        "requests": [],
        "clients": [],
        "upstream": [],
        "headers": dict(COUNTERS),
        "result": _result(),
        "status": 200,
        "error_body": {"error": {"message": "upstream unavailable"}},
        "terminal": True,
        "duplicate": False,
        "closed": False,
        "pause": None,
        "read_blocked": asyncio.Event(),
        "cancel_on_terminal": None,
        "stream_chunks": None,
        "body_chunks": 0,
    }
    real_client = transport.DefaultAsyncHttpxClient
    httpx = importlib.import_module(real_client.__mro__[1].__module__.split(".")[0])

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            if state["stream_chunks"] is not None:
                for chunk in state["stream_chunks"]:
                    state["body_chunks"] += 1
                    yield chunk
                return
            result = state["result"]
            events = [
                {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {**result, "output": [], "usage": None, "status": "in_progress"},
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "sequence_number": 1,
                    "item_id": "fc-orders",
                    "output_index": 0,
                    "delta": "{}",
                },
            ]
            if state["terminal"]:
                events.append(
                    {
                        "type": "response." + result["status"],
                        "sequence_number": 2,
                        "response": result,
                    }
                )
            if state["duplicate"]:
                events.append(
                    {"type": "response.completed", "sequence_number": 3, "response": result}
                )
            for event in events:
                if event["type"] in responses._TERMINALS and state["cancel_on_terminal"]:
                    asyncio.get_running_loop().call_soon(state["cancel_on_terminal"].cancel)
                yield responses._sse(event).encode()
            if state["pause"] is not None:
                state["read_blocked"].set()
                await state["pause"].wait()

        async def aclose(self):
            state["closed"] = True

    def respond(request):
        state["requests"].append(request)
        row = db.query(LlmClientRequest).filter_by(user_id=7, client_request_id=KEY).one()
        assert row.state == "settling"
        assert request.url.path == "/v1/responses"
        assert request.headers["authorization"] == "Bearer server-only-model-key"
        body = json.loads(request.content)
        assert body["model"] == "account-model"
        assert body["num_retries"] == 0 and body["disable_fallbacks"] is True
        if state["status"] != 200:
            result = httpx.Response(
                state["status"],
                json=state["error_body"],
                headers=state["headers"],
            )
        elif body.get("stream"):
            result = httpx.Response(
                200,
                stream=Body(),
                headers={"content-type": "text/event-stream", **state["headers"]},
            )
        else:
            result = httpx.Response(200, json=state["result"], headers=state["headers"])
        state["upstream"].append(result)
        return result

    def client(**options):
        assert options["trust_env"] is False and options["follow_redirects"] is False
        result = real_client(transport=httpx.MockTransport(respond), **options)
        state["clients"].append(result)
        return result

    monkeypatch.setattr(transport, "DefaultAsyncHttpxClient", client)

    async def call(*, body=None, uid=7, token=None, key=KEY):
        if token is None:
            token = chat_route_token(state["route"], 7, runtime_contract=state["contract"])
        return await responses.run_billed_responses(
            _request(token, key), db, SimpleNamespace(id=uid), body or _payload()
        )

    state["call"] = call
    return state


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("byok", [False, True])
async def test_sdk_preserves_wire_settles_once_and_replays_even_after_route_expires(
    billed, db, stream, byok
):
    if byok:
        billed["route"] = replace(billed["route"], key_source="user_override")
    body = _payload(stream=stream)
    first = await billed["call"](body=body)
    result, events = await _consume(first)
    xcagi = result["xcagi"]
    assert result["model"] == "deepseek-chat" and result["output"][0]["call_id"] == "call-orders"
    assert xcagi["schema"] == "xcmax.responses-billing.v1"
    assert xcagi["provider"] == "litellm" and xcagi["model"] == "account-model"
    assert xcagi["config_revision"] == "revision-a" and xcagi["client_request_id"] == KEY
    assert xcagi["billed"] is not byok and xcagi["billing_status"] == (
        "byok" if byok else "settled"
    )
    assert xcagi["usage"] == _result()["usage"]
    assert xcagi["charge_amount"] == ("0.00" if byok else "0.02")
    assert xcagi["hold_no"] == ("byok-" + xcagi["request_id"] if byok else "wallet-hold-7")
    assert (
        first.headers["x-xcmax-upstream-attempts"] == "1"
        and first.headers["x-xcmax-upstream-fallbacks"] == "0"
    )
    assert all(first.headers[name] == "0" for name in COUNTERS)
    assert all(client.is_closed for client in billed["clients"])
    assert all(response.is_closed for response in billed["upstream"])
    sent = json.loads(billed["requests"][0].content)
    assert sent["input"] == body["input"] and sent["tools"] == body["tools"]
    assert sent["store"] is False and sent["background"] is False
    assert "x-xcmax-route-token" not in billed["requests"][0].headers
    assert "idempotency-key" not in billed["requests"][0].headers
    assert len(billed["requests"]) == 1
    second = await billed["call"](body=body, token="expired-snapshot")
    replay_result, replay_events = await _consume(second)
    assert replay_result == result and replay_events == events
    assert second.headers["x-xcmax-request-replayed"] == "true"
    assert len(billed["requests"]) == 1
    assert (
        billed["wallet"].preauthorize.await_count
        == billed["wallet"].settle.await_count
        == int(not byok)
    )
    billed["wallet"].release.assert_not_awaited()
    assert db.query(LlmCallLog).count() == 1
    row = db.query(LlmCallLog).one()
    assert row.total_tokens == 16 and row.estimated is False
    assert ledger.lookup(db, 7, KEY, 90) == "completed"


@pytest.mark.parametrize(
    "failure",
    [
        "missing-counter",
        "positive-counter",
        "duplicate-counter",
        "wrong-model",
        "missing-usage",
        "estimated-usage",
        "http-400",
        "http-500",
    ],
)
async def test_uncertain_attempt_never_reexecutes_or_releases_its_hold(billed, db, failure):
    if failure == "missing-counter":
        billed["headers"].pop("x-litellm-attempted-fallbacks")
    elif failure == "positive-counter":
        billed["headers"]["x-litellm-attempted-retries"] = "1"
    elif failure == "duplicate-counter":
        billed["headers"]["x-litellm-attempted-retries"] = "0, 0"
    elif failure == "wrong-model":
        billed["result"]["model"] = "another-model"
    elif failure == "missing-usage":
        billed["result"].pop("usage")
    elif failure == "estimated-usage":
        billed["result"]["usage"]["estimated"] = True
    else:
        billed["status"] = int(failure.removeprefix("http-"))
    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            await billed["call"]()
        assert error.value.status_code == 409 and error.value.detail["state"] == "settling"
    assert len(billed["requests"]) == 1 and ledger.lookup(db, 7, KEY, 90) == "settling"
    billed["wallet"].settle.assert_not_awaited()
    billed["wallet"].release.assert_not_awaited()
    assert db.query(LlmCallLog).count() == 0


@pytest.mark.parametrize("invalid_at_gateway", [False, True])
async def test_schema_rejection_has_no_paid_retry(billed, db, invalid_at_gateway):
    schema = {"type": "invalid"} if invalid_at_gateway else {"type": "object"}
    body = {
        "model": "litellm/account-model",
        "input": "Review the evidence",
        "text": {"format": {"type": "json_schema", "name": "review", "schema": schema}},
    }
    billed["status"] = 400
    billed["error_body"] = {
        "error": {
            "message": "response_format.json_schema is not a valid moonshot flavored json schema"
        }
    }
    if invalid_at_gateway:
        with pytest.raises(HTTPException) as error:
            await billed["call"](body=body)
        assert error.value.status_code == 422
        assert error.value.detail["code"] == "CODEX_RESPONSE_SCHEMA_REJECTED"
        billed["wallet"].preauthorize.assert_not_awaited()
        assert not billed["requests"]
        return
    for _ in range(2):
        reply = await billed["call"](body=body)
        assert reply.status_code == 422
        assert json.loads(reply.body)["detail"]["code"] == "CODEX_RESPONSE_SCHEMA_REJECTED"
    assert len(billed["requests"]) == 1
    billed["wallet"].release.assert_awaited_once()
    billed["wallet"].settle.assert_not_awaited()
    assert recovery.response_receipt(db, 7, KEY)["rejection"]["billing_status"] == "released"
    assert db.query(LlmCallLog).count() == 0


async def test_schema_rejection_keeps_uncertain_hold_until_matching_wallet_readback(billed, db):
    body = {
        "model": "litellm/account-model",
        "input": "Review evidence",
        "text": {"format": {"type": "json_schema", "name": "review", "schema": {"type": "object"}}},
    }
    billed["status"] = 400
    billed["error_body"] = {"error": {"code": "invalid_json_schema"}}
    billed["wallet"].release.side_effect = HTTPException(502, "wallet response lost")
    with pytest.raises(HTTPException) as error:
        await billed["call"](body=body)
    assert error.value.status_code == 409
    assert recovery.response_receipt(db, 7, KEY) is None
    receipt = {
        "hold_no": "wallet-hold-7",
        "request_id": ledger.attempt_request_id(7, KEY, 1),
        "provider": "litellm",
        "model": "account-model",
        "status": "released",
    }
    billed["wallet"].read_hold.return_value = {**receipt, "request_id": "foreign-request"}
    with pytest.raises(HTTPException) as error:
        await billed["call"](body=body)
    assert error.value.status_code == 409
    billed["wallet"].read_hold.return_value = receipt
    reply = await billed["call"](body=body)
    assert reply.status_code == 422 and len(billed["requests"]) == 1
    billed["wallet"].release.assert_awaited_once()


@pytest.mark.parametrize("failure", ["truncated", "duplicate", "wrong-model"])
async def test_stream_failures_publish_no_success_terminal_and_leave_usage_unknown(
    billed, db, failure
):
    billed["terminal"] = failure != "truncated"
    billed["duplicate"] = failure == "duplicate"
    if failure == "wrong-model":
        billed["result"]["model"] = "another-model"
    result, events = await _consume(await billed["call"](body=_payload(stream=True)))
    assert result is None and events[-1]["type"] == "error"
    assert all(event["type"] != "response.completed" for event in events)
    assert billed["closed"] is True and ledger.lookup(db, 7, KEY, 90) == "settling"
    billed["wallet"].settle.assert_not_awaited()
    billed["wallet"].release.assert_not_awaited()


async def test_terminal_is_held_until_native_eof_and_authoritative_settlement(billed, db):
    billed["pause"] = asyncio.Event()
    response = await billed["call"](body=_payload(stream=True))
    events = response.body_iterator
    assert "response.created" in await anext(events)
    assert "response.function_call_arguments.delta" in await anext(events)
    pending = asyncio.create_task(anext(events))
    await asyncio.wait_for(billed["read_blocked"].wait(), timeout=5)
    assert not pending.done()
    billed["wallet"].settle.assert_not_awaited()
    assert ledger.lookup(db, 7, KEY, 90) == "settling"
    billed["pause"].set()
    terminal = await pending
    assert "response.completed" in terminal and '"xcagi"' in terminal
    assert billed["closed"] is True and ledger.lookup(db, 7, KEY, 90) == "completed"
    with pytest.raises(StopAsyncIteration):
        await anext(events)


@pytest.mark.parametrize("limit", ["partial-line", "comments", "events"])
async def test_account_runtime_stream_limit_keeps_the_original_wallet_hold_without_replay(
    billed, db, monkeypatch, limit
):
    from modstore_server import llm_gateway_contract, platform_model_transport

    if limit == "events":
        monkeypatch.setattr(llm_gateway_contract, "MAX_STREAM_EVENTS", 1)
    else:
        prefix = b'data: {"unfinished":"' if limit == "partial-line" else b": keepalive\n\n"
        chunk = b"x" * 64 if limit == "partial-line" else b": " + b"x" * 64 + b"\n\n"
        billed["stream_chunks"] = [prefix, chunk, b"unread-tail"]
        monkeypatch.setattr(platform_model_transport, "MAX_MODEL_STREAM_BYTES", len(prefix) + 63)
    body = _payload(stream=True)
    result, events = await _consume(await billed["call"](body=body))
    assert result is None and events[-1]["code"] == "CODEX_REQUEST_UNRESOLVED"
    assert all(event["type"] not in responses._TERMINALS for event in events)
    if limit != "events":
        assert billed["body_chunks"] == 2
    assert billed["closed"] and all(client.is_closed for client in billed["clients"])
    assert ledger.lookup(db, 7, KEY, 90) == "settling"
    assert len(billed["requests"]) == 1
    assert billed["requests"][0].headers["accept-encoding"] == "identity"
    billed["wallet"].settle.assert_not_awaited()
    billed["wallet"].release.assert_not_awaited()
    assert db.query(LlmCallLog).count() == 0
    with pytest.raises(HTTPException) as error:
        await billed["call"](body=body)
    assert error.value.status_code == 409 and len(billed["requests"]) == 1


@pytest.mark.parametrize("cancel_point", ["blocked-read", "ready-terminal"])
async def test_client_cancellation_closes_the_real_stream_and_keeps_original_attempt_pending(
    billed, db, cancel_point
):
    billed["pause"] = asyncio.Event()
    response = await billed["call"](body=_payload(stream=True))
    events = response.body_iterator
    await anext(events)
    await anext(events)
    waiting = asyncio.create_task(anext(events))
    if cancel_point == "ready-terminal":
        billed["cancel_on_terminal"] = waiting
    else:
        await asyncio.wait_for(billed["read_blocked"].wait(), timeout=5)
        assert not waiting.done()
        waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(5):
            await waiting
    with pytest.raises(StopAsyncIteration):
        await anext(events)
    assert billed["closed"] is True
    assert ledger.lookup(db, 7, KEY, 90) == "settling"
    assert all(client.is_closed for client in billed["clients"])
    billed["wallet"].settle.assert_not_awaited()
    billed["wallet"].release.assert_not_awaited()
    with pytest.raises(HTTPException) as error:
        await billed["call"](body=_payload(stream=True))
    assert error.value.status_code == 409 and len(billed["requests"]) == 1


async def test_definite_wallet_rejection_is_not_an_unknown_paid_attempt(billed, db):
    billed["wallet"].preauthorize.side_effect = HTTPException(402, "insufficient balance")
    with pytest.raises(HTTPException) as error:
        await billed["call"]()
    assert error.value.status_code == 402
    assert billed["requests"] == [] and ledger.lookup(db, 7, KEY, 90) == "failed"
    billed["wallet"].preauthorize.side_effect = None
    result, _ = await _consume(await billed["call"]())
    assert result["xcagi"]["request_id"].endswith("-2")
    assert len(billed["requests"]) == billed["wallet"].settle.await_count == 1


CONCURRENCY_KEY = concurrency_key("litellm", "account-model", config_revision="revision-a")


async def test_platform_rate_limit_returns_window_reset_before_reservation(billed, db, monkeypatch):
    monkeypatch.setattr(responses, "enforce_risk_limits", billing.enforce_risk_limits)
    monkeypatch.setattr(billing, "time", SimpleNamespace(monotonic=lambda: 140.25))
    monkeypatch.setattr(billing, "_WINDOWS", {"llm_user_minute:7": [100.0, 121.0]})
    monkeypatch.setenv("COSER_USER_LLM_RPM", "2")
    with pytest.raises(HTTPException) as error:
        await billed["call"]()
    assert error.value.status_code == 429 and error.value.headers["Retry-After"] == "20"
    assert ledger.lookup(db, 7, KEY, 90) == "not_found"
    billed["wallet"].preauthorize.assert_not_awaited()
    assert billed["requests"] == []


async def test_saturated_model_concurrency_rejects_before_journal_or_wallet(
    billed, db, monkeypatch
):
    monkeypatch.setattr(responses, "_CONCURRENCY_WAIT_S", 0.0)
    concurrency.seed(db, CONCURRENCY_KEY, 1)
    held = await concurrency.acquire(db, CONCURRENCY_KEY, wait_s=0.0, timeout_s=30)
    assert held is not None and held.enforced
    with pytest.raises(HTTPException) as error:
        await billed["call"]()
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "1"
    assert error.value.detail["code"] == "MODEL_CONCURRENCY_SATURATED"
    assert ledger.lookup(db, 7, KEY, 90) == "not_found"
    assert billed["wallet"].preauthorize.await_count == 0
    assert billed["requests"] == []
    concurrency.release(db, held)
    assert concurrency.inflight(db, CONCURRENCY_KEY) == 0


async def test_completed_receipt_still_replays_while_the_model_is_saturated(
    billed, db, monkeypatch
):
    first, _ = await _consume(await billed["call"]())
    assert first is not None
    monkeypatch.setattr(responses, "_CONCURRENCY_WAIT_S", 0.0)
    concurrency.seed(db, CONCURRENCY_KEY, 1)
    held = await concurrency.acquire(db, CONCURRENCY_KEY, wait_s=0.0, timeout_s=30)
    assert held is not None
    replay, _ = await _consume(await billed["call"]())
    assert replay == first
    assert len(billed["requests"]) == 1
    concurrency.release(db, held)


async def test_upstream_429_halves_the_limit_and_keeps_the_attempt_unresolved(billed, db):
    concurrency.seed(db, CONCURRENCY_KEY, 4)
    billed["status"] = 429
    billed["headers"] = {**COUNTERS, "retry-after": "3"}
    with pytest.raises(HTTPException) as error:
        await billed["call"]()
    assert error.value.status_code == 409 and error.value.detail["state"] == "settling"
    assert concurrency.current_limit(db, CONCURRENCY_KEY) == 2
    assert concurrency.inflight(db, CONCURRENCY_KEY) == 0
    billed["wallet"].release.assert_not_awaited()
    assert ledger.lookup(db, 7, KEY, 90) == "settling"


async def test_byok_throttle_cannot_block_the_platform_route(billed, db, monkeypatch):
    monkeypatch.setattr(responses, "_CONCURRENCY_WAIT_S", 0.0)
    concurrency.seed(db, CONCURRENCY_KEY, 4)
    billed["route"] = replace(billed["route"], key_source="user_override")
    billed["status"] = 429
    with pytest.raises(HTTPException) as error:
        await billed["call"]()
    assert error.value.detail["state"] == "settling"
    assert concurrency.current_limit(db, CONCURRENCY_KEY) == 4
    billed["route"] = replace(billed["route"], key_source="platform")
    billed["status"] = 200
    result, _ = await _consume(await billed["call"](key=KEY + "-platform"))
    assert result["xcagi"]["billing_status"] == "settled"
    assert len(billed["requests"]) == 2


async def test_stream_completion_releases_the_slot(billed, db):
    concurrency.seed(db, CONCURRENCY_KEY, 1)
    _, events = await _consume(await billed["call"](body=_payload(stream=True)))
    assert events[-1]["type"] == "response.completed"
    assert concurrency.inflight(db, CONCURRENCY_KEY) == 0


async def test_stream_cancellation_releases_the_slot(billed, db):
    concurrency.seed(db, CONCURRENCY_KEY, 1)
    billed["pause"] = asyncio.Event()
    response = await billed["call"](body=_payload(stream=True))
    frames = response.body_iterator
    await anext(frames)
    await anext(frames)
    waiting = asyncio.create_task(anext(frames))
    await asyncio.wait_for(billed["read_blocked"].wait(), timeout=5)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(5):
            await waiting
    with pytest.raises(StopAsyncIteration):
        await anext(frames)
    assert concurrency.inflight(db, CONCURRENCY_KEY) == 0


@pytest.mark.parametrize(
    "case",
    [
        "other-user",
        "expired",
        "expired-signed",
        "runtime-contract",
        "capacity-contract",
        "model-change",
        "not-codex",
        "bad-key",
        "hidden-retry",
        "remote-history",
        "oversize-output",
    ],
)
async def test_authentication_and_snapshot_guards_reject_before_wallet_or_model(billed, db, case):
    options = {}
    if case == "other-user":
        options["uid"] = 8
    elif case == "expired":
        options["token"] = "invalid-snapshot"
    elif case == "expired-signed":
        sealed = chat_route_token(billed["route"], 7, runtime_contract=billed["contract"])
        data = json.loads(decrypt_secret(sealed))
        data["expires"] = 0
        options["token"] = encrypt_secret(json.dumps(data))
    elif case == "runtime-contract":
        billed["contract"]["runtime"]["response_model"] = "another-model"
    elif case == "capacity-contract":
        billed["contract"]["model_capabilities"]["context_window"] = True
    elif case == "model-change":
        options["body"] = _payload(model="litellm/another-model")
    elif case == "not-codex":
        options["token"] = chat_route_token(billed["route"], 7)
    elif case == "bad-key":
        options["key"] = "bad"
    elif case == "hidden-retry":
        options["body"] = _payload(num_retries=2)
    elif case == "remote-history":
        options["body"] = _payload(previous_response_id="someone-elses-response")
    else:
        options["body"] = _payload(max_output_tokens=10000)
    with pytest.raises(HTTPException) as error:
        await billed["call"](**options)
    if case in {"expired", "expired-signed", "not-codex", "runtime-contract", "capacity-contract"}:
        assert error.value.status_code == 412
    assert billed["requests"] == [] and db.query(LlmClientRequest).count() == 0
    billed["wallet"].preauthorize.assert_not_awaited()


async def test_disabled_wallet_cannot_turn_platform_calls_into_unbilled_requests(billed, db):
    billed["wallet"].enabled = False
    with pytest.raises(HTTPException) as error:
        await billed["call"]()
    assert (
        error.value.status_code == 503 and error.value.detail["code"] == "CODEX_BILLING_UNAVAILABLE"
    )
    assert not billed["requests"] and db.query(LlmClientRequest).count() == 0


async def test_wallet_readback_recovers_the_original_response_without_another_model_call(
    billed, db
):
    billed["wallet"].settle.side_effect = HTTPException(502, "receipt lost after payment")
    with pytest.raises(HTTPException) as error:
        await billed["call"]()
    assert error.value.status_code == 409
    row = db.query(LlmClientRequest).one()
    saved = json.loads(row.done_json)["pending_settlement"]
    billed["wallet"].read_hold.return_value = {
        "status": "settled",
        "settled_amount": saved["charge_amount"],
        **{field: saved[field] for field in ("hold_no", "request_id", "provider", "model")},
    }
    result, _ = await _consume(await billed["call"](token="expired-snapshot"))
    assert result["xcagi"]["billing_status"] == "settled"
    assert len(billed["requests"]) == billed["wallet"].settle.await_count == 1
    assert db.query(LlmCallLog).count() == 1 and ledger.lookup(db, 7, KEY, 90) == "completed"


def test_responses_route_requires_the_existing_account_authentication(monkeypatch):
    from modstore_server import openai_llm_gateway_api as gateway

    app = FastAPI()
    app.include_router(gateway.router)
    app.dependency_overrides[gateway.get_db] = lambda: object()
    with TestClient(app) as client:
        response = client.post("/v1/responses", json=_payload())
    assert response.status_code == 401


async def test_closed_consumer_drains_and_recovers_exact_receipt_without_redispatch(billed, db):
    response = await billed["call"](body=_payload(stream=True))
    frames = response.body_iterator
    await anext(frames)
    await frames.aclose()
    saved = recovery.response_receipt(db, 7, KEY)
    assert saved["response"]["status"] == "completed"
    assert saved["headers"]["X-XCMax-Upstream-Attempts"] == "1"
    assert recovery.response_receipt(db, 8, KEY) is None
    assert len(billed["requests"]) == billed["wallet"].settle.await_count == 1
    assert db.query(LlmCallLog).count() == 1
    assert concurrency.inflight(db, CONCURRENCY_KEY) == 0


@pytest.mark.parametrize("deadline", ["0", "-1", "nan", "9" * 100])
async def test_expired_or_invalid_deadline_never_reserves_or_dispatches(billed, db, deadline):
    request = _request(chat_route_token(billed["route"], 7, runtime_contract=billed["contract"]))
    request.scope["headers"].append((b"x-xcmax-request-deadline-ms", deadline.encode()))
    with pytest.raises(HTTPException) as error:
        await responses.run_billed_responses(request, db, SimpleNamespace(id=7), _payload())
    assert error.value.status_code in {400, 408}
    assert db.query(LlmClientRequest).count() == 0 and not billed["requests"]
    billed["wallet"].preauthorize.assert_not_awaited()
