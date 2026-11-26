"""trace_store 单元测试：落盘 / 日轮转 / 保留期 / 查询 / fail-open。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.infrastructure.llm.trace_store import TraceStore


@pytest.fixture(autouse=True)
def close_processors(monkeypatch):
    created = []
    initialize = TraceStore.__init__

    def track(store, *args, **kwargs):
        initialize(store, *args, **kwargs)
        created.append(store)

    monkeypatch.setattr(TraceStore, "__init__", track)
    yield
    for store in created:
        store.stop()


def _span(span_id: str, **attrs) -> dict:
    return {
        "span_id": span_id,
        "trace_id": attrs.pop("trace_id", "t-1"),
        "parent_span_id": None,
        "name": "chat",
        "start_time": attrs.pop("start_time", time.time()),
        "end_time": time.time(),
        "duration_ms": 1.0,
        "status": attrs.pop("status", "ok"),
        "attributes": attrs,
        "events": [],
    }


class TestRecord:
    def test_record_flush_writes_jsonl(self, tmp_path: Path):
        store = TraceStore(base_dir=tmp_path)
        store.record(_span("s1", **{"gen_ai.request.model": "m1"}))
        store.flush()
        files = list(tmp_path.glob("trace-*.jsonl"))
        assert len(files) == 1
        rows = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
        assert rows[0]["span_id"] == "s1"
        assert rows[0]["attributes"]["gen_ai.request.model"] == "m1"

    def test_record_fail_open_on_bad_dir(self, tmp_path: Path):
        bad = tmp_path / "not-a-dir"
        bad.write_text("occupied", encoding="utf-8")  # 同名文件使 mkdir 失败
        store = TraceStore(base_dir=bad / "sub")
        store.record(_span("s2"))  # 不抛异常
        store.flush()


class TestQuery:
    def test_query_filters(self, tmp_path: Path):
        store = TraceStore(base_dir=tmp_path)
        store.record(_span("a", **{"gen_ai.request.model": "m1"}))
        store.record(_span("b", status="error", **{"gen_ai.request.model": "m2"}))
        store.record(_span("c", **{"guardrail.blocked": True}))
        store.flush()

        assert {s["span_id"] for s in store.query(model="m1")} == {"a"}
        assert {s["span_id"] for s in store.query(status="error")} == {"b"}
        assert {s["span_id"] for s in store.query(has_guardrail_block=True)} == {"c"}
        assert len(store.query(limit=500)) == 3
        assert {s["span_id"] for s in store.query(trace_id="t-1")} == {"a", "b", "c"}

    def test_query_sorted_desc_by_start_time(self, tmp_path: Path):
        store = TraceStore(base_dir=tmp_path)
        store.record(_span("old", start_time=time.time() - 100))
        store.record(_span("new", start_time=time.time()))
        store.flush()
        items = store.query()
        assert [s["span_id"] for s in items] == ["new", "old"]


class TestRetention:
    def test_cleanup_expired_removes_old_files(self, tmp_path: Path):
        old = tmp_path / "trace-2020-01-01.jsonl"
        old.write_text("{}\n", encoding="utf-8")
        keep = tmp_path / f"trace-{time.strftime('%Y-%m-%d')}.jsonl"
        keep.write_text("{}\n", encoding="utf-8")
        store = TraceStore(base_dir=tmp_path, retention_days=14)
        store.cleanup_expired()
        assert not old.exists()
        assert keep.exists()


def test_otlp_export_preserves_stored_ids_parent_error_and_elapsed(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from opentelemetry.sdk.trace.export import SpanExportResult
    from opentelemetry.trace import StatusCode

    monkeypatch.setenv("XCAGI_OTLP_ENDPOINT", "http://collector.invalid")
    store = TraceStore(base_dir=tmp_path)
    exporter = MagicMock()
    exporter.export.return_value = SpanExportResult.SUCCESS
    monkeypatch.setattr(store, "_get_otlp_exporter", lambda endpoint: exporter)
    item = _span("b" * 16, trace_id="a" * 32, start_time=1000.0, status="error")
    item.update(
        parent_span_id="c" * 16,
        end_time=900.0,
        duration_ms=25.5,
        events=[{"name": "response", "timestamp": 1000.02, "attributes": {"count": 1}}],
    )
    store.record(item)
    store.flush()
    exported = exporter.export.call_args.args[0][0]
    assert exported.context.trace_id == int(item["trace_id"], 16)
    assert exported.context.span_id == int(item["span_id"], 16)
    assert exported.parent.span_id == int(item["parent_span_id"], 16)
    assert exported.start_time == 1_000_000_000_000
    assert exported.end_time - exported.start_time == 25_500_000
    assert exported.status.status_code == StatusCode.ERROR
    assert exported.events[0].name == "response"
    assert exported.resource is store.tracer_provider.resource
    assert store.query()[0]["trace_id"] == item["trace_id"]


def test_otlp_bad_legacy_ids_remain_queryable_without_fabricated_trace(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setenv("XCAGI_OTLP_ENDPOINT", "http://collector.invalid")
    store = TraceStore(base_dir=tmp_path)
    exporter = MagicMock()
    monkeypatch.setattr(store, "_get_otlp_exporter", lambda endpoint: exporter)
    store.record(_span("legacy-span", trace_id="legacy-trace"))
    store.flush()
    exporter.export.assert_not_called()
    assert store.query(trace_id="legacy-trace")[0]["span_id"] == "legacy-span"


def test_otlp_export_failure_does_not_break_jsonl_flush(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setenv("XCAGI_OTLP_ENDPOINT", "http://collector.invalid")
    store = TraceStore(base_dir=tmp_path)
    exporter = MagicMock()
    exporter.export.side_effect = TypeError("broken exporter")
    monkeypatch.setattr(store, "_get_otlp_exporter", lambda endpoint: exporter)
    store.record(_span("b" * 16, trace_id="a" * 32))
    store.flush()
    assert store.query(trace_id="a" * 32)
    exporter.export.side_effect = None
    store.record(_span("c" * 16, trace_id="a" * 32))
    store.flush()
    assert exporter.export.call_count == 2
    assert len(store.query()) == 2


def test_genai_propagation_survives_background_flush(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import MagicMock

    from opentelemetry.sdk.trace.export import SpanExportResult

    from app.infrastructure.llm.genai_telemetry import start_genai_span
    from app.neuro_bus.tracer import TraceContext

    monkeypatch.setenv("XCAGI_OTLP_ENDPOINT", "http://collector.invalid")
    store = TraceStore(base_dir=tmp_path)
    exporter = MagicMock()
    exporter.export.return_value = SpanExportResult.SUCCESS
    monkeypatch.setattr(store, "_get_otlp_exporter", lambda endpoint: exporter)
    with TraceContext("a" * 32, "b" * 16, trace_flags="00", trace_state="vendor=opaque"):
        span = start_genai_span(
            provider_id="test",
            model="test",
            temperature=0,
            max_tokens=1,
            profile="test",
            caller=None,
            tenant_id=None,
            messages=[],
        )
        span.finish()
        assert span.to_dict()["trace_flags"] == "00"
        assert span.to_dict()["trace_state"] == "vendor=opaque"
        store.record(span.to_dict())
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(store.flush).result()
    # SDK sampling must not turn a parent's explicit unsampled decision into export.
    exporter.export.assert_not_called()
    stored = store.query()[0]
    assert stored["trace_flags"] == "00"
    assert stored["trace_state"] == "vendor=opaque"
    assert stored["parent_span_id"] == "b" * 16


def test_transient_otlp_failure_does_not_disable_later_exports(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from opentelemetry.sdk.trace.export import SpanExportResult

    monkeypatch.setenv("XCAGI_OTLP_ENDPOINT", "http://collector.invalid")
    store = TraceStore(base_dir=tmp_path)
    exporter = MagicMock()
    exporter.export.side_effect = [SpanExportResult.FAILURE, SpanExportResult.SUCCESS]
    monkeypatch.setattr(store, "_get_otlp_exporter", lambda endpoint: exporter)
    for span_id in ("b" * 16, "c" * 16):
        store.record(_span(span_id, trace_id="a" * 32))
        store.flush()
    assert exporter.export.call_count == 2
    assert len(store.query()) == 2


def test_shutdown_drains_all_batches_and_explicit_restart_works(tmp_path):
    store = TraceStore(base_dir=tmp_path, max_batch=10)
    for i in range(35):
        store.record(_span(str(i)))
    store.stop()
    assert len(store.query()) == 35
    store.stop()
    store.start()
    store.record(_span("after-restart"))
    store.stop()
    assert len(store.query()) == 36


def test_queue_freezes_nested_payload_before_caller_reuses_it(tmp_path):
    store = TraceStore(base_dir=tmp_path)
    item = _span("a", **{"gen_ai.request.model": "original"})
    store.record(item)
    item["attributes"]["gen_ai.request.model"] = "changed"
    store.flush()
    assert store.query()[0]["attributes"]["gen_ai.request.model"] == "original"


@pytest.mark.parametrize("shape", ["array", "tuple", "nested_mapping"])
def test_otlp_queue_freezes_span_and_event_arrays(tmp_path, monkeypatch, shape):
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
    from opentelemetry.sdk.trace import Event, ReadableSpan
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    monkeypatch.setenv("XCAGI_OTLP_ENDPOINT", "http://collector.invalid")
    store = TraceStore(base_dir=tmp_path)
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(store, "_get_otlp_exporter", lambda endpoint: exporter)
    original = ["original"]
    value = {"array": original, "tuple": (original,), "nested_mapping": [{"inner": original}]}[
        shape
    ]
    expected = json.loads(json.dumps(value))
    item = _span("b" * 16, trace_id="a" * 32, values=value)
    item["events"] = [
        {"name": "response", "timestamp": time.time(), "attributes": {"values": value}}
    ]

    # Exercise the real batch processor before reusing the caller's nested input.
    store.record(item)
    original[0] = "changed"
    store.stop()

    (exported,) = exporter.get_finished_spans()
    assert isinstance(exported, ReadableSpan) and isinstance(exported.events[0], Event)
    assert json.loads(json.dumps(exported.attributes["values"])) == expected
    assert json.loads(json.dumps(exported.events[0].attributes["values"])) == expected
    (local,) = store.query()
    assert local["attributes"]["values"] == local["events"][0]["attributes"]["values"] == expected
    # The locked OTLP encoder supports sequences and nested mappings, too.
    encoded = encode_spans((exported,)).SerializeToString()
    assert encoded.count(b"original") == 2 and b"changed" not in encoded


def test_long_running_queries_bound_memory_and_skip_corrupt_records(tmp_path):
    import tracemalloc

    path = tmp_path / f"trace-{time.strftime('%Y-%m-%d')}.jsonl"
    with path.open("w", encoding="utf-8") as stream:
        for i in range(4000):
            stream.write(json.dumps(_span(str(i), start_time=i, detail="x" * 1024)) + "\n")
        stream.write('[1, 2]\n{"start_time": "invalid"}\n{"start_time": NaN}\n{partial')
    store = TraceStore(base_dir=tmp_path)
    tracemalloc.start()
    try:
        rows = store.query(limit=3)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert [row["span_id"] for row in rows] == ["3999", "3998", "3997"]
    assert peak < 3_000_000


def test_retention_runs_when_sdk_writes_without_restarting_process(tmp_path):
    expired = tmp_path / "trace-2020-01-01.jsonl"
    expired.write_text("{}\n", encoding="utf-8")
    store = TraceStore(base_dir=tmp_path)
    store.record(_span("today"))
    store.flush()
    assert not expired.exists()


def test_actual_sdk_spans_share_the_existing_trace_view(tmp_path, monkeypatch):
    from app.infrastructure.llm import trace_store
    from app.infrastructure.observability.genai_spans import record_tool_result, tool_call_span
    from app.neuro_bus.tracer import NeuroTracer, SpanStatus, TraceContext

    store = TraceStore(base_dir=tmp_path)
    monkeypatch.setattr(trace_store, "get_trace_store", lambda: store)
    with TraceContext("a" * 32, "b" * 16):
        with tool_call_span(tool_id="customers", action="read", node_id="read-1") as tool:
            child = NeuroTracer().start_span("database-read")
            child.finish()
            cancelled = NeuroTracer().start_span("cancelled-read")
            cancelled.finish(SpanStatus.CANCELLED)
            record_tool_result(tool, {"success": True})
    store.stop()
    rows = {row["name"]: row for row in store.query()}
    parent = rows["execute_tool customers.read"]
    assert parent["trace_id"] == rows["database-read"]["trace_id"] == "a" * 32
    assert parent["parent_span_id"] == "b" * 16
    assert rows["database-read"]["parent_span_id"] == parent["span_id"]
    assert rows["cancelled-read"]["status"] == "cancelled"
    assert parent["attributes"]["gen_ai.tool.call.result"] == "success"


def test_real_otlp_http_preserves_parent_and_encodes_content_descriptor(tmp_path, monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    from app.infrastructure.llm.genai_telemetry import start_genai_span
    from app.neuro_bus.tracer import TraceContext

    requests = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append((self.path, ExportTraceServiceRequest.FromString(body)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("XCAGI_OTLP_ENDPOINT", f"http://127.0.0.1:{server.server_port}/v1/traces")
    monkeypatch.setenv("XCAGI_GENAI_TRACE_CAPTURE_CONTENT", "0")
    store = TraceStore(base_dir=tmp_path)
    try:
        with TraceContext("a" * 32, "b" * 16):
            span = start_genai_span(
                provider_id="test",
                model="test",
                temperature=0,
                max_tokens=1,
                profile="test",
                caller=None,
                tenant_id=None,
                messages=[{"role": "user", "content": "private-business-input"}],
            )
            span.finish()
            store.record(span.to_dict())
        store.stop()
        assert len(requests) == 1
        path, request = requests[0]
        assert path == "/v1/traces"
        exported = request.resource_spans[0].scope_spans[0].spans[0]
        assert exported.trace_id.hex() == "a" * 32
        assert exported.parent_span_id.hex() == "b" * 16
        assert exported.span_id.hex() == span.span_id
        descriptor = json.loads(exported.events[0].attributes[0].value.string_value)
        assert descriptor["len"] == len("private-business-input")
        assert "sha256" in descriptor and "text" not in descriptor
        assert "private-business-input" not in str(request)
        assert len(store.query()) == 1
    finally:
        store.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.asyncio
async def test_lifespan_drains_traces_even_when_application_cleanup_fails(tmp_path, monkeypatch):
    import importlib
    from contextlib import asynccontextmanager

    from app.infrastructure.llm import trace_store

    lifecycle = importlib.import_module("app.fastapi_app.lifespan")
    store = TraceStore(base_dir=tmp_path, max_batch=10)
    monkeypatch.setattr(trace_store, "_store", store)

    @asynccontextmanager
    async def failing_lifecycle(app):
        yield
        raise RuntimeError("application cleanup failed")

    monkeypatch.setattr(lifecycle, "_application_lifespan", failing_lifecycle)
    with pytest.raises(RuntimeError, match="application cleanup failed"):
        async with lifecycle.lifespan(object()):
            for i in range(35):
                store.record(_span(str(i)))
    assert trace_store._store is None
    assert len(store.query()) == 35
