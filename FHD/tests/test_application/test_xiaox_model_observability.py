"""The real Responses route must preserve durable trace identity and model semantics."""

import json
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anyio
import httpx
import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.infrastructure.llm import genai_telemetry, trace_store
from app.infrastructure.observability import metrics
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_xiaox_binding import make_binding
from tests.test_application.test_xiaox_model_gateway import gateway as gateway
from tests.test_application.test_xiaox_model_gateway import post


@pytest.fixture
def observed(gateway, tmp_path, monkeypatch):
    _, binding, _, _, _ = gateway
    binding.run.metadata.update(trace_id="1" * 32, span_id="2" * 16, trace_flags="01")
    store = trace_store.TraceStore(base_dir=tmp_path / "traces")
    store.start()
    exporter = InMemorySpanExporter()
    store._otlp_processor = SimpleSpanProcessor(exporter)
    monkeypatch.setattr(trace_store, "get_trace_store", lambda: store)
    monkeypatch.setenv("XCAGI_GENAI_TRACE_ENABLED", "1")
    monkeypatch.setenv("XCAGI_GENAI_TRACE_SAMPLE_RATE", "1")
    try:
        yield store, exporter
    finally:
        store.stop()


@pytest.mark.parametrize("stream", [False, True])
def test_responses_emit_sdk_span_on_original_task_and_persist_final_observation(
    gateway, observed, stream
):
    client, binding, calls, _, _ = gateway
    store, exporter = observed
    before = metrics.snapshot()
    assert post(client, stream=stream).status_code == 200
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.context.trace_id == int("1" * 32, 16)
    assert span.parent.span_id == int("2" * 16, 16)
    assert calls[0].headers["traceparent"] == f"00-{'1' * 32}-{span.context.span_id:016x}-01"
    row = next(iter(binding.binding.metadata["model_requests"].values()))
    observation = row["observation"]
    assert row["state"] == "completed"
    assert observation["span_id"] == f"{span.context.span_id:016x}"
    assert observation["final"] is True and observation["group_outcome"] == "success"
    assert observation["duration_ms"] >= observation["phases_ms"]["admission"] >= 0
    assert observation["remote_queue_ms"] is observation["inference_ms"] is None
    assert span.attributes["xcagi.remote_queue_timing"] == "unavailable"
    store.flush()
    assert "model-secret" not in json.dumps(store.query())
    after = metrics.snapshot()
    key = "xcagi_model_call_total{source=xiaox,status=success}"
    assert after[key] - before.get(key, 0) == 1


def test_real_loopback_http_transport_records_measured_phases(gateway, observed):
    client, binding, _, response, app = gateway

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Upstream) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            route = replace(
                app.state.xiaox_model_route, base_url=f"http://127.0.0.1:{server.server_port}/v1"
            )
            app.state.xiaox_model_route = route
            binding.binding.metadata["runtime_config"] = route.runtime_identity()
            app.state.xiaox_http_client_factory = None
            assert post(client).status_code == 200
        finally:
            server.shutdown()
            worker.join(timeout=5)
    row = next(iter(binding.binding.metadata["model_requests"].values()))
    phases = row["observation"]["phases_ms"]
    assert all(
        phases[phase] > 0 for phase in ("connect", "request_send", "response_wait", "response_read")
    )
    assert "inference" not in phases and "queue" not in phases


def test_read_timeout_is_error_trace_but_keeps_unknown_usage(gateway, observed):
    client, binding, calls, _, app = gateway

    def fail(request):
        calls.append(request)
        raise httpx.ReadTimeout("password=must-not-be-exported", request=request)

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(fail), **kwargs
    )
    assert post(client).status_code == 502
    assert len(calls) == 1
    row = next(iter(binding.binding.metadata["model_requests"].values()))
    assert row["state"] == "unknown" and row["observation"]["final"] is True
    spans = observed[1].get_finished_spans()
    assert len(spans) == 1 and spans[0].status.status_code is StatusCode.ERROR
    assert "must-not-be-exported" not in str(spans[0].attributes)


def test_expired_task_finishes_error_trace_before_any_model_effect(gateway, observed):
    client, binding, calls, _, _ = gateway
    binding.binding.metadata["deadline_at"] = 1
    assert post(client).status_code == 408
    assert calls == [] and not binding.binding.metadata.get("model_requests")
    span = observed[1].get_finished_spans()[0]
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes["xcagi.outcome"] == "error"


def test_sql_binding_reopen_keeps_observation_on_original_task(gateway, observed, trusted_actor):
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.infrastructure.xiaox.binding import XiaoxBindingStore
    from app.infrastructure.xiaox.model_gateway import MODEL_PATH

    client, _, calls, _, app = gateway
    actor = trusted_actor(user_id=71)
    original, run, grant = make_binding(
        actor, runtime_config=app.state.xiaox_model_route.runtime_identity()
    )
    original.update(
        run.run_id,
        lambda current, _metadata: current.metadata.update(
            trace_id="3" * 32, span_id="4" * 16, trace_flags="01"
        ),
    )
    app.state.xiaox_binding_store = XiaoxBindingStore(
        SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    )
    app.state.xiaox_run_id = run.run_id
    result = client.post(
        MODEL_PATH,
        headers={"authorization": f"Bearer {grant.model_token}"},
        json={"model": "local-agent", "input": "test"},
    )
    assert result.status_code == 200 and len(calls) == 1
    reopened = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=actor.factory))
    persisted = reopened.get(run.run_id)
    observation = next(iter(persisted.metadata["model_requests"].values()))["observation"]
    assert observation["trace_id"] == "3" * 32 and observation["parent_span_id"] == "4" * 16
    assert observation["final"] is True and persisted.run.status == run.status
    assert observed[1].get_finished_spans()[0].context.trace_id == int("3" * 32, 16)


@pytest.mark.asyncio
async def test_cancelled_request_finishes_trace_without_replaying_unknown_usage(gateway, observed):
    _, binding, calls, _, app = gateway
    started = anyio.Event()
    cancellation = anyio.CancelScope()

    async def provider(request):
        calls.append(request)
        started.set()
        await anyio.sleep_forever()

    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(provider), **kwargs
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://runtime.test"
    ) as client:

        async def invoke():
            with cancellation:
                await client.post(
                    "/api/agent-runtime/xiaox/responses",
                    headers={"authorization": "Bearer model-secret"},
                    json={"model": "local-agent", "input": "test"},
                )

        async with anyio.create_task_group() as requests:
            requests.start_soon(invoke)
            with anyio.fail_after(5):
                await started.wait()
            cancellation.cancel()
    assert cancellation.cancelled_caught and len(calls) == 1
    row = next(iter(binding.binding.metadata["model_requests"].values()))
    assert row["state"] == "unknown" and row["observation"]["group_outcome"] == "cancelled"
    span = observed[1].get_finished_spans()[0]
    assert (
        span.status.status_code is StatusCode.ERROR
        and span.attributes["xcagi.outcome"] == "cancelled"
    )


@pytest.mark.parametrize("method", ["snapshot", "headers", "finish", "attempt"])
def test_optional_observation_outage_never_replays_or_fails_business(gateway, monkeypatch, method):
    def broken(*_args, **_kwargs):
        raise OSError("telemetry unavailable")

    monkeypatch.setattr(genai_telemetry.ModelRequestObservation, method, broken)
    client, binding, calls, _, _ = gateway
    assert post(client).status_code == 200
    assert len(calls) == len(binding.run.llm_calls) == 1
    assert next(iter(binding.binding.metadata["model_requests"].values()))["state"] == "completed"
