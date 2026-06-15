"""neuro_bus event_publisher_mixin 单测。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.neuro_bus.event_publisher_mixin import NeuroEventPublisherMixin
from app.neuro_bus.events.base import EventPriority


class _DemoService(NeuroEventPublisherMixin):
    pass


def test_publish_event_returns_event_id():
    bus = MagicMock()
    with patch("app.neuro_bus.event_publisher_mixin.get_neuro_bus", return_value=bus):
        svc = _DemoService()
        event_id = svc._publish_event("demo.created", {"id": 1})
        assert event_id
        bus.publish.assert_called_once()
        event = bus.publish.call_args[0][0]
        assert event.event_type == "demo.created"
        assert event.payload.get("source") == "_DemoService"
        assert event.priority == EventPriority.NORMAL


def test_publish_event_custom_priority():
    bus = MagicMock()
    with patch("app.neuro_bus.event_publisher_mixin.get_neuro_bus", return_value=bus):
        svc = _DemoService()
        svc._publish_event("demo.urgent", {}, priority=EventPriority.CRITICAL)
        event = bus.publish.call_args[0][0]
        assert event.priority == EventPriority.CRITICAL


def test_publish_event_failure_returns_empty():
    with patch(
        "app.neuro_bus.event_publisher_mixin.get_neuro_bus",
        side_effect=RuntimeError("bus down"),
    ):
        svc = _DemoService()
        assert svc._publish_event("demo.fail", {}) == ""
