"""neuro_bus events 基类与领域事件注册表（Phase 4 高 ROI mock 单测）。"""

from __future__ import annotations

import json
import time

import pytest

from app.neuro_bus.events.base import (
    DomainEvent,
    EventMetadata,
    EventPriority,
    IntentEvent,
    NeuroEvent,
)
from app.neuro_bus.events.product_events import (
    PRODUCT_EVENT_HANDLERS,
    register_product_handler,
)


def _make_event(**kwargs) -> NeuroEvent:
    return NeuroEvent("test.event", {"k": "v"}, **kwargs)


class TestEventMetadata:
    def test_to_dict_has_required_keys(self) -> None:
        meta = EventMetadata(source="unit", domain="test")
        d = meta.to_dict()
        assert d["source"] == "unit"
        assert d["domain"] == "test"
        assert "event_id" in d
        assert "span_id" in d


class TestNeuroEvent:
    def test_to_dict_and_json_roundtrip(self) -> None:
        e = _make_event(priority=EventPriority.HIGH)
        d = e.to_dict()
        assert d["event_type"] == "test.event"
        assert d["priority"] == EventPriority.HIGH.value
        parsed = json.loads(e.to_json())
        assert parsed["payload"]["k"] == "v"

    def test_from_dict_reassigns_event_id_by_default(self) -> None:
        original = _make_event()
        data = original.to_dict()
        restored = NeuroEvent.from_dict(data)
        assert restored.event_type == "test.event"
        assert restored.metadata.event_id != original.metadata.event_id

    def test_from_dict_preserve_queue_identity(self) -> None:
        original = _make_event()
        data = original.to_dict()
        restored = NeuroEvent.from_dict(data, preserve_queue_identity=True)
        assert restored.metadata.event_id == original.metadata.event_id

    def test_remint_queue_identity(self) -> None:
        e = _make_event()
        old_id = e.metadata.event_id
        e.remint_queue_identity()
        assert e.metadata.event_id != old_id
        assert e.metadata.dedup_key

    def test_with_trace_source_domain_timeout(self) -> None:
        e = _make_event()
        e.with_trace("trace-1", "span-child")
        assert e.metadata.trace_id == "trace-1"
        assert e.metadata.span_id == "span-child"
        e.with_source("pytest").with_domain("inventory")
        assert e.metadata.source == "pytest"
        assert e.metadata.domain == "inventory"
        e.with_timeout(100)
        assert e.metadata.timeout_ms == 100

    def test_is_expired(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now = 1_000_000.0
        monkeypatch.setattr(time, "time", lambda: now)
        e = NeuroEvent("t", {}, metadata=EventMetadata(timeout_ms=1000))
        monkeypatch.setattr(time, "time", lambda: now + 2)
        assert e.is_expired() is True

    def test_priority_comparison(self) -> None:
        high = NeuroEvent("h", {}, priority=EventPriority.HIGH)
        low = NeuroEvent("l", {}, priority=EventPriority.LOW)
        assert high < low

    def test_repr(self) -> None:
        e = NeuroEvent("demo", {}, priority=EventPriority.CRITICAL)
        e.metadata.domain = "demo"
        assert "demo" in repr(e)

    def test_kwargs_merged_into_payload(self) -> None:
        e = NeuroEvent("t", {"a": 1}, extra_field="x")
        assert e.payload["extra_field"] == "x"

    def test_get_dedup_key_stable(self) -> None:
        e = _make_event()
        assert e.get_dedup_key() == e.metadata.dedup_key


class TestDomainEvent:
    def test_aggregate_fields(self) -> None:
        e = DomainEvent("product", "created", "agg-42", {"name": "螺栓"})
        assert e.event_type == "product.created"
        assert e.aggregate_id == "agg-42"
        assert e.version == 1
        assert e.payload["_aggregate_id"] == "agg-42"


class TestIntentEvent:
    def test_reflex_intent_timeout(self) -> None:
        e = IntentEvent("greeting", "u1", 0.99, "你好")
        assert e.metadata.timeout_ms == 1

    def test_subconscious_intent_timeout(self) -> None:
        e = IntentEvent("help", "u1", 0.8, "帮助")
        assert e.metadata.timeout_ms == 10

    def test_default_intent_timeout(self) -> None:
        e = IntentEvent("complex_query", "u1", 0.7, "查库存")
        assert e.metadata.timeout_ms == 200


class TestProductEventHandlers:
    def test_register_product_handler(self) -> None:
        called: list[str] = []

        def handler(_evt):
            called.append("ok")

        register_product_handler("product.created", handler)
        assert handler in PRODUCT_EVENT_HANDLERS["product.created"]

    def test_register_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="未知的产品事件类型"):
            register_product_handler("product.unknown_type", lambda e: None)


def test_domain_event_classes_have_expected_event_types() -> None:
    """各域事件类应是 NeuroEvent 子类，且 event_type 带正确的域前缀。"""
    from app.neuro_bus.events import (
        inventory_events,
        order_events,
        payment_events,
        shipment_events,
    )
    from app.neuro_bus.events.base import NeuroEvent

    # Representative event classes from four domains, with their expected
    # event_type prefix. This verifies the class definitions are real and
    # correctly wired (not merely that the module imported).
    cases = [
        (order_events.OrderSubmittedEvent, "order.", "order.submitted"),
        (payment_events.PaymentCompletedEvent, "payment.", "payment.completed"),
        (inventory_events.InventoryStockInEvent, "inventory.", "inventory.stock_in"),
        (shipment_events.ShipmentCreatedEvent, "shipment.", "shipment.created"),
    ]
    for cls, prefix, exact in cases:
        assert issubclass(cls, NeuroEvent), f"{cls.__name__} 不是 NeuroEvent 子类"
        event_type = getattr(cls, "event_type")
        assert isinstance(event_type, str) and event_type
        assert event_type.startswith(prefix), f"{cls.__name__}.event_type={event_type!r}"
        if exact is not None:
            assert event_type == exact
