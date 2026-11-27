"""Real model-HTTP faults retain SQL progress and cannot authorize blind replay.

The loopback provider is synthetic, not a live model. HTTPX, run/billing storage,
LangGraph checkpoints and the Xiaox admission boundary are production code.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.infrastructure.billing import model_usage as ledger
from app.infrastructure.workflow.checkpoint_bridge import (
    LanggraphCheckpointBridge,
    open_run_checkpointer,
)
from app.infrastructure.xiaox import model_gateway
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from app.infrastructure.xiaox.policy import ModelRoute
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_xiaox_binding import make_binding


@pytest.fixture
def provider():
    state = SimpleNamespace(fault="", requests=[], release=threading.Event())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            state.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            if state.fault == "headers_timeout":
                state.release.wait(5)
                return
            self.send_response(200)
            self.send_header("Content-Length", "10000")
            self.send_header(
                "Content-Type",
                "text/event-stream" if state.fault == "stream_disconnect" else "application/json",
            )
            self.end_headers()
            if state.fault == "body_timeout":
                self.wfile.write(b'{"id":"accepted-but-incomplete"')
                self.wfile.flush()
                state.release.wait(5)
                return
            event = {"type": "response.created", "response": {"model": "fault-model"}}
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
            self.wfile.flush()
            # A genuine incomplete TCP body, not a raised MockTransport exception.
            self.connection.shutdown(socket.SHUT_RDWR)
            self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state.url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()


@pytest.mark.parametrize("fault", ["headers_timeout", "body_timeout", "stream_disconnect"])
def test_transport_fault_preserves_checkpoint_and_blocks_unsettled_replay(
    provider, trusted_actor, tmp_path, monkeypatch, fault
):
    provider.fault = fault
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "local")
    monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "1")
    # Shorten only this test's real wait; the host deadline/retry code is unchanged.
    monkeypatch.setattr(model_gateway, "model_request_timeout_seconds", lambda: 0.75)
    actor = trusted_actor(user_id=71)
    ledger.set_model_wallet_balance("71", 100)
    route = ModelRoute(
        base_url=provider.url + "/v1",
        model="fault-model",
        provider_id="local-fault-fixture",
        upstream_vendor="fixture",
        context_window=32000,
        max_output_tokens=4000,
    )
    store, run, grant = make_binding(actor, runtime_config=route.runtime_identity())
    # Pre-existing progress is committed through the real run and checkpoint stores.
    step = AgentStep(
        node_id="prepared",
        tool_id="customers",
        action="list",
        status="completed",
        output={"success": True, "data": [{"id": "fixture-row"}]},
        attempt_count=1,
    )
    store.update(run.run_id, lambda parent, _metadata: parent.steps.append(step))
    with open_run_checkpointer(store.repository) as saver:
        checkpoints = LanggraphCheckpointBridge(saver, run_namespace=run.run_id)
        checkpoint_id = checkpoints.save(
            "fault-plan", 1, {"node_outputs": {"prepared": step.output}}, ["prepared"]
        )
        before = checkpoints.get("fault-plan", checkpoint_id)
    deadline = store.get(run.run_id).metadata["deadline_at"]

    app = FastAPI()
    app.state.xiaox_binding_store = store
    app.state.xiaox_model_route = route
    app.state.xiaox_run_id = run.run_id
    # No client factory override: the production IndependentModelTransport opens TCP.
    app.include_router(model_gateway.router)
    request = {
        "headers": {"authorization": f"Bearer {grant.model_token}"},
        "json": {"model": route.model, "input": "continue", "stream": fault == "stream_disconnect"},
    }
    with TestClient(app) as client:
        started = time.monotonic()
        response = client.post(model_gateway.MODEL_PATH, **request)
        assert time.monotonic() - started < 5
        assert len(provider.requests) == 1
        if fault == "stream_disconnect":
            frames = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            assert response.status_code == 200 and frames[-1]["type"] == "error"
            assert not any(frame["type"] == "response.completed" for frame in frames)
        else:
            assert response.status_code in {502, 504}

        # Restored network health never turns unknown usage into permission to replay.
        provider.release.set()
        with httpx.Client(trust_env=False, timeout=2) as probe:
            assert probe.get(provider.url).status_code == 200
        reopened = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=actor.factory))
        app.state.xiaox_binding_store = reopened
        saved = reopened.get(run.run_id)
        assert saved.run.status != "completed" and not saved.run.final_output.get("success")
        assert [item.to_dict() for item in saved.run.steps] == [step.to_dict()]
        assert saved.metadata["deadline_at"] == deadline
        assert saved.metadata["model_reconciliation_required"] is True
        attempts = list(saved.metadata["model_requests"].values())
        assert len(attempts) == 1 and attempts[0]["state"] == "unknown"
        assert attempts[0]["diagnostic"]["outcome"] == "unknown"
        assert attempts[0]["diagnostic"]["retryable"] is False
        assert saved.run.metadata["runtime_failure_stage"] == "model"
        assert ledger.get_model_wallet("71")["balance_units"] == 68
        with open_run_checkpointer(reopened.repository) as saver:
            checkpoint = LanggraphCheckpointBridge(saver, run_namespace=run.run_id)
            assert checkpoint.get("fault-plan", checkpoint_id) == before
            assert checkpoint.latest("fault-plan") == before
        assert client.post(model_gateway.MODEL_PATH, **request).status_code == 409
        reopened.close(
            run.run_id, "waiting_reconciliation", generation=grant.binding.metadata["generation"]
        )
        with pytest.raises(XiaoxBindingError) as error:
            reopened.create(run.run_id, runtime_config=route.runtime_identity())
        assert error.value.code == "reconciliation_required"
        assert len(provider.requests) == 1
        assert ledger.get_model_wallet("71")["balance_units"] == 68
