"""trace_store 单元测试：落盘 / 日轮转 / 保留期 / 查询 / fail-open。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.infrastructure.llm.trace_store import TraceStore


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
    assert store.query()[0]["trace_id"] == item["trace_id"]


def test_otlp_bad_legacy_ids_remain_queryable_without_fabricated_trace(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setenv("XCAGI_OTLP_ENDPOINT", "http://collector.invalid")
    store = TraceStore(base_dir=tmp_path)
    exporter = MagicMock()
    monkeypatch.setattr(store, "_get_otlp_exporter", exporter)
    store.record(_span("legacy-span", trace_id="legacy-trace"))
    store.flush()
    exporter.assert_not_called()
    assert store.query(trace_id="legacy-trace")[0]["span_id"] == "legacy-span"
    assert not store._otlp_failed


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
    assert store._otlp_failed


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
    exported = exporter.export.call_args.args[0][0]
    assert exported.context.trace_flags == 0
    assert exported.context.trace_state.to_header() == "vendor=opaque"
    assert exported.parent.trace_flags == 0
    assert exported.parent.trace_state.to_header() == "vendor=opaque"


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
    assert not store._otlp_failed
    assert len(store.query()) == 2
