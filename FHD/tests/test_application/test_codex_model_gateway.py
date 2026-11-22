"""Admission/settlement failures must stop provider I/O and future tool work."""

import time
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator.run_models import AgentRun
from app.infrastructure.billing import model_usage as ledger
from app.infrastructure.billing.model_reservation import settle_model_usage
from app.infrastructure.codex.model_gateway import MODEL_PATH, _finish, response_usage, router
from app.infrastructure.codex.policy import ModelRoute


class Store:
    def __init__(self, route):
        self.run = AgentRun(user_id="71", message="test")
        self.run.metadata["runtime_context"] = {"actor_id": "71", "tenant_id": "1"}
        self.run.metadata["codex_runtime"] = {
            "runtime_config": route.runtime_identity(),
            "deadline_at": time.time() + 60,
        }
        self.binding = SimpleNamespace(
            run=self.run,
            run_id=self.run.run_id,
            context=self.run.metadata["runtime_context"],
            metadata=self.run.metadata["codex_runtime"],
        )

    def authenticate(self, token, audience="mcp"):
        from app.infrastructure.codex.binding import CodexBindingError

        if token != "model-secret" or audience != "model":
            raise CodexBindingError("token_invalid", "wrong audience")
        return self.binding

    @contextmanager
    def scope(self, token, audience="mcp"):
        from app.infrastructure.llm.model_admission import model_rate_limit_scope

        with model_rate_limit_scope(self.binding.context):
            yield self.authenticate(token, audience)

    def update(self, run_id, mutation, **kwargs):
        assert run_id == self.run.run_id
        mutation(self.run, self.binding.metadata)
        return self.binding


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "local")
    monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "1")
    monkeypatch.setattr(
        "app.infrastructure.llm.model_admission.admit_model_call", lambda *a, **k: None
    )
    ledger.set_model_wallet_balance("71", 100)
    route = ModelRoute(
        base_url="http://127.0.0.1:9876/v1",
        model="local-agent",
        provider_id="enterprise",
        upstream_vendor="local",
        context_window=32000,
        max_output_tokens=4000,
    )
    store, calls = Store(route), []
    response = {
        "id": "resp_1",
        "status": "completed",
        "output": [],
        "usage": {"input_tokens": 1500, "output_tokens": 500, "total_tokens": 2000},
    }

    def handler(request):
        # Cost must be reserved atomically before a request reaches the model.
        assert ledger.get_model_wallet("71")["balance_units"] == 68
        calls.append(request)
        if b'"stream":true' in request.content:
            import json

            data = json.dumps({"type": "response.completed", "response": response})
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=f"data: {data}\n\n"
            )
        return httpx.Response(200, json=response)

    app = FastAPI()
    app.state.codex_binding_store = store
    app.state.codex_model_route = route
    app.state.codex_run_id = store.run.run_id
    app.state.codex_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        **kwargs,
    )
    app.include_router(router)
    with TestClient(app) as client:
        yield client, store, calls, response, app


def post(client, **body):
    return client.post(
        MODEL_PATH,
        headers={"authorization": "Bearer model-secret"},
        json={"model": "local-agent", "input": "test", **body},
    )


@pytest.mark.parametrize("stream", [False, True])
def test_wallet_reserved_before_io_and_actual_usage_settles_once(gateway, stream):
    client, store, calls, _, _ = gateway
    response = post(client, stream=stream)
    assert response.status_code == 200
    assert len(calls) == 1
    assert ledger.get_model_wallet("71")["balance_units"] == 98
    assert store.run.llm_calls[0].total_tokens == 2000
    row = next(iter(store.binding.metadata["model_requests"].values()))
    settle_model_usage(row["usage_key"], row["usage"])
    assert ledger.get_model_wallet("71")["balance_units"] == 98
    assert ledger.list_model_usage_entries(run_id=store.run.run_id)[0]["cost_units"] == 2


def test_missing_or_wrong_audience_never_contacts_provider(gateway):
    client, _, calls, _, _ = gateway
    assert client.post(MODEL_PATH, json={}).status_code == 401
    assert (
        client.post(MODEL_PATH, headers={"authorization": "Bearer mcp-secret"}, json={}).status_code
        == 403
    )
    assert not calls


@pytest.mark.parametrize(
    "body",
    [
        {"model": "gpt-fallback"},
        {"max_output_tokens": 4001},
        {"tools": [{"type": "web_search"}]},
        {"tools": [{"type": "function", "name": "shell"}]},
        {"previous_response_id": "another-tenants-response"},
    ],
)
def test_route_and_tools_cannot_be_changed_by_model(gateway, body):
    client, _, calls, _, _ = gateway
    assert post(client, **body).status_code in {400, 403, 409}
    assert not calls
    assert ledger.get_model_wallet("71")["balance_units"] == 100


def test_budget_denies_before_network_or_wallet_debit(gateway):
    client, store, calls, _, _ = gateway
    store.run.metadata["ai_cost_budget_units"] = 1
    assert post(client).status_code == 402
    assert not calls
    assert ledger.get_model_wallet("71")["balance_units"] == 100


def test_insufficient_wallet_does_not_call_model(gateway):
    client, _, calls, _, _ = gateway
    ledger.set_model_wallet_balance("71", 1)
    assert post(client).status_code == 402
    assert not calls
    assert ledger.get_model_wallet("71")["balance_units"] == 1


def test_missing_usage_is_unknown_and_blocks_next_call(gateway):
    client, store, calls, response, _ = gateway
    response.pop("usage")
    assert post(client).status_code == 502
    assert store.binding.metadata["model_reconciliation_required"]
    assert post(client).status_code == 409
    assert len(calls) == 1
    assert ledger.get_model_wallet("71")["balance_units"] == 68


def test_usage_event_replay_does_not_double_count(gateway):
    client, store, _, _, _ = gateway
    assert post(client).status_code == 200
    key, row = next(iter(store.binding.metadata["model_requests"].items()))
    _finish(store, store.run.run_id, key, usage=row["usage"], usage_key=row["usage_key"])
    assert len(store.run.llm_calls) == 1
    assert store.run.metadata["ai_cost_units_total"] == 2


def test_redirect_never_follows_or_leaks_gateway_token(gateway):
    client, store, _, _, app = gateway
    seen = []

    def redirect(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://api.openai.com/v1/responses"})

    app.state.codex_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(redirect),
        **kwargs,
    )
    assert post(client).status_code == 502
    assert seen == ["http://127.0.0.1:9876/v1/responses"]
    assert store.binding.metadata["model_reconciliation_required"]


def test_unknown_usage_is_not_zero():
    assert response_usage({}) is None
    assert response_usage({"usage": {"input_tokens": -1, "output_tokens": 10}}) is None


def test_another_task_token_cannot_use_this_private_gateway(gateway):
    client, _, calls, _, app = gateway
    app.state.codex_run_id = "another-parent"
    assert post(client).status_code == 403
    assert not calls
    assert ledger.get_model_wallet("71")["balance_units"] == 100


def test_child_budget_hold_is_counted_before_model_admission(gateway):
    client, store, calls, _, _ = gateway
    store.run.metadata.update(ai_cost_budget_units=40, reserved_cost_units=10)
    assert post(client).status_code == 402
    assert not calls
    assert store.run.metadata["reserved_cost_units"] == 10
    assert ledger.get_model_wallet("71")["balance_units"] == 100


def test_revocation_after_reservation_before_io_releases_unused_hold(gateway):
    from app.infrastructure.codex.binding import CodexBindingError

    client, store, calls, _, _ = gateway
    authenticate = store.authenticate

    def revoked(token, audience="mcp"):
        if ledger.get_model_wallet("71")["balance_units"] < 100:
            raise CodexBindingError("cancelled", "cancelled before sending")
        return authenticate(token, audience)

    store.authenticate = revoked
    assert post(client).status_code == 409
    assert not calls
    assert store.run.metadata["reserved_cost_units"] == 0
    assert ledger.get_model_wallet("71")["balance_units"] == 100
    assert not store.binding.metadata.get("model_reconciliation_required")


def test_gateway_error_is_reported_to_existing_circuit_breaker(gateway, monkeypatch):
    client, _, _, _, app = gateway
    failures = []

    @contextmanager
    def slot(*args, **kwargs):
        try:
            yield
        except httpx.HTTPStatusError as exc:
            failures.append(exc.response.status_code)
            raise

    monkeypatch.setattr("app.infrastructure.llm.model_admission.model_call_slot", slot)
    app.state.codex_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503)),
        **kwargs,
    )
    assert post(client).status_code == 502
    assert failures == [503]


def test_market_unused_reservation_retries_same_refund_then_settles_once(gateway, monkeypatch):
    from app.infrastructure.billing.model_reservation import (
        ModelReservationError,
        reserve_model_usage,
    )

    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
    monkeypatch.setattr(
        ledger,
        "_apply_market_wallet_debit",
        lambda **kwargs: (
            "debited",
            {"status": "debited", "hold_no": "H", "amount_yuan": "0.32"},
        ),
    )
    requests = []

    def release(**kwargs):
        requests.append(kwargs)
        return ("refund_pending", {}) if len(requests) == 1 else ("refunded", {"hold_no": "H"})

    monkeypatch.setattr(ledger, "_apply_market_wallet_refund", release)
    reserve_model_usage(
        usage_key="reserved",
        run_id="run",
        user_id="71",
        provider_id="local",
        model="model",
        token_ceiling=32000,
    )
    usage = {"prompt_tokens": 1500, "completion_tokens": 500, "total_tokens": 2000}
    with pytest.raises(ModelReservationError):
        settle_model_usage("reserved", usage)
    entry = ledger.list_model_usage_entries(run_id="run")[0]
    assert entry["cost_units"] == 32
    assert entry["metadata"]["usage_status"] == "settlement_pending"
    assert settle_model_usage("reserved", usage)["cost_units"] == 2
    assert settle_model_usage("reserved", usage)["cost_units"] == 2
    assert len(requests) == 2
    assert {request["refund_key"] for request in requests} == {"reserved:unused"}
    assert str(requests[0]["amount_yuan"]) == "0.30"


def test_concurrent_usage_replays_refund_local_wallet_only_once(gateway):
    from concurrent.futures import ThreadPoolExecutor

    from app.infrastructure.billing.model_reservation import reserve_model_usage

    reserve_model_usage(
        usage_key="concurrent",
        run_id="run",
        user_id="71",
        provider_id="local",
        model="model",
        token_ceiling=32000,
    )
    usage = {"prompt_tokens": 1500, "completion_tokens": 500, "total_tokens": 2000}
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: settle_model_usage("concurrent", usage), range(8)))
    assert all(row["cost_units"] == 2 for row in rows)
    assert ledger.get_model_wallet("71")["balance_units"] == 98


def test_pinned_cli_helpers_are_not_advertised_to_the_model(gateway):
    import json

    client, _, calls, _, _ = gateway
    bridge = {
        "type": "namespace",
        "name": "mcp__xcmax",
        "tools": [
            {"type": "function", "name": "request_input", "parameters": {"type": "object"}},
        ],
    }
    assert (
        post(client, tools=[{"type": "function", "name": "request_user_input"}, bridge]).status_code
        == 200
    )
    assert json.loads(calls[0].content)["tools"] == [bridge]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "item",
    [
        {"type": "function_call", "name": "view_image", "arguments": "{}"},
        {
            "type": "function_call",
            "name": "mcp__xcmax__request_input",
            "namespace": "another_server",
        },
        {"type": "local_shell_call", "action": {"command": ["echo", "blocked"]}},
        {"type": "function_call_output", "call_id": "fake", "output": "business completed"},
    ],
)
def test_unadvertised_native_or_forged_tool_proposals_never_reach_runtime(gateway, stream, item):
    client, store, _, response, _ = gateway
    response["output"] = [item]
    received = post(client, stream=stream)
    assert received.status_code == (200 if stream else 502)
    assert (
        "Model stream requires reconciliation" in received.text
        if stream
        else "invalid response" in received.text
    )
    assert '"output"' not in received.text
    assert store.binding.metadata["model_reconciliation_required"]
    assert post(client).status_code == 409


@pytest.mark.parametrize(
    "name,namespace",
    [
        ("request_input", "mcp__xcmax"),
        ("mcp__xcmax__request_input", None),
    ],
)
def test_real_responses_namespace_and_flat_mcp_call_formats_are_allowed(gateway, name, namespace):
    client, _, _, response, _ = gateway
    response["output"] = [
        {
            "type": "function_call",
            "name": name,
            "namespace": namespace,
            "call_id": "request",
            "arguments": '{"question":"date?"}',
        }
    ]
    assert post(client).status_code == 200


def test_connect_failure_retries_on_same_route_and_charges_each_attempt_once(gateway):
    client, store, calls, response, app = gateway

    def flaky(request):
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ConnectError("no connection", request=request)
        return httpx.Response(200, json=response)

    app.state.codex_http_client_factory = lambda **kwargs: httpx.AsyncClient(
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

    app.state.codex_http_client_factory = lambda **kwargs: httpx.AsyncClient(
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

    app.state.codex_http_client_factory = lambda **kwargs: httpx.AsyncClient(
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
    from app.infrastructure.codex.binding import CodexBindingError

    client, store, calls, _, app = gateway
    original = store.authenticate

    def authenticate(token, audience="mcp"):
        if calls:
            raise CodexBindingError("cancelled", "task stopped")
        return original(token, audience)

    def limited(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": "0"})

    store.authenticate = authenticate
    app.state.codex_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(limited),
        **kwargs,
    )
    assert post(client).status_code == 409 and len(calls) == 1
    assert ledger.get_model_wallet("71")["balance_units"] == 100
    assert not store.binding.metadata.get("model_reconciliation_required")
