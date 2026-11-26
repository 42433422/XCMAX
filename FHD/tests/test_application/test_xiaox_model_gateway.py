"""Admission/settlement failures must stop provider I/O and future tool work."""

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


class Store:
    def __init__(self, route):
        self.run = AgentRun(user_id="71", message="test")
        self.run.metadata["runtime_context"] = {"actor_id": "71", "tenant_id": "1"}
        self.run.metadata["xiaox_runtime"] = {
            "runtime_config": route.runtime_identity(),
            "deadline_at": time.time() + 60,
        }
        self.binding = SimpleNamespace(
            run=self.run,
            run_id=self.run.run_id,
            context=self.run.metadata["runtime_context"],
            metadata=self.run.metadata["xiaox_runtime"],
        )
        self.route_max_model_calls = route.max_model_calls

    def get(self, run_id):
        assert run_id == self.run.run_id
        return self.binding

    def authenticate(self, token, audience="mcp"):
        from app.infrastructure.xiaox.binding import XiaoxBindingError

        if token != "model-secret" or audience != "model":
            raise XiaoxBindingError("token_invalid", "wrong audience")
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
        "model": route.response_model,
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
    app.state.xiaox_binding_store = store
    app.state.xiaox_model_route = route
    app.state.xiaox_run_id = store.run.run_id
    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
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
        {"allow_failover": True},
        {"disable_fallbacks": False},
        {"num_retries": 5},
        {"extra_body": {"disable_fallbacks": False}},
        {"provider": {"order": ["another-provider"]}},
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

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(redirect),
        **kwargs,
    )
    assert post(client).status_code == 502
    assert seen == ["http://127.0.0.1:9876/v1/responses"]
    assert store.binding.metadata["model_reconciliation_required"]


def test_model_call_budget_refusal_is_committed_as_a_readable_stop_reason(gateway):
    client, store, calls, _, _ = gateway
    store.binding.metadata["model_requests"] = {
        f"call-{index}": {"state": "completed"} for index in range(store.route_max_model_calls)
    }
    assert post(client).status_code == 429
    assert not calls
    limit = store.binding.metadata.get("model_call_limit")
    assert limit and limit["reason"] == "model_call_budget_exhausted"
    assert limit["max_model_calls"] == store.route_max_model_calls


def test_unknown_usage_is_not_zero():
    assert response_usage({}) is None
    assert response_usage({"usage": {"input_tokens": -1, "output_tokens": 10}}) is None


def test_another_task_token_cannot_use_this_private_gateway(gateway):
    client, _, calls, _, app = gateway
    app.state.xiaox_run_id = "another-parent"
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
    from app.infrastructure.xiaox.binding import XiaoxBindingError

    client, store, calls, _, _ = gateway
    authenticate = store.authenticate

    def revoked(token, audience="mcp"):
        if ledger.get_model_wallet("71")["balance_units"] < 100:
            raise XiaoxBindingError("cancelled", "cancelled before sending")
        return authenticate(token, audience)

    store.authenticate = revoked
    assert post(client).status_code == 409
    assert not calls
    assert store.run.metadata["reserved_cost_units"] == 0
    assert ledger.get_model_wallet("71")["balance_units"] == 100
    assert not store.binding.metadata.get("model_reconciliation_required")


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("stop", ["revoked", "deadline"])
def test_final_authority_and_deadline_fence_output_after_real_usage_settlement(
    gateway, monkeypatch, stream, stop
):
    from app.infrastructure.xiaox.binding import XiaoxBindingError

    client, store, calls, response, _app = gateway
    response["output"] = [
        {
            "type": "function_call",
            "name": "mcp__xcmax__execute_action",
            "call_id": "stopped-before-release",
            "arguments": "{}",
        }
    ]
    authenticate = store.authenticate
    settled = False

    def current_authority(token, audience="mcp"):
        if settled and stop == "revoked":
            raise XiaoxBindingError("cancelled", "revoked while model response was pending")
        return authenticate(token, audience)

    def settle_then_stop(usage_key, usage):
        nonlocal settled
        receipt = settle_model_usage(usage_key, usage)
        settled = True
        if stop == "deadline":
            store.binding.metadata["deadline_at"] = time.time() - 1
        return receipt

    store.authenticate = current_authority
    monkeypatch.setattr(
        "app.infrastructure.billing.model_reservation.settle_model_usage", settle_then_stop
    )
    received = post(client, stream=stream)
    assert received.status_code == (200 if stream else 409 if stop == "revoked" else 408)
    assert "stopped-before-release" not in received.text
    assert settled and len(calls) == 1
    row = next(iter(store.binding.metadata["model_requests"].values()))
    assert row["state"] == "completed" and row["usage"]["total_tokens"] == 2000
    assert store.run.metadata["reserved_cost_units"] == 0
    assert not store.binding.metadata.get("model_reconciliation_required")
    assert len(store.run.llm_calls) == 1 and store.run.llm_calls[0].total_tokens == 2000
    assert ledger.get_model_wallet("71")["balance_units"] == 98


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
    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
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


@pytest.mark.parametrize("model", [None, "unexpected-fallback-model"])
@pytest.mark.parametrize("stream", [False, True])
def test_wrong_or_missing_response_model_cannot_drive_tools(gateway, model, stream):
    client, store, calls, response, _app = gateway
    response["model"] = model
    response["output"] = [
        {
            "type": "function_call",
            "name": "mcp__xcmax__execute_action",
            "call_id": "never-visible",
            "arguments": "{}",
        }
    ]
    received = post(client, stream=stream)
    assert received.status_code == (200 if stream else 502)
    assert "never-visible" not in received.text
    assert len(calls) == 1
    attempt = next(iter(store.binding.metadata["model_requests"].values()))
    assert attempt["state"] == "failed" and attempt["model_identity_verified"] is False
    assert attempt["diagnostic"]["failure_kind"] == "model_identity_mismatch"
    assert store.run.llm_calls[0].metadata["observed_model"] == model
    assert ledger.get_model_wallet("71")["balance_units"] == 98


def test_qualified_alias_records_actual_response_identity(gateway):
    client, store, calls, response, app = gateway
    route = replace(app.state.xiaox_model_route, response_model="local-agent-snapshot")
    app.state.xiaox_model_route = route
    store.binding.metadata["runtime_config"] = route.runtime_identity()
    response["model"] = route.response_model
    assert post(client).status_code == 200
    wire = json.loads(calls[0].content)
    assert wire["model"] == "local-agent"
    assert not {"disable_fallbacks", "num_retries", "allow_failover"} & wire.keys()
    assert store.run.llm_calls[0].model == "local-agent-snapshot"
    assert store.run.llm_calls[0].metadata["requested_model"] == "local-agent"
    assert store.run.llm_calls[0].metadata["model_identity_verified"] is True


def test_pinned_cli_trace_metadata_is_not_forwarded_as_a_provider_option(gateway):
    client, _store, calls, _response, _app = gateway
    assert post(client, client_metadata={"private_trace": "host-only"}).status_code == 200
    assert "client_metadata" not in json.loads(calls[0].content)
    assert b"host-only" not in calls[0].content


def test_mimo_structured_output_uses_supported_object_format(gateway):
    client, store, calls, response, app = gateway
    route = replace(
        app.state.xiaox_model_route,
        model="mimo-v2.6-pro",
        response_model="mimo-v2.6-pro",
        upstream_vendor="xiaomi",
    )
    app.state.xiaox_model_route = route
    store.binding.metadata["runtime_config"] = route.runtime_identity()
    response["model"] = route.response_model
    schema = {"type": "object", "required": ["action"], "additionalProperties": False}
    result = post(
        client,
        model=route.model,
        instructions="Original host instructions",
        text={"format": {"type": "json_schema", "name": "proposal", "schema": schema}},
    )
    assert result.status_code == 200
    wire = json.loads(calls[0].content)
    assert wire["text"]["format"] == {"type": "json_object"}
    assert wire["instructions"].startswith("Original host instructions\n\n")
    assert json.loads(wire["instructions"].splitlines()[-1]) == schema


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("proof", ["zero", "missing", "nonzero", "duplicate"])
def test_litellm_controls_and_native_single_attempt_proof(gateway, stream, proof):
    client, store, calls, response, app = gateway
    route = replace(app.state.xiaox_model_route, gateway_kind="litellm")
    app.state.xiaox_model_route = route
    store.binding.metadata["runtime_config"] = route.runtime_identity()
    response["output"] = [
        {
            "type": "function_call",
            "name": "mcp__xcmax__request_input",
            "call_id": "qualified-only",
            "arguments": "{}",
        }
    ]

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["num_retries"] == 0 and body["disable_fallbacks"] is True
        assert "allow_failover" not in body and "extra_body" not in body
        headers = (
            []
            if proof == "missing"
            else [
                ("x-litellm-attempted-retries", "0"),
                ("x-litellm-attempted-fallbacks", "1" if proof == "nonzero" else "0"),
            ]
        )
        if proof == "duplicate":
            headers.append(("x-litellm-attempted-fallbacks", "0"))
        if stream:
            return httpx.Response(
                200,
                headers=[*headers, ("content-type", "text/event-stream")],
                content="data: "
                + json.dumps({"type": "response.completed", "response": response})
                + "\n\n",
            )
        return httpx.Response(200, headers=headers, json=response)

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        **kwargs,
    )
    received = post(client, stream=stream)
    assert len(calls) == 1
    row = next(iter(store.binding.metadata["model_requests"].values()))
    if proof == "zero":
        assert received.status_code == 200 and "qualified-only" in received.text
        assert row["state"] == "completed" and row["gateway_attempts_verified"] is True
        assert ledger.get_model_wallet("71")["balance_units"] == 98
    else:
        assert received.status_code == 502 and "qualified-only" not in received.text
        assert row["state"] == "unknown" and row["gateway_attempts_verified"] is False
        assert row["diagnostic"]["failure_kind"] == "gateway_attempts_unverified"
        assert ledger.get_model_wallet("71")["balance_units"] == 68
        assert post(client).status_code == 409 and len(calls) == 1


@pytest.mark.parametrize("first_identity", [None, "local-agent"])
def test_stream_tool_frames_wait_for_final_model_and_usage_proof(gateway, first_identity):
    client, store, calls, response, app = gateway
    item = {
        "type": "function_call",
        "name": "mcp__xcmax__execute_action",
        "call_id": "must-not-escape",
        "arguments": "{}",
    }
    frames = []
    if first_identity is not None:
        frames.append(
            {
                "type": "response.created",
                "response": {
                    "id": response["id"],
                    "model": first_identity,
                    "status": "in_progress",
                    "output": [],
                },
            }
        )
    frames.extend(
        [
            {"type": "response.output_item.added", "item": item},
            {"type": "response.function_call_arguments.done", "arguments": "must-not-escape"},
            {"type": "response.output_item.done", "item": item},
            {
                "type": "response.completed",
                "response": {**response, "model": "fallback", "output": [item]},
            },
        ]
    )

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="".join("data: " + json.dumps(frame) + "\n\n" for frame in frames),
        )

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        **kwargs,
    )
    received = post(client, stream=True)
    assert received.status_code == 200 and "requires reconciliation" in received.text
    assert "must-not-escape" not in received.text
    assert len(calls) == 1
    row = next(iter(store.binding.metadata["model_requests"].values()))
    assert row["state"] == ("unknown" if first_identity is None else "failed")


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("terminal", ["incomplete", "failed"])
@pytest.mark.parametrize("has_usage", [False, True])
@pytest.mark.parametrize("terminal_has_tool", [False, True])
def test_unsuccessful_terminal_settles_known_usage_and_never_releases_tools(
    gateway, stream, terminal, has_usage, terminal_has_tool
):
    client, store, calls, response, app = gateway
    item = {
        "type": "function_call",
        "name": "mcp__xcmax__execute_action",
        "call_id": "failed-turn-proposal",
        "arguments": "{}",
    }
    known_usage = dict(response["usage"])
    response.update(status=terminal, output=[item] if terminal_has_tool else [])
    if terminal == "incomplete":
        response["incomplete_details"] = {"reason": "max_output_tokens"}
    else:
        response["error"] = {"code": "server_error", "message": "model generation failed"}
    if not has_usage:
        response.pop("usage")

    def handler(request):
        calls.append(request)
        if not stream:
            return httpx.Response(200, json=response)
        frames = [
            {
                "type": "response.created",
                "response": {
                    "id": response["id"],
                    "model": response["model"],
                    "status": "in_progress",
                    "output": [],
                },
            }
        ]
        if response["status"] != "completed":
            frames.extend(
                [
                    {"type": "response.output_item.added", "item": item},
                    {"type": "response.function_call_arguments.done", "arguments": "{}"},
                    {"type": "response.output_item.done", "item": item},
                ]
            )
        frames.append({"type": f"response.{response['status']}", "response": response})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="".join("data: " + json.dumps(frame) + "\n\n" for frame in frames),
        )

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), **kwargs
    )
    received = post(client, stream=stream)
    assert received.status_code == (200 if stream or has_usage and not terminal_has_tool else 502)
    assert "failed-turn-proposal" not in received.text
    assert len(calls) == 1
    row = next(iter(store.binding.metadata["model_requests"].values()))
    if not has_usage:
        assert row["state"] == "unknown"
        assert store.binding.metadata["model_reconciliation_required"] is True
        assert ledger.get_model_wallet("71")["balance_units"] == 68
        assert post(client, stream=stream).status_code == 409 and len(calls) == 1
        return

    assert row["state"] == "failed" and row["usage"]["total_tokens"] == 2000
    assert not store.binding.metadata.get("model_reconciliation_required")
    assert ledger.get_model_wallet("71")["balance_units"] == 98
    assert store.run.metadata["reserved_cost_units"] == 0
    assert len(store.run.llm_calls) == 1 and store.run.llm_calls[0].status == "failed"
    if not terminal_has_tool:
        if stream:
            frames = [json.loads(line[6:]) for line in received.text.splitlines() if line]
            assert frames[-1]["type"] == f"response.{terminal}"
            assert frames[-1]["response"] == response
        else:
            assert received.json() == response

    # A known failed attempt can be followed by a newly admitted request; no
    # uncertain completion is silently retried or converted into a free call.
    response.update(status="completed", output=[], usage=known_usage)
    response.pop("incomplete_details", None)
    response.pop("error", None)
    assert post(client, stream=stream).status_code == 200 and len(calls) == 2
    assert [call.status for call in store.run.llm_calls] == ["failed", "completed"]
    assert ledger.get_model_wallet("71")["balance_units"] == 96


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
    ("bad_event", "phase"),
    [
        ([], "event_shape"),
        ({"type": "response.output_item.added", "item": []}, "delta_item"),
        ({"type": "response.completed", "response": {"output": {}}}, "terminal_output"),
        ({"type": "response.completed", "response": {"usage": None}}, "settlement"),
    ],
)
def test_stream_failure_after_first_frame_records_internal_boundary(gateway, bad_event, phase):
    client, store, calls, model_response, app = gateway
    created = {"type": "response.created", "response": {**model_response, "status": "in_progress"}}
    if isinstance(bad_event, dict) and "response" in bad_event:
        bad_event = {**bad_event, "response": {**model_response, **bad_event["response"]}}

    def broken_stream(request):
        calls.append(request)
        content = "".join(f"data: {json.dumps(event)}\n\n" for event in (created, bad_event))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=content)

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(broken_stream), **kwargs
    )
    received = post(client, stream=True)
    assert received.status_code == 200
    assert '"type": "response.created"' in received.text
    assert '"type": "response.completed"' not in received.text
    assert "Model stream requires reconciliation" in received.text
    assert phase not in received.text
    row = next(iter(store.binding.metadata["model_requests"].values()))
    assert row["state"] == "unknown"
    assert row["diagnostic"]["output_started"] is True
    assert row["diagnostic"]["stream_phase"] == phase
    assert row["diagnostic"]["stream_frame"] == 2
    assert not store.run.llm_calls
    assert post(client, stream=True).status_code == 409
    assert len(calls) == 1


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
