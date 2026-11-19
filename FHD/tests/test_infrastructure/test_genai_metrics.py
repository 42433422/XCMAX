"""统一指标出口：计数、直方图、停用开关与受治理记忆召回。"""

from __future__ import annotations

from app.infrastructure.observability import metrics
from tests.fixtures.governed_memory_runtime import governed_memory as governed_memory
from tests.fixtures.governed_memory_runtime import owner_id


def _delta(before: dict[str, float], after: dict[str, float], key: str) -> float:
    return after.get(key, 0.0) - before.get(key, 0.0)


def test_memory_recall_counter_and_histogram(monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_METRICS", raising=False)
    before = metrics.snapshot()

    metrics.observe_memory_recall(outcome="hit", duration_ms=12.5)
    metrics.observe_memory_recall(outcome="empty", duration_ms=3.0)

    after = metrics.snapshot()
    assert _delta(before, after, "xcagi_memory_recall_total{outcome=hit}") == 1
    assert _delta(before, after, "xcagi_memory_recall_total{outcome=empty}") == 1
    assert _delta(before, after, "xcagi_memory_recall_duration_ms_count") == 2


def test_metrics_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_METRICS", "0")
    before = metrics.snapshot()

    metrics.observe_plan_stage(stage="model_returned", outcome="returned", duration_ms=100)
    metrics.observe_run_terminal(status="completed")
    metrics.observe_chat_ttft(50)
    metrics.observe_tool_call(tool="products", status="success", duration_ms=8)

    assert metrics.snapshot() == before


def test_labels_are_bounded(monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_METRICS", raising=False)
    before = metrics.snapshot()

    metrics.observe_memory_consolidation("weird-action")
    metrics.observe_tool_call(tool="x" * 200, status="timeout", duration_ms=1)

    after = metrics.snapshot()
    assert _delta(before, after, "xcagi_memory_consolidation_total{action=SKIPPED}") == 1
    assert any(
        key.startswith("xcagi_tool_call_total{") and "status=failure" in key for key in after
    )


def test_governed_native_recall_emits_hit_and_empty_metrics(governed_memory, monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_METRICS", raising=False)
    runtime = governed_memory
    runtime.confirm(runtime.propose("采购预算：80万元"))
    before = metrics.snapshot()

    assert runtime.backend.recall(user_id=owner_id(), query="采购预算")
    assert runtime.backend.recall(user_id=owner_id(8), query="采购预算") == []

    after = metrics.snapshot()
    assert _delta(before, after, "xcagi_memory_recall_total{outcome=hit}") == 1
    assert _delta(before, after, "xcagi_memory_recall_total{outcome=empty}") == 1
    assert _delta(before, after, "xcagi_memory_recall_duration_ms_count") == 2


def test_render_is_prometheus_text(monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_METRICS", raising=False)
    metrics.observe_chat_ttft(120)
    body = metrics.render().decode("utf-8")
    assert "xcagi_chat_ttft_ms" in body
    assert "# TYPE" in body
