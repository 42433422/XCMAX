"""Tests for the mobile-push application boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.application import mobile_push_app_service
from app.services import mobile_push


def test_notify_mobile_user_forwards_delivery_scope(monkeypatch):
    calls = []

    def fake_notify(user_id, title, body, data, *, audience, tenant_id):
        calls.append((user_id, title, body, data, audience, tenant_id))
        return {"fcm": True, "outbox": True}

    monkeypatch.setattr(mobile_push, "notify_user", fake_notify)

    result = mobile_push_app_service.notify_mobile_user(
        17,
        title="员工已交付",
        body="管理任务等待验收",
        data={"task_id": "mwi_1"},
        audience="management",
        tenant_id=8,
    )

    assert result == {"fcm": True, "outbox": True}
    assert calls == [
        (
            17,
            "员工已交付",
            "管理任务等待验收",
            {"task_id": "mwi_1"},
            "management",
            8,
        )
    ]


def test_notification_schema_and_scope_delegate(monkeypatch):
    db = object()
    user = SimpleNamespace(id=17)
    seen = []
    monkeypatch.setattr(
        mobile_push,
        "ensure_mobile_notification_schema",
        lambda value: seen.append(value),
    )
    monkeypatch.setattr(
        mobile_push,
        "notification_scope_for_user",
        lambda value: ("management", 8) if value is user else ("enterprise", 0),
    )

    mobile_push_app_service.ensure_mobile_notification_schema(db)

    assert seen == [db]
    assert mobile_push_app_service.notification_scope_for_user(user) == (
        "management",
        8,
    )


def test_notify_mobile_user_preserves_dependency_errors(monkeypatch):
    def fail_notify(*_args, **_kwargs):
        raise RuntimeError("push unavailable")

    monkeypatch.setattr(mobile_push, "notify_user", fail_notify)

    with pytest.raises(RuntimeError, match="push unavailable"):
        mobile_push_app_service.notify_mobile_user(17, "title", "body")
