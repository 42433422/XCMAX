"""同步 outbox 补推调度器：有积压才推，无积压不碰网络。"""

from __future__ import annotations

from app.desktop_runtime import sync_outbox_scheduler as scheduler


class _FakeSyncDb:
    def __init__(self, pending: list[dict]):
        self._pending = pending

    def get_pending_outbox(self, limit: int = 100):
        return self._pending[:limit]


def test_push_skips_network_when_outbox_empty(monkeypatch):
    monkeypatch.setattr("app.db.xcmax_sync.SyncDb", lambda: _FakeSyncDb([]))

    def _fail_push(**_kwargs):
        raise AssertionError("should not push when outbox is empty")

    monkeypatch.setattr("app.application.xcmax_sync_app.push_outbox", _fail_push)
    result = scheduler.push_pending_outbox_once()
    assert result == {"sent": 0, "failed": 0, "total_pending": 0}


def test_push_delegates_when_outbox_has_pending(monkeypatch):
    monkeypatch.setattr(
        "app.db.xcmax_sync.SyncDb",
        lambda: _FakeSyncDb([{"id": 1, "entity_type": "private_mod_delivery"}]),
    )
    calls: list[dict] = []

    def _push(**kwargs):
        calls.append(kwargs)
        return {"sent": 1, "failed": 0, "total_pending": 1}

    monkeypatch.setattr("app.application.xcmax_sync_app.push_outbox", _push)
    result = scheduler.push_pending_outbox_once()
    assert result["sent"] == 1
    assert len(calls) == 1
    assert calls[0]["remote_host"]


def test_scheduler_does_not_start_under_pytest():
    scheduler.start_sync_outbox_scheduler()
    assert scheduler._thread is None


def test_scheduler_disabled_by_env(monkeypatch):
    monkeypatch.setenv("XCMAX_SYNC_AUTO_PUSH", "0")
    assert scheduler._enabled() is False
    monkeypatch.setenv("XCMAX_SYNC_AUTO_PUSH", "1")
    assert scheduler._enabled() is True


def test_interval_respects_env_and_minimum(monkeypatch):
    monkeypatch.setenv("XCMAX_SYNC_PUSH_INTERVAL_SECONDS", "5")
    assert scheduler._interval_seconds() == 30
    monkeypatch.setenv("XCMAX_SYNC_PUSH_INTERVAL_SECONDS", "300")
    assert scheduler._interval_seconds() == 300
    monkeypatch.delenv("XCMAX_SYNC_PUSH_INTERVAL_SECONDS")
    assert scheduler._interval_seconds() == 120
