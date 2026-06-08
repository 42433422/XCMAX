"""InMemoryNeuroBus：订阅顺序、通配符、幂等去重、单处理器异常不阻断其他处理器。

Enhanced tests aligned with FHD NeuroBus reliability layer:
- Handler priority ordering
- Handler filter support
- Circuit breaker integration
- Deduplication cache
- DLQ callback
- Stats reporting
"""

from __future__ import annotations

from modstore_server.eventing.bus import (
    CircuitBreaker,
    DeduplicationCache,
    HandlerSubscription,
    InMemoryNeuroBus,
)
from modstore_server.eventing.events import new_event


def _evt(name: str, key: str = "k1", payload: dict | None = None):
    return new_event(
        name,
        producer="test",
        subject_id="sub",
        idempotency_key=key,
        payload=payload or {},
    )


def test_publish_invokes_handlers_in_subscribe_order() -> None:
    bus = InMemoryNeuroBus()
    out: list[str] = []
    bus.subscribe("order.paid", lambda _: out.append("first"))
    bus.subscribe("order.paid", lambda _: out.append("second"))
    bus.publish(_evt("order.paid", "id-1"))
    assert out == ["first", "second"]


def test_wildcard_star_subscriber() -> None:
    bus = InMemoryNeuroBus()
    stars: list[str] = []

    def star(_):
        stars.append("*")

    bus.subscribe("*", star)
    bus.publish(_evt("any.event", "id-4"))
    assert stars == ["*"]


def test_duplicate_idempotency_key_skips_handlers_second_time() -> None:
    bus = InMemoryNeuroBus()
    n = {"c": 0}

    def h(_):
        n["c"] += 1

    bus.subscribe("e", h)
    e = _evt("e", "same-key")
    bus.publish(e)
    bus.publish(e)
    assert n["c"] == 1


def test_handler_exception_does_not_stop_other_handlers() -> None:
    bus = InMemoryNeuroBus()
    out: list[str] = []

    def boom(_):
        raise RuntimeError("boom")

    def ok(_):
        out.append("ok")

    bus.subscribe("e2", boom)
    bus.subscribe("e2", ok)
    bus.publish(_evt("e2", "id-5"))
    assert out == ["ok"]


def test_priority_ordering() -> None:
    bus = InMemoryNeuroBus()
    out: list[str] = []
    bus.subscribe("e", lambda _: out.append("low"), priority=10)
    bus.subscribe("e", lambda _: out.append("high"), priority=1)
    bus.subscribe("e", lambda _: out.append("mid"), priority=5)
    bus.publish(_evt("e", "prio-1"))
    assert out == ["high", "mid", "low"]


def test_handler_filter_fn() -> None:
    bus = InMemoryNeuroBus()
    out: list[str] = []

    def only_paid(event):
        return event.payload.get("status") == "paid"

    bus.subscribe("order", lambda _: out.append("filtered"), filter_fn=only_paid)
    bus.publish(_evt("order", "f1", payload={"status": "pending"}))
    assert out == []
    bus.publish(_evt("order", "f2", payload={"status": "paid"}))
    assert out == ["filtered"]


def test_circuit_breaker_blocks_when_open() -> None:
    cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=300.0)
    assert cb.can_execute() is True
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    assert cb.can_execute() is False


def test_circuit_breaker_half_open_recovery() -> None:
    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.0)
    cb.record_failure()
    assert cb.state == "open"
    assert cb.can_execute() is True
    assert cb.state == "half_open"
    cb.record_success()
    assert cb.state == "closed"


def test_circuit_breaker_reset() -> None:
    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=300.0)
    cb.record_failure()
    assert cb.state == "open"
    cb.reset()
    assert cb.state == "closed"
    assert cb.can_execute() is True


def test_deduplication_cache() -> None:
    cache = DeduplicationCache(ttl_seconds=60.0)
    assert cache.mark_processing("key1") is True
    assert cache.mark_processing("key1") is False
    cache.remove("key1")
    assert cache.mark_processing("key1") is True


def test_dlq_callback_on_handler_failure() -> None:
    bus = InMemoryNeuroBus()
    dlq: list[tuple] = []

    def dlq_handler(event, exc, handler_name):
        dlq.append((event.event_name, str(exc), handler_name))

    bus.set_dlq_callback(dlq_handler)

    def boom(_):
        raise RuntimeError("dlq test")

    bus.subscribe("dlq.evt", boom)
    bus.publish(_evt("dlq.evt", "dlq-1"))
    assert len(dlq) == 1
    assert dlq[0][0] == "dlq.evt"
    assert "dlq test" in dlq[0][1]


def test_stats_reporting() -> None:
    bus = InMemoryNeuroBus()
    bus.subscribe("stats.evt", lambda _: None)
    bus.publish(_evt("stats.evt", "s1"))
    bus.publish(_evt("stats.evt", "s2"))
    stats = bus.get_stats()
    assert stats["published"] == 2
    assert stats["processed"] == 2
    assert stats["handlers"] == 1
    assert "dedup_enabled" in stats
    assert "circuit_breaker_state" in stats


def test_handler_subscription_stats() -> None:
    sub = HandlerSubscription("test", lambda _: None)
    sub.record_call(success=True)
    sub.record_call(success=True)
    sub.record_call(success=False)
    assert sub.call_count == 3
    assert sub.error_count == 1
    assert abs(sub.error_rate - 1 / 3) < 0.01
