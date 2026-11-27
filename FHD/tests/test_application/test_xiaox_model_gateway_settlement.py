"""Xiaox provider retries, deadlines and settlement."""

import json
import time
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.application.agent_orchestrator.run_models import AgentRun
from app.infrastructure.billing import model_usage as ledger
from app.infrastructure.billing.model_reservation import settle_model_usage
from app.infrastructure.xiaox.model_gateway import (
    MODEL_PATH,
    ModelRequestTimeout,
    _finish,
    model_request_deadline,
    model_request_timeout_seconds,
    request_remaining,
    response_usage,
    router,
)
from app.infrastructure.xiaox.policy import ModelRoute
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_xiaox_model_gateway import (
    gateway as gateway,
)
from tests.test_application.test_xiaox_model_gateway import (
    post,
)


def test_connect_failure_retries_on_same_route_and_charges_each_attempt_once(gateway):
    client, store, calls, response, app = gateway

    def flaky(request):
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ConnectError("no connection", request=request)
        return httpx.Response(200, json=response)

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(flaky),
        **kwargs,
    )
    assert post(client).status_code == 200
    assert len(calls) == 3 and len({str(call.url) for call in calls}) == 1
    attempts = list(store.binding.metadata["model_requests"].values())
    assert [item["state"] for item in attempts] == ["failed", "failed", "completed"]
    assert [item["attempt"] for item in attempts] == [1, 2, 3]
    assert len({item["request_group"] for item in attempts}) == 1
    assert all(item["diagnostic"]["outcome"] == "not_started" for item in attempts[:2])
    assert len(store.run.llm_calls) == 3 and ledger.get_model_wallet("71")["balance_units"] == 98
    assert "runtime_failure_kind" not in store.run.metadata
    assert "runtime_failure_stage" not in store.run.metadata


def test_429_rejection_retries_with_original_task_deadline(gateway):
    client, store, calls, response, app = gateway
    deadline = store.binding.metadata["deadline_at"]

    def limited(request):
        calls.append(request)
        return (
            httpx.Response(429, headers={"retry-after": "0"})
            if len(calls) == 1
            else httpx.Response(200, json=response)
        )

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(limited),
        **kwargs,
    )
    assert post(client).status_code == 200 and len(calls) == 2
    assert store.binding.metadata["deadline_at"] == deadline
    first = next(iter(store.binding.metadata["model_requests"].values()))
    assert first["diagnostic"]["failure_kind"] == "rate_limited"
    assert first["diagnostic"]["outcome"] == "not_started"
    assert "runtime_failure_kind" not in store.run.metadata
    assert "runtime_failure_reason" not in store.run.metadata


@pytest.mark.parametrize("failure", ["read_timeout", "http_503"])
def test_uncertain_provider_failure_never_replays_request(gateway, failure):
    client, store, calls, _, app = gateway

    def uncertain(request):
        calls.append(request)
        if failure == "read_timeout":
            raise httpx.ReadTimeout("receipt lost", request=request)
        return httpx.Response(503)

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(uncertain),
        **kwargs,
    )
    assert post(client).status_code == 502 and len(calls) == 1
    assert store.binding.metadata["model_reconciliation_required"] is True
    assert post(client).status_code == 409 and len(calls) == 1
    assert store.run.metadata["runtime_failure_kind"] in {
        "transport_unknown",
        "provider_unavailable",
    }


def test_expired_parent_deadline_blocks_network_and_reservation(gateway):
    client, store, calls, _, _ = gateway
    store.binding.metadata["deadline_at"] = time.time() - 1
    assert post(client).status_code == 408
    assert not calls and not store.binding.metadata.get("model_requests")
    assert ledger.get_model_wallet("71")["balance_units"] == 100


def test_cancellation_between_retries_stops_before_second_provider_attempt(gateway):
    from app.infrastructure.xiaox.binding import XiaoxBindingError

    client, store, calls, _, app = gateway
    original = store.authenticate

    def authenticate(token, audience="mcp"):
        if calls:
            raise XiaoxBindingError("cancelled", "task stopped")
        return original(token, audience)

    def limited(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": "0"})

    store.authenticate = authenticate
    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(limited),
        **kwargs,
    )
    assert post(client).status_code == 409 and len(calls) == 1
    assert ledger.get_model_wallet("71")["balance_units"] == 100
    assert not store.binding.metadata.get("model_reconciliation_required")


def test_sql_model_call_budget_survives_repository_reopen_and_new_generation(
    gateway, trusted_actor
):
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.infrastructure.xiaox.binding import XiaoxBindingStore
    from tests.test_application.test_xiaox_binding import make_binding

    client, _, calls, response, app = gateway
    actor = trusted_actor(user_id=71)
    route = replace(app.state.xiaox_model_route, max_model_calls=2)
    store, parent, grant = make_binding(actor, runtime_config=route.runtime_identity())
    app.state.xiaox_binding_store = store
    app.state.xiaox_model_route = route
    app.state.xiaox_run_id = parent.run_id

    def successful(request):
        assert ledger.get_model_wallet("71")["balance_units"] == 68 - 2 * len(calls)
        calls.append(request)
        return httpx.Response(200, json=response)

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(successful), **kwargs
    )

    def invoke(token):
        return client.post(
            MODEL_PATH,
            headers={"authorization": f"Bearer {token}"},
            json={"model": route.model, "input": "test"},
        )

    assert invoke(grant.model_token).status_code == 200
    assert invoke(grant.model_token).status_code == 200
    saved = store.repository.get(parent.run_id)
    metadata = saved.metadata["xiaox_runtime"]
    deadline = metadata["deadline_at"]
    requests = metadata["model_requests"]
    llm_calls = [call.to_dict() for call in saved.llm_calls]
    assert len(requests) == len(llm_calls) == 2
    assert {item["state"] for item in requests.values()} == {"completed"}

    for new_generation in (False, True):
        store = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=actor.factory))
        token = grant.model_token
        if new_generation:
            generation = grant.binding.metadata["generation"]
            store.close(parent.run_id, "waiting_user", generation=generation)
            replacement = store.create(parent.run_id, runtime_config=route.runtime_identity())
            assert replacement.binding.metadata["generation"] == generation + 1
            assert replacement.model_token != token
            token = replacement.model_token
        app.state.xiaox_binding_store = store
        rejected = invoke(token)
        assert rejected.status_code == 429 and "call limit" in rejected.json()["detail"]
        assert len(calls) == 2
        saved = store.repository.get(parent.run_id)
        assert saved.metadata["xiaox_runtime"]["deadline_at"] == deadline
        assert saved.metadata["xiaox_runtime"]["model_requests"] == requests
        assert [call.to_dict() for call in saved.llm_calls] == llm_calls
        assert saved.metadata["reserved_cost_units"] == 0
        assert saved.metadata["ai_cost_units_total"] == 4
        assert ledger.get_model_wallet("71")["balance_units"] == 96
        assert [run.run_id for run in store.repository.list_recent()] == [parent.run_id]


@pytest.fixture
def market_gateway(gateway, monkeypatch):
    client, store, calls, response, app = gateway
    route = replace(
        app.state.xiaox_model_route,
        model="enterprise/local-agent",
        gateway_kind="market",
        credential="account-secret",
        route_token="snapshot-secret",
        config_revision="rev-1",
        key_source="platform",
    )
    app.state.xiaox_model_route = route
    store.binding.metadata["runtime_config"] = route.runtime_identity()
    control = {"status": 200, "receipt": True, "attempts": True}
    monkeypatch.setattr(
        "app.infrastructure.billing.model_reservation.reserve_model_usage",
        lambda **kw: pytest.fail("platform request reserved wallet a second time"),
    )

    def handler(request):
        calls.append(request)
        assert ledger.get_model_wallet("71")["balance_units"] == 100
        assert request.headers["authorization"] == "Bearer account-secret"
        assert request.headers["x-xcmax-route-token"] == "snapshot-secret"
        request_id = request.headers["idempotency-key"]
        if control["status"] != 200:
            extra = {"json": control["body"]} if control.get("body") else {}
            return httpx.Response(control["status"], **extra)
        headers = (
            {"x-xcmax-upstream-attempts": "1", "x-xcmax-upstream-fallbacks": "0"}
            if control["attempts"]
            else {}
        )
        payload = dict(response)
        if control["receipt"]:
            payload["xcagi"] = {
                "schema": "xcmax.responses-billing.v1",
                "provider": "enterprise",
                "model": "local-agent",
                "key_source": "platform",
                "config_revision": "rev-1",
                "client_request_id": request_id,
                "request_id": "platform-" + request_id,
                "hold_no": "hold-" + request_id,
                "billed": True,
                "charge_amount": "0.02",
                "billing_status": "settled",
                "usage": response["usage"],
            }
        if b'"stream":true' in request.content:
            headers["content-type"] = "text/event-stream"
            data = json.dumps({"type": "response.completed", "response": payload})
            return httpx.Response(200, headers=headers, content=f"data: {data}\n\n")
        return httpx.Response(200, headers=headers, json=payload)

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        **kwargs,
    )
    return client, store, calls, response, app, control


@pytest.mark.parametrize("stream", [False, True])
def test_account_gateway_uses_platform_settlement_once_and_preserves_task_budget(
    market_gateway, stream
):
    client, store, calls, _, _, _ = market_gateway
    received = post(client, model="enterprise/local-agent", stream=stream)
    assert received.status_code == 200 and "error" not in received.text
    assert len(calls) == 1
    assert ledger.get_model_wallet("71")["balance_units"] == 100
    assert store.run.metadata["ai_cost_units_total"] == 2
    assert store.run.metadata["reserved_cost_units"] == 0
    entries = ledger.list_model_usage_entries(run_id=store.run.run_id)
    assert len(entries) == 1 and entries[0]["wallet_backend"] == "audit"
    assert store.run.llm_calls[0].total_tokens == 2000


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("zero_usage", [False, True])
def test_account_missing_settlement_blocks_tools_and_requires_reconciliation(
    market_gateway,
    stream,
    zero_usage,
):
    client, store, calls, response, _, control = market_gateway
    control["receipt"] = False
    if zero_usage:
        response["usage"] = dict.fromkeys(response["usage"], 0)
    response["output"] = [
        {
            "type": "function_call",
            "name": "mcp__xcmax__execute_action",
            "call_id": "must-not-run",
            "arguments": "{}",
        }
    ]
    received = post(client, model="enterprise/local-agent", stream=stream)
    assert received.status_code == (200 if stream else 409)
    assert "must-not-run" not in received.text
    assert store.binding.metadata["model_reconciliation_required"] is True
    assert post(client, model="enterprise/local-agent").status_code == 409
    assert len(calls) == 1 and ledger.get_model_wallet("71")["balance_units"] == 100


@pytest.mark.parametrize("status,unknown", [(401, False), (409, True), (502, True)])
def test_account_gateway_distinguishes_nonstarted_rejection_from_pending_receipt(
    market_gateway,
    status,
    unknown,
):
    client, store, calls, _, _, control = market_gateway
    control["status"] = status
    received = post(client, model="enterprise/local-agent")
    assert received.status_code == (502 if unknown else status)
    assert len(calls) == 1
    assert bool(store.binding.metadata.get("model_reconciliation_required")) is unknown
    assert ledger.get_model_wallet("71")["balance_units"] == 100
    if unknown:
        assert post(client, model="enterprise/local-agent").status_code == 409
        assert len(calls) == 1


def test_market_409_records_bounded_upstream_error_for_reconciliation(market_gateway):
    # 409 不能当成确定拒绝，但必须留下上游原因，供只读核对，不能靠猜测。
    client, store, calls, _, _, control = market_gateway
    control["status"] = 409
    control["body"] = {"code": "concurrent_limit", "message": "account has a pending request"}
    assert post(client, model="enterprise/local-agent").status_code == 502
    assert len(calls) == 1
    call = next(iter(store.binding.metadata["model_requests"].values()))
    assert call["state"] == "unknown"
    assert call["diagnostic"]["upstream_error"] == (
        '{"code":"concurrent_limit","message":"account has a pending request"}'
    )
    assert post(client, model="enterprise/local-agent").status_code == 409
    assert len(calls) == 1


def test_model_request_deadline_is_one_clock_for_headers_retries_and_reads(monkeypatch):
    monkeypatch.setenv("XCAGI_MODEL_REQUEST_TIMEOUT_SEC", "180")
    now = [1_000.0]
    monkeypatch.setattr("app.infrastructure.xiaox.model_gateway.time.monotonic", lambda: now[0])
    binding = SimpleNamespace(
        run=SimpleNamespace(metadata={}), metadata={"deadline_at": time.time() + 90}
    )
    deadline = model_request_deadline(binding)
    assert deadline == pytest.approx(1_090.0)
    now[0] = 1_089.0
    assert request_remaining(deadline) == pytest.approx(1.0, abs=1e-3)
    now[0] = 1_090.0
    with pytest.raises(ModelRequestTimeout):
        request_remaining(deadline)


def test_model_request_deadline_requires_a_live_task_deadline(monkeypatch):
    monkeypatch.setenv("XCAGI_MODEL_REQUEST_TIMEOUT_SEC", "180")
    binding = SimpleNamespace(
        run=SimpleNamespace(metadata={}), metadata={"deadline_at": time.time() - 1}
    )
    with pytest.raises(HTTPException) as caught:
        model_request_deadline(binding)
    assert caught.value.status_code == 408


def test_model_request_timeout_defaults_above_legacy_60s(monkeypatch):
    monkeypatch.delenv("XCAGI_MODEL_REQUEST_TIMEOUT_SEC", raising=False)
    assert model_request_timeout_seconds() == 180.0


def test_model_request_timeout_is_configurable_and_bounded(monkeypatch):
    monkeypatch.setenv("XCAGI_MODEL_REQUEST_TIMEOUT_SEC", "240")
    assert model_request_timeout_seconds() == 240.0
    monkeypatch.setenv("XCAGI_MODEL_REQUEST_TIMEOUT_SEC", "5")
    assert model_request_timeout_seconds() == 30.0
    monkeypatch.setenv("XCAGI_MODEL_REQUEST_TIMEOUT_SEC", "9999")
    assert model_request_timeout_seconds() == 600.0
    monkeypatch.setenv("XCAGI_MODEL_REQUEST_TIMEOUT_SEC", "abc")
    assert model_request_timeout_seconds() == 180.0
