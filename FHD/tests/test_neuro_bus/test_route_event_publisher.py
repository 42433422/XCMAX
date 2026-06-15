"""neuro_bus route_event_publisher 单测（mock 发布）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.neuro_bus.route_event_publisher import (
    RouteEvents,
    publish_route_event,
    publish_simple_event,
)


@pytest.mark.asyncio
async def test_publish_route_event_async_success(monkeypatch):
    monkeypatch.setenv("XCAGI_NEURO_INTENT", "1")
    published: list[str] = []

    def _capture(event_type, payload, domain="api"):
        published.append(event_type)
        return True

    with patch(
        "app.neuro_bus.route_event_publisher.is_neuro_stack_enabled",
        return_value=True,
    ), patch(
        "app.neuro_bus.route_event_publisher.publish_neuro_event",
        side_effect=_capture,
    ):
        @publish_route_event("unit.test", domain="unit")
        async def handler(request=None):
            return {"ok": True}

        request = MagicMock()
        request.method = "POST"
        request.url.path = "/unit"
        request.client = MagicMock(host="127.0.0.1")
        result = await handler(request)
        assert result == {"ok": True}
        assert "unit.test.started" in published
        assert "unit.test.completed" in published


def test_publish_route_event_sync_skips_when_disabled(monkeypatch):
    with patch(
        "app.neuro_bus.route_event_publisher.is_neuro_stack_enabled",
        return_value=False,
    ), patch("app.neuro_bus.route_event_publisher.publish_neuro_event") as pub:
        @publish_route_event("sync.test")
        def handler():
            return 42

        assert handler() == 42
        pub.assert_not_called()


@pytest.mark.asyncio
async def test_publish_route_event_async_failure():
    with patch(
        "app.neuro_bus.route_event_publisher.is_neuro_stack_enabled",
        return_value=True,
    ), patch(
        "app.neuro_bus.route_event_publisher.publish_neuro_event",
        return_value=True,
    ) as pub:
        @publish_route_event("fail.test")
        async def handler():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await handler()
        calls = [c.args[0] for c in pub.call_args_list]
        assert "fail.test.failed" in calls


def test_publish_simple_event_disabled():
    with patch(
        "app.neuro_bus.route_event_publisher.is_neuro_stack_enabled",
        return_value=False,
    ):
        assert publish_simple_event("x", {"a": 1}) is False


def test_publish_simple_event_success():
    with patch(
        "app.neuro_bus.route_event_publisher.is_neuro_stack_enabled",
        return_value=True,
    ), patch(
        "app.neuro_bus.route_event_publisher.publish_neuro_event",
        return_value=True,
    ):
        assert publish_simple_event("chat.request", {"id": 1}, domain="ai") is True


def test_route_events_constants():
    assert RouteEvents.CHAT_REQUEST == "chat.request"
    assert RouteEvents.HEALTH_CHECK == "health.check"
