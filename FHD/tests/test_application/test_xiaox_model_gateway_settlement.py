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


def test_market_schema_rejection_is_terminal_and_closes_the_model_event(market_gateway):
    client, store, _, _, _, control = market_gateway
    control.update(status=422, body={"detail": {"code": "CODEX_RESPONSE_SCHEMA_REJECTED"}})
    response = post(client, model="enterprise/local-agent")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CODEX_RESPONSE_SCHEMA_REJECTED"
    request_id, call = next(iter(store.binding.metadata["model_requests"].items()))
    assert call["state"] == "failed" and call["diagnostic"]["outcome"] == "not_started"
    assert not store.binding.metadata["model_reconciliation_required"]
    events = [
        (event.event_type, event.data.get("model_request_id"))
        for event in store.run.events
        if event.event_type.startswith("runtime.model.")
    ]
    assert events == [
        ("runtime.model.started", request_id),
        ("runtime.model.failure", request_id),
        ("runtime.model.failed", request_id),
    ]


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


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf"])
def test_nonfinite_request_timeout_cannot_disable_the_deadline(monkeypatch, raw):
    monkeypatch.setenv("XCAGI_MODEL_REQUEST_TIMEOUT_SEC", raw)
    assert model_request_timeout_seconds() == 180.0


@pytest.mark.parametrize("as_date", [False, True])
def test_provider_retry_after_exceeding_task_budget_is_returned_without_replay(gateway, as_date):
    from email.utils import formatdate

    client, store, calls, _, app = gateway
    hint = formatdate(time.time() + 180, usegmt=True) if as_date else "180"

    def limited(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": hint})

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(limited), **kwargs
    )
    response = post(client)
    assert response.status_code == 429
    assert 179 <= int(response.headers["retry-after"]) <= 180
    assert len(calls) == 1
    assert ledger.get_model_wallet("71")["balance_units"] == 100
    assert not store.binding.metadata.get("model_reconciliation_required")


def test_request_trace_and_phase_limits_follow_the_same_run(gateway, monkeypatch):
    client, store, calls, _, _ = gateway
    for phase, seconds in {"connect": 2, "pool": 3, "write": 4, "read": 5}.items():
        monkeypatch.setenv(f"XCAGI_MODEL_{phase.upper()}_TIMEOUT_SEC", str(seconds))
    assert post(client).status_code == 200
    assert calls[0].extensions["timeout"] == {"connect": 2, "pool": 3, "write": 4, "read": 5}
    row = next(iter(store.binding.metadata["model_requests"].values()))
    assert row["trace_id"] == store.run.to_dict()["trace_id"]
    assert row["provider_response_id"] == "resp_1"
    assert row["response_headers_ms"] <= row["duration_ms"]
    assert row["finished_at"] >= row["started_at"]


@pytest.mark.parametrize(
    "status,slow_phase", [(200, "inference"), (503, "inference"), (200, "response")]
)
def test_real_http_slow_headers_and_body_share_bounded_phase_deadlines(
    gateway, monkeypatch, status, slow_phase
):
    """Use a real loopback socket; byte activity must not refresh the absolute clock."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    client, store, _, _, app = gateway
    received = []
    stopped = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            received.append(self.path)
            self.rfile.read(int(self.headers["content-length"]))
            if slow_phase == "response":
                stopped.wait(1)
            self.send_response(status)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            try:
                for _ in range(1000):
                    if stopped.wait(0.02):
                        break
                    self.wfile.write(b" ")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    worker.start()
    route = replace(
        app.state.xiaox_model_route, base_url=f"http://127.0.0.1:{server.server_port}/v1"
    )
    app.state.xiaox_model_route = route
    store.binding.metadata["runtime_config"] = route.runtime_identity()
    app.state.xiaox_http_client_factory = httpx.AsyncClient
    monkeypatch.setenv(f"XCAGI_MODEL_{slow_phase.upper()}_TIMEOUT_SEC", "0.1")
    started = time.monotonic()
    try:
        response = post(client)
        assert response.status_code == 504
        assert time.monotonic() - started < 1
        assert received == ["/v1/responses"]
        row = next(iter(store.binding.metadata["model_requests"].values()))
        assert row["state"] == "unknown"
        assert row["diagnostic"]["request_phase"] == slow_phase
        assert store.binding.metadata["model_reconciliation_required"]
        assert post(client).status_code == 409
        assert received == ["/v1/responses"]
    finally:
        stopped.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


@pytest.mark.asyncio
async def test_disconnect_during_backoff_stops_the_original_request():
    from starlette.requests import Request

    from app.infrastructure.xiaox.model_gateway import _wait_for_model_retry

    async def disconnected():
        return {"type": "http.disconnect"}

    request = Request({"type": "http"}, receive=disconnected)
    started = time.monotonic()
    assert not await _wait_for_model_retry(request, 60)
    assert time.monotonic() - started < 0.1


def authorize_backup(app, store):
    primary = app.state.xiaox_model_route
    backup = replace(
        primary, model="backup-agent", response_model="backup-agent", provider_id="backup"
    )
    app.state.xiaox_model_routes = (primary, backup)
    store.binding.metadata["runtime_config"]["authorized_model_routes"] = [
        primary.identity,
        backup.identity,
    ]
    return primary, backup


@pytest.mark.parametrize("failure", ["connect", "rate_limit"])
def test_authorized_fallback_preserves_payload_budget_and_sticks_to_effective_route(
    gateway, monkeypatch, failure
):
    client, store, calls, response, app = gateway
    primary, backup = authorize_backup(app, store)
    from app.infrastructure.xiaox import model_gateway

    async def no_wait(*args):
        return True

    monkeypatch.setattr(model_gateway, "_wait_for_model_retry", no_wait)
    history = [
        {"role": "user", "content": "continue original task; do not repeat its completed tool"}
    ]

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["model"] == primary.model:
            if failure == "connect":
                raise httpx.ConnectError("not sent", request=request)
            return httpx.Response(429)
        return httpx.Response(200, json={**response, "model": backup.response_model})

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(respond), **kwargs
    )
    assert post(client, input=history).status_code == 200
    assert [item["model"] for item in calls] == [primary.model, backup.model]
    assert calls[0]["input"] == calls[1]["input"] == history
    assert calls[0]["tools"] == calls[1]["tools"]
    attempts = list(store.binding.metadata["model_requests"].values())
    assert len({item["request_group"] for item in attempts}) == 1
    assert [item["state"] for item in attempts] == ["failed", "completed"]
    assert [item["model"] for item in attempts] == [primary.model, backup.model]
    assert store.run.metadata["runtime_effective_model_route"] == backup.identity
    assert ledger.get_model_wallet("71")["balance_units"] == 98
    # New provider-bound context stays on the selected route on later requests.
    opaque = [{"type": "reasoning", "encrypted_content": "backup-private-state", "summary": []}]
    assert post(client, input=opaque).status_code == 200
    assert [item["model"] for item in calls] == [primary.model, backup.model, backup.model]
    assert calls[-1]["input"] == opaque
    assert store.binding.metadata["runtime_config"]["model"] == primary.model


@pytest.mark.parametrize(
    "history",
    [
        [{"id": "provider-saved-item"}],
        [{"type": "reasoning", "summary": []}],
        [{"type": "compaction", "encrypted_content": "state"}],
        [{"type": "message", "role": "user", "content": [{"type": "input_file", "file_id": "f1"}]}],
        [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_image", "image_url": "data:image/png;base64,eA=="}],
            }
        ],
        [{"type": "function_call_output", "call_id": "missing-original-call", "output": "done"}],
    ],
)
def test_nonportable_context_never_crosses_a_model_route(gateway, monkeypatch, history):
    client, store, calls, _, app = gateway
    primary, _ = authorize_backup(app, store)
    from app.infrastructure.xiaox import model_gateway

    async def no_wait(*args):
        return True

    monkeypatch.setattr(model_gateway, "_wait_for_model_retry", no_wait)

    def reject(request):
        calls.append(json.loads(request.content))
        return httpx.Response(429)

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(reject), **kwargs
    )
    assert post(client, input=history).status_code == 429
    assert len(calls) == 3
    assert {item["model"] for item in calls} == {primary.model}
    assert all(item["input"] == history for item in calls)
    assert store.run.metadata["runtime_effective_model_route"] == primary.identity


@pytest.mark.parametrize("failure", ["read_timeout", "server_error", "forbidden"])
def test_authorized_backup_does_not_permit_replaying_an_unknown_or_denied_request(gateway, failure):
    client, store, calls, _, app = gateway
    primary, _ = authorize_backup(app, store)

    def fail(request):
        calls.append(json.loads(request.content))
        if failure == "read_timeout":
            raise httpx.ReadTimeout("unknown", request=request)
        return httpx.Response(503 if failure == "server_error" else 403)

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(fail), **kwargs
    )
    assert post(client).status_code == (403 if failure == "forbidden" else 502)
    assert [item["model"] for item in calls] == [primary.model]


def test_live_candidate_list_cannot_expand_the_tasks_bound_authorization(gateway):
    client, store, calls, _, app = gateway
    authorize_backup(app, store)
    store.binding.metadata["runtime_config"].pop("authorized_model_routes")
    assert post(client).status_code == 409 and not calls


def test_plain_business_file_identifiers_do_not_block_a_self_contained_tool_history():
    from app.infrastructure.xiaox.model_gateway import _portable_fallback_body

    body = {
        "tools": [{"parameters": {"properties": {"file_id": {"type": "string"}}}}],
        "input": [
            {
                "type": "function_call",
                "call_id": "c1",
                "name": "mcp__xcmax__task_evidence",
                "arguments": '{"file_id":"business-id"}',
            },
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": '{"file_id":"business-id","done":true}',
            },
        ],
    }
    assert _portable_fallback_body(body)
    assert not _portable_fallback_body({**body, "prompt": {"id": "provider-template"}})


def test_backup_capacity_does_not_expand_the_original_output_or_call_budget(gateway, monkeypatch):
    from app.infrastructure.xiaox import model_gateway

    client, store, calls, response, app = gateway
    primary, backup = authorize_backup(app, store)
    backup = replace(backup, max_output_tokens=8000, max_model_calls=100)
    app.state.xiaox_model_routes = (primary, backup)
    config = store.binding.metadata["runtime_config"]
    config.update(authorized_model_routes=[primary.identity, backup.identity], max_model_calls=2)

    async def no_wait(*args):
        return True

    monkeypatch.setattr(model_gateway, "_wait_for_model_retry", no_wait)

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        return (
            httpx.Response(429)
            if len(calls) == 1
            else httpx.Response(200, json={**response, "model": backup.model})
        )

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(respond), **kwargs
    )
    assert post(client).status_code == 200
    assert [item["max_output_tokens"] for item in calls] == [primary.max_output_tokens] * 2
    assert post(client).status_code == 429
    assert len(calls) == 2


def test_fallback_retry_leaves_verification_inside_original_call_ceiling(gateway, monkeypatch):
    from app.application.agent_runtime.verification_budget import initialize_verification_budget
    from app.infrastructure.xiaox import model_gateway
    from tests.test_application.test_goal_verification_budget import post_review, reviewing

    client, store, calls, response, app = gateway
    primary, backup = authorize_backup(app, store)
    backup = replace(backup, max_model_calls=100)
    app.state.xiaox_model_routes = (primary, backup)
    metadata = store.binding.metadata
    metadata["runtime_config"].update(
        authorized_model_routes=[primary.identity, backup.identity], max_model_calls=4
    )
    metadata["model_requests"] = {
        str(index): {"state": "completed", "purpose": "execution"} for index in range(2)
    }
    initialize_verification_budget(
        store.run, metadata, context_window=32000, max_model_calls=4, total_seconds=60
    )

    async def no_wait(*args):
        return True

    monkeypatch.setattr(model_gateway, "_wait_for_model_retry", no_wait)

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(429) if len(calls) == 1 else httpx.Response(200, json=response)

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(respond), **kwargs
    )
    refused = post(client)
    assert refused.status_code == 429 and "reserved" in refused.text
    assert len(calls) == 1 and len(metadata["model_requests"]) == 3
    assert store.run.metadata["runtime_effective_model_route"] == primary.identity
    reviewing(store.run, metadata)
    assert post_review(client).status_code == 200
    assert len(calls) == 2 and len(metadata["model_requests"]) == 4
    receipt = list(metadata["model_requests"].values())[-1]
    assert receipt["purpose"] == "verification" and receipt["state"] == "completed"
    assert receipt["verification_response"] == response
    assert post_review(client).status_code == 429 and len(calls) == 2


def test_verification_fallback_keeps_job_receipt_and_actual_route_observation(gateway, monkeypatch):
    from app.application.agent_runtime.verification_budget import initialize_verification_budget
    from app.infrastructure.xiaox import model_gateway
    from tests.test_application.test_goal_verification_budget import post_review, reviewing

    client, store, calls, response, app = gateway
    primary, backup = authorize_backup(app, store)
    metadata = store.binding.metadata
    initialize_verification_budget(
        store.run, metadata, context_window=32000, max_model_calls=8, total_seconds=60
    )
    reviewing(store.run, metadata)

    async def no_wait(*args):
        return True

    monkeypatch.setattr(model_gateway, "_wait_for_model_retry", no_wait)

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={**response, "model": backup.response_model})

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(respond), **kwargs
    )
    assert post_review(client).status_code == 200
    attempts = list(metadata["model_requests"].values())
    assert [row["model"] for row in attempts] == [primary.model, backup.model]
    assert [row["state"] for row in attempts] == ["failed", "completed"]
    assert all(row["purpose"] == "verification" for row in attempts)
    assert all(row["verification_job_id"] == "verify-original" for row in attempts)
    assert len({row["request_group"] for row in attempts}) == 1
    assert [row["observation"]["route_identity"] for row in attempts] == [
        primary.identity,
        backup.identity,
    ]
    assert "verification_response" not in attempts[0]
    assert attempts[1]["verification_response"]["model"] == backup.response_model
    assert ledger.get_model_wallet("71")["balance_units"] == 98


def test_effective_route_change_during_backoff_cannot_move_another_requests_context(
    gateway, monkeypatch
):
    from app.infrastructure.xiaox import model_gateway

    client, store, calls, _, app = gateway
    _, backup = authorize_backup(app, store)

    async def concurrent_change(*args):
        store.run.metadata["runtime_effective_model_route"] = backup.identity
        return True

    monkeypatch.setattr(model_gateway, "_wait_for_model_retry", concurrent_change)

    def reject(request):
        calls.append(request)
        return httpx.Response(429)

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(reject), **kwargs
    )
    assert post(client).status_code == 409
    assert len(calls) == 1


def test_market_deadline_uses_signed_budget_and_propagates_parent_ceiling(
    market_gateway, monkeypatch
):
    client, store, calls, response, app, control = market_gateway
    monkeypatch.delenv("XCAGI_MODEL_REQUEST_TIMEOUT_SEC", raising=False)
    route = replace(app.state.xiaox_model_route, request_timeout_seconds=300)
    app.state.xiaox_model_route = route
    store.binding.metadata["runtime_config"] = route.runtime_identity()
    assert model_request_timeout_seconds(route) == 300
    result = post(client, model="enterprise/local-agent")
    assert result.status_code == 200, result.text
    deadline = int(calls[0].headers["x-xcmax-request-deadline-ms"]) / 1000
    assert time.time() < deadline <= store.binding.metadata["deadline_at"] + 0.1
    monkeypatch.setenv("XCAGI_MODEL_REQUEST_TIMEOUT_SEC", "600")
    assert model_request_timeout_seconds(route) == 300
    monkeypatch.setenv("XCAGI_MODEL_REQUEST_TIMEOUT_SEC", "30")
    assert model_request_timeout_seconds(route) == 30


@pytest.mark.parametrize(
    "defect", [None, "foreign_request", "changed_config", "missing_usage", "unverified_attempts"]
)
def test_original_market_receipt_reconciles_once_without_model_or_tool_replay(
    market_gateway, monkeypatch, defect
):
    from app.application.market_llm.protocols import Connection
    from app.infrastructure.xiaox.receipt_projection import reconcile_model_receipts

    client, store, calls, response, app, control = market_gateway
    control["status"] = 503
    assert post(client, model="enterprise/local-agent").status_code == 502
    key, original = next(iter(store.binding.metadata["model_requests"].items()))
    store.run.status = "blocked"
    receipt = {
        "schema": "xcmax.responses-billing.v1",
        "provider": "enterprise",
        "model": "local-agent",
        "key_source": "platform",
        "config_revision": "rev-1",
        "client_request_id": key,
        "request_id": "original-platform-request",
        "hold_no": "original-hold",
        "billed": True,
        "charge_amount": "0.02",
        "billing_status": "settled",
        "usage": response["usage"],
    }
    if defect == "foreign_request":
        receipt["client_request_id"] = "another-request"
    if defect == "changed_config":
        receipt["config_revision"] = "different-revision"
    payload = {**response, "xcagi": receipt}
    if defect == "missing_usage":
        payload.pop("usage")
    headers = {"X-XCMax-Upstream-Attempts": "1", "X-XCMax-Upstream-Fallbacks": "0"}
    if defect == "unverified_attempts":
        headers.clear()
    reads = []
    real_client = httpx.Client

    def read(request):
        reads.append(request)
        assert request.method == "GET" and request.url.path.endswith("/" + key)
        assert request.headers["authorization"] == "Bearer original-account-session"
        return httpx.Response(
            200,
            json={
                "state": "completed",
                "client_request_id": key,
                "response": payload,
                "headers": headers,
            },
        )

    monkeypatch.setattr(
        "app.application.agent_runtime.configuration._account_connection",
        lambda owner: Connection("https://market.example", "original-account-session", None, 5),
    )
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(read), **kw)
    )
    reconcile_model_receipts(store, store.run)
    reconcile_model_receipts(store, store.run)
    assert len(reads) == 1 and len(calls) == 1
    assert store.run.status == "blocked" and not store.run.tool_calls
    if defect:
        assert (
            original["state"] == "unknown"
            and store.binding.metadata["model_reconciliation_required"]
        )
        assert not store.run.llm_calls
    else:
        assert original["state"] == "completed"
        assert not store.binding.metadata["model_reconciliation_required"]
        assert original["reconciled_response"]["xcagi"]["client_request_id"] == key
        assert len(store.run.llm_calls) == 1 and store.run.metadata["reserved_cost_units"] == 0
    assert ledger.get_model_wallet("71")["balance_units"] == 100
