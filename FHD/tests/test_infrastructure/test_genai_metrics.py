"""统一指标出口：计数、直方图、停用开关与合并动作埋点。"""

from __future__ import annotations

from app.infrastructure.memory.consolidation import consolidate
from app.infrastructure.observability import metrics


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

    metrics.observe_plan_generation(outcome="success", duration_ms=100)
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


def test_consolidation_emits_action_metrics(monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_METRICS", raising=False)

    class Store:
        def __init__(self) -> None:
            self.items: list[dict] = []

        def search_facts(self, user_id, fact, limit=5):
            return [
                item
                for item in self.items
                if item["metadata"]["fact_key"] == fact["key"]
                and not item["metadata"]["superseded_by"]
            ]

        def add_fact(self, user_id, fact, *, supersedes=""):
            self.items.append(
                {
                    "chunk_id": f"m{len(self.items) + 1}",
                    "content": fact["text"],
                    "metadata": {
                        "fact_key": fact["key"],
                        "fact_value": fact["value"],
                        "superseded_by": "",
                        "valid_to": "",
                    },
                }
            )
            return f"m{len(self.items)}"

        def supersede_fact(self, user_id, memory_id, *, content, new_id, today):
            return True

    store = Store()
    fact = {"key": "finance.budget", "value": "80万元", "text": "预算：80万元"}
    before = metrics.snapshot()

    consolidate(store, user_id="u", facts=[fact])
    consolidate(store, user_id="u", facts=[fact])

    after = metrics.snapshot()
    assert _delta(before, after, "xcagi_memory_consolidation_total{action=ADD}") == 1
    assert _delta(before, after, "xcagi_memory_consolidation_total{action=NOOP}") == 1


def test_render_is_prometheus_text(monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_METRICS", raising=False)
    metrics.observe_chat_ttft(120)
    body = metrics.render().decode("utf-8")
    assert "xcagi_chat_ttft_ms" in body
    assert "# TYPE" in body
