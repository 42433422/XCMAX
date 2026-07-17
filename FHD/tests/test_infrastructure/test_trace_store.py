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
