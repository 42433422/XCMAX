"""COVERAGE_RAMP C3.1: NeuroBus 总线 publish / 处理器失败 / DLQ 兜底路径。

覆盖：
- bus 未运行时 publish 拒绝
- _preflight_publish：dedup 命中 / 限流 / lifeline 拒收
- handler 抛错时 record_call / circuit.record_failure / DLQ handle_failure
- DLQ handle_failure 内部抛错被吞（双层兜底）
- get_stats / get_reliability_status 字段
- summarize_subscriptions flat + domain + global_handlers
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.neuro_bus import bus as bus_mod
from app.neuro_bus.events.base import EventPriority, NeuroEvent

# ---------------------------------------------------------------------------
# publish() 拒绝分支
# ---------------------------------------------------------------------------


def test_publish_refused_when_not_running():
    bus = bus_mod.NeuroBus(worker_threads=1)
    ev = NeuroEvent("test.evt", {"k": 1}, priority=EventPriority.NORMAL)
    assert bus.publish(ev) is False


def test_publish_returns_false_when_dedup_rejects(monkeypatch):
    bus = bus_mod.NeuroBus(worker_threads=1)
    bus._running = True

    fake_dedup = MagicMock()
    fake_dedup.mark_processing.return_value = False
    bus._rel_dedup = fake_dedup

    ev = NeuroEvent("test.evt", {"k": 1}, priority=EventPriority.NORMAL)
    assert bus.publish(ev) is False
    fake_dedup.mark_processing.assert_called_once_with(ev)


def test_publish_returns_false_when_rate_limit_rejects(monkeypatch):
    bus = bus_mod.NeuroBus(worker_threads=1)
    bus._running = True

    fake_dedup = MagicMock()
    fake_dedup.mark_processing.return_value = True
    bus._rel_dedup = fake_dedup

    fake_rate = MagicMock()
    fake_rate.check_rate.return_value = False
    bus._rel_rate = fake_rate

    ev = NeuroEvent("test.evt", {"k": 1}, priority=EventPriority.NORMAL)
    assert bus.publish(ev) is False
    # 限流拒绝后回滚 dedup
    fake_dedup.remove.assert_called_once_with(ev)


def test_publish_returns_false_when_lifeline_rejects(monkeypatch):
    bus = bus_mod.NeuroBus(worker_threads=1)
    bus._running = True

    fake_dedup = MagicMock()
    fake_dedup.mark_processing.return_value = True
    bus._rel_dedup = fake_dedup

    fake_lifeline = MagicMock()
    fake_lifeline.should_process.return_value = False
    bus._rel_lifeline = fake_lifeline

    ev = NeuroEvent("test.evt", {"k": 1}, priority=EventPriority.NORMAL)
    assert bus.publish(ev) is False
    fake_dedup.remove.assert_called_once_with(ev)


# ---------------------------------------------------------------------------
# publish() 成功路径：tracer / metric / event_available
# ---------------------------------------------------------------------------


def test_publish_with_tracer_writes_span(monkeypatch):
    bus = bus_mod.NeuroBus(worker_threads=1)
    bus._running = True

    fake_span = MagicMock()
    fake_span.span_id = "span-1"
    fake_tracer = MagicMock()
    fake_tracer.start_span.return_value = fake_span
    bus._rel_tracer = fake_tracer

    # 强制 100% 采样
    monkeypatch.setattr(bus_mod, "_should_trace_event", lambda: True)
    # event_available 不可写
    bus._event_available = None

    ev = NeuroEvent("test.evt", {"k": 1}, priority=EventPriority.NORMAL)
    assert bus.publish(ev) is True
    fake_tracer.start_span.assert_called_once()
    assert bus._trace_by_event_id[ev.metadata.event_id] == "span-1"


def test_publish_with_persistence_appends_buffer(monkeypatch):
    bus = bus_mod.NeuroBus(worker_threads=1)
    bus._running = True
    bus._enable_persistence = True

    ev = NeuroEvent("test.evt", {"k": 1}, priority=EventPriority.NORMAL)
    assert bus.publish(ev) is True
    assert len(bus._event_buffer) == 1


# ---------------------------------------------------------------------------
# 处理器失败：circuit / DLQ 兜底
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_handler_exception_dlq_and_circuit_record():
    bus = bus_mod.NeuroBus(worker_threads=1)
    bus._running = True

    # 注入假电路
    fake_circuit = MagicMock()
    fake_circuit.can_execute.return_value = True
    bus._rel_circuit = fake_circuit

    # 注入假 DLQ
    fake_dlq_int = MagicMock()
    bus._dlq_integration = fake_dlq_int

    async def boom(event):
        raise RuntimeError("handler failed")

    bus.subscribe("test.fail", boom)

    ev = NeuroEvent("test.fail", {"x": 1}, priority=EventPriority.NORMAL)
    ok = await bus._call_handler(
        bus._handlers["test.fail"][0],
        ev,
    )
    assert ok is False
    fake_circuit.record_failure.assert_called_once()
    fake_dlq_int.handle_failure.assert_called_once()
    args = fake_dlq_int.handle_failure.call_args
    assert args[0][0] is ev
    assert isinstance(args[0][1], RuntimeError)


@pytest.mark.asyncio
async def test_dispatch_handler_circuit_open_skips():
    bus = bus_mod.NeuroBus(worker_threads=1)
    bus._running = True

    fake_circuit = MagicMock()
    fake_circuit.can_execute.return_value = False
    bus._rel_circuit = fake_circuit

    called = MagicMock()

    async def handler(event):
        called()

    bus.subscribe("test.x", handler)
    ev = NeuroEvent("test.x", {}, priority=EventPriority.NORMAL)
    ok = await bus._call_handler(bus._handlers["test.x"][0], ev)
    assert ok is False
    called.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_dlq_handle_failure_inner_exception_swallowed():
    bus = bus_mod.NeuroBus(worker_threads=1)
    bus._running = True

    fake_dlq_int = MagicMock()
    fake_dlq_int.handle_failure.side_effect = RuntimeError("dlq broken")
    bus._dlq_integration = fake_dlq_int

    async def boom(event):
        raise RuntimeError("h-fail")

    bus.subscribe("test.fail2", boom)
    ev = NeuroEvent("test.fail2", {}, priority=EventPriority.NORMAL)
    # 不应向外抛
    ok = await bus._call_handler(bus._handlers["test.fail2"][0], ev)
    assert ok is False


# ---------------------------------------------------------------------------
# get_stats / get_reliability_status
# ---------------------------------------------------------------------------


def test_get_stats_reports_counters():
    bus = bus_mod.NeuroBus(worker_threads=1)
    bus._running = True
    stats = bus.get_stats()
    assert "published" in stats
    assert "processed" in stats
    assert "errors" in stats
    assert "dropped" in stats
    assert "queue_size" in stats
    assert stats["running"] is True


def test_get_reliability_status_no_circuit():
    bus = bus_mod.NeuroBus(worker_threads=1)
    out = bus.get_reliability_status()
    assert "fhd_env" in out
    assert "dedup" in out
    assert "circuit_open" not in out  # 无 circuit 时不写


def test_get_reliability_status_with_circuit_open():
    bus = bus_mod.NeuroBus(worker_threads=1)
    fake_circuit = MagicMock()
    fake_circuit.can_execute.return_value = False
    bus._rel_circuit = fake_circuit
    out = bus.get_reliability_status()
    assert out["circuit_open"] is True


def test_get_reliability_status_with_circuit_can_execute_error():
    bus = bus_mod.NeuroBus(worker_threads=1)
    fake_circuit = MagicMock()
    fake_circuit.can_execute.side_effect = RuntimeError("oops")
    bus._rel_circuit = fake_circuit
    out = bus.get_reliability_status()
    assert out["circuit_open"] is None


# ---------------------------------------------------------------------------
# summarize_subscriptions
# ---------------------------------------------------------------------------


def test_summarize_subscriptions_flat_and_domain_and_global():
    bus = bus_mod.NeuroBus(worker_threads=1)

    async def h1(event):
        return None

    async def h2(event):
        return None

    bus.subscribe("alpha", h1)
    bus.subscribe("alpha", h2)
    bus.subscribe_event("beta", h1, domain="sales")
    bus.subscribe_global(h1)

    summary = bus.summarize_subscriptions()
    assert summary["flat_event_handlers"]["alpha"] == 2
    assert summary["domain_handlers"]["sales"]["beta"] == 1
    assert summary["global_handlers"] == 1


# ---------------------------------------------------------------------------
# set_neuro_bus / registered_domains
# ---------------------------------------------------------------------------


def test_set_neuro_bus_replaces_singleton(monkeypatch):
    new_bus = bus_mod.NeuroBus(worker_threads=1)
    bus_mod.set_neuro_bus(new_bus)
    assert bus_mod.get_neuro_bus() is new_bus


def test_registered_domains_returns_empty_when_registry_unavailable(monkeypatch):
    monkeypatch.setattr(
        "app.neuro_bus.domains.base.get_domain_registry",
        MagicMock(side_effect=RuntimeError("no registry")),
    )
    bus = bus_mod.NeuroBus(worker_threads=1)
    assert bus.registered_domains == []


# ---------------------------------------------------------------------------
# HandlerSubscription
# ---------------------------------------------------------------------------


def test_handler_subscription_error_rate_zero_calls():
    from app.neuro_bus.bus import HandlerSubscription

    sub = HandlerSubscription("e", lambda ev: None, is_async=False)
    assert sub.error_rate == 0.0


def test_handler_subscription_filter_fn():
    from app.neuro_bus.bus import HandlerSubscription

    called = []

    async def h(event):
        called.append(event)

    sub = HandlerSubscription("e", h, filter_fn=lambda e: e.event_type == "match")
    ev_match = NeuroEvent("match", {}, priority=EventPriority.NORMAL)
    ev_other = NeuroEvent("other", {}, priority=EventPriority.NORMAL)
    assert sub.should_handle(ev_match) is True
    assert sub.should_handle(ev_other) is False


# ---------------------------------------------------------------------------
# PriorityEventQueue
# ---------------------------------------------------------------------------


def test_priority_queue_replaces_low_priority_when_full():
    from app.neuro_bus.bus import PriorityEventQueue

    pq = PriorityEventQueue(max_size=2)
    ev_high = NeuroEvent("h", {}, priority=EventPriority.HIGH)
    ev_low = NeuroEvent("l", {}, priority=EventPriority.LOW)
    ev_norm = NeuroEvent("n", {}, priority=EventPriority.NORMAL)
    assert pq.put(ev_low) is True
    assert pq.put(ev_norm) is True
    # 再放一个 HIGH，会挤掉最低优先级 (LOW)
    assert pq.put(ev_high) is True
    assert pq.size() == 2
    assert pq.get().event_type == "h"


def test_priority_queue_drops_when_full_and_higher_or_equal_priority():
    from app.neuro_bus.bus import PriorityEventQueue

    pq = PriorityEventQueue(max_size=1)
    ev_low = NeuroEvent("l", {}, priority=EventPriority.LOW)
    ev_high = NeuroEvent("h", {}, priority=EventPriority.HIGH)
    assert pq.put(ev_low) is True
    # 新事件优先级 <= 最低，直接丢弃
    assert pq.put(ev_low) is False
    assert pq._dropped_count == 1


def test_priority_queue_clear_empties():
    from app.neuro_bus.bus import PriorityEventQueue

    pq = PriorityEventQueue()
    ev = NeuroEvent("e", {}, priority=EventPriority.NORMAL)
    pq.put(ev)
    pq.clear()
    assert pq.size() == 0
