"""Proactive events dedupe, persist and fan out without duplicating alerts."""

from __future__ import annotations

from app.application.proactive.service import (
    DEDUPE_WINDOW_SECONDS,
    ProactiveEvent,
    ProactiveService,
    apprise_sender,
)


def event(**overrides):
    base = {"kind": "inventory_low", "title": "库存不足", "detail": "华东仓低于安全线"}
    base.update(overrides)
    return ProactiveEvent(**base)


def test_duplicate_event_is_deduped_within_window(tmp_path):
    now = 1000.0
    service = ProactiveService(tmp_path, clock=lambda: now)
    first = service.publish(event())
    second = service.publish(event())
    assert first["deduped"] is False
    assert second["deduped"] is True
    assert len(service.recent()) == 1


def test_event_is_republished_after_window(tmp_path):
    clock = {"now": 1000.0}
    service = ProactiveService(tmp_path, clock=lambda: clock["now"])
    service.publish(event())
    clock["now"] += DEDUPE_WINDOW_SECONDS + 1
    again = service.publish(event())
    assert again["deduped"] is False
    assert len(service.recent()) == 2


def test_channel_failure_keeps_event_and_reports_error(tmp_path):
    def broken(_event):
        raise RuntimeError("渠道不可用")

    result = ProactiveService(tmp_path, senders=[broken]).publish(event())
    assert result["ok"] is True and result["deduped"] is False
    assert any("渠道不可用" in item for item in result["errors"])


def test_successful_senders_are_recorded(tmp_path):
    seen = []
    result = ProactiveService(tmp_path, senders=[seen.append]).publish(event())
    assert result["delivered"] == ["append"]
    assert seen[0].title == "库存不足"


def test_apprise_sender_is_noop_without_urls(monkeypatch):
    monkeypatch.delenv("PROACTIVE_APPRISE_URLS", raising=False)
    apprise_sender()(event())  # must not import apprise or raise
