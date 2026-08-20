# mypy: disable-error-code="arg-type, exit-return"
"""COVERAGE_RAMP Phase 4 round 16: xcmax_sync_service helpers + push/pull/apply (33%→)."""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import xcmax_sync_service as svc

# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_utc_now_ms_positive() -> None:
    assert svc.utc_now_ms() > 1_600_000_000_000


def test_payload_updated_at_ms() -> None:
    assert svc._payload_updated_at_ms({"meta": {"updated_at_ms": 123}}) == 123
    assert svc._payload_updated_at_ms({}) == 0
    assert svc._payload_updated_at_ms({"meta": {}}) == 0


def test_sync_meta_roundtrip(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "sync.db"
    import app.db.xcmax_sync as xs

    monkeypatch.setattr(xs, "_resolve_db_path", lambda: db_path)
    # empty read on fresh db
    assert svc._read_sync_meta("k") == {}
    svc._write_sync_meta("k", {"a": 1})
    assert svc._read_sync_meta("k") == {"a": 1}


def test_register_entity_applier() -> None:
    @svc.register_entity_applier("__test_entity__")
    def _applier(item):  # noqa: ANN001
        return None

    assert svc._ENTITY_APPLIERS["__test_entity__"] is _applier
    del svc._ENTITY_APPLIERS["__test_entity__"]


def test_csrf_token_from_jar_covers_empty_nonmatching_and_valid_cookie() -> None:
    assert svc._csrf_token_from_jar([]) == ""
    jar = [
        SimpleNamespace(name="session_id", value="sid"),
        SimpleNamespace(name="csrf_token", value="  "),
        SimpleNamespace(name="csrf_token", value="csrf-123"),
    ]
    assert svc._csrf_token_from_jar(jar) == "csrf-123"


def test_open_sync_request_uses_direct_opener_when_urlopen_is_default() -> None:
    req = urllib.request.Request("http://example.invalid/api/health", method="GET")
    opener = MagicMock()
    opener.open.return_value = _FakeResp(b"ok")

    assert svc._open_sync_request(opener, req, timeout=1).read() == b"ok"
    opener.open.assert_called_once_with(req, timeout=1)


def test_open_sync_request_honors_monkeypatched_urlopen() -> None:
    req = urllib.request.Request("http://example.invalid/api/health", method="GET")
    opener = MagicMock()
    with patch("urllib.request.urlopen", return_value=_FakeResp(b"patched")) as urlopen:
        assert svc._open_sync_request(opener, req, timeout=2).read() == b"patched"
    urlopen.assert_called_once_with(req, timeout=2)
    opener.open.assert_not_called()


def test_sync_payload_list_filters_blank_and_duplicates() -> None:
    assert svc._sync_payload_list("not-list") == []
    assert svc._sync_payload_list([" mod-a ", "", None, "mod-a", "mod-b"]) == [
        "mod-a",
        "mod-b",
    ]


def test_apply_account_entitlements_skips_invalid_payloads() -> None:
    with patch.object(svc, "_write_sync_meta") as write_meta:
        svc._apply_account_entitlements({"payload": "bad"})
        svc._apply_account_entitlements({"payload": {"username": "alice"}})
        svc._apply_account_entitlements({"entity_id": "42", "payload": {}})
    write_meta.assert_not_called()


class _DbContext:
    def __init__(self, db: MagicMock) -> None:
        self._db = db

    def __enter__(self) -> MagicMock:
        return self._db

    def __exit__(self, *args) -> bool:  # noqa: ANN002
        return False


class _FakeUser:
    username = "username-column"

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        self.__dict__.update(kwargs)


def test_apply_account_entitlements_creates_user_and_normalizes_payload() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    payload = {
        "profile": {
            "username": "alice",
            "account_tier": "pro",
            "budget_range": "10-20",
            "entitled_industries": ["retail"],
        },
        "is_enterprise": True,
        "industry_id": "food",
        "mod_ids": [" mod-a ", "", "mod-a", "mod-b"],
        "email": " alice@example.com ",
    }

    with (
        patch.object(svc, "_write_sync_meta") as write_meta,
        patch("app.db.models.user.User", _FakeUser),
        patch("app.db.session.get_db", return_value=_DbContext(db)),
    ):
        svc._apply_account_entitlements({"entity_id": "42", "payload": payload})

    assert write_meta.call_count == 2
    stored = write_meta.call_args_list[0].args[1]
    assert stored["market_user_id"] == "42"
    assert stored["mod_ids"] == ["mod-a", "mod-b"]
    created = db.add.call_args.args[0]
    assert created.username == "alice"
    assert created.tier == "enterprise"
    assert created.account_tier == "pro"
    assert created.industry_id == "food"
    assert created.entitled_industries == ["retail", "food"]
    assert created.email == "alice@example.com"
    db.flush.assert_called_once()
    db.commit.assert_called_once()


def test_apply_account_entitlements_updates_existing_personal_user() -> None:
    db = MagicMock()
    existing = SimpleNamespace(username="bob")
    db.query.return_value.filter.return_value.first.return_value = existing
    payload = {
        "profile": {
            "username": "bob",
            "tier": "personal",
            "account_tier": "ignored",
            "entitled_industries": ["general"],
        },
        "industry_id": "general",
        "mod_ids": [],
    }

    with (
        patch.object(svc, "_write_sync_meta"),
        patch("app.db.models.user.User", _FakeUser),
        patch("app.db.session.get_db", return_value=_DbContext(db)),
    ):
        svc._apply_account_entitlements({"entity_id": "7", "payload": payload})

    db.add.assert_not_called()
    assert existing.tier == "personal"
    assert existing.account_tier is None
    assert existing.entitled_industries == ["general"]
    assert not hasattr(existing, "email")
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# record_change
# ---------------------------------------------------------------------------


def test_record_change_success() -> None:
    fake_db = MagicMock()
    fake_db.append_change.return_value = 7
    with patch("app.db.xcmax_sync.SyncDb", return_value=fake_db):
        out = svc.record_change("attendance", "1", "insert", {"x": 1})
    assert out == 7
    fake_db.append_change.assert_called_once()


def test_record_change_failure_returns_minus_one() -> None:
    with patch("app.db.xcmax_sync.SyncDb", side_effect=RuntimeError("boom")):
        assert svc.record_change("attendance", "1", "insert", {}) == -1


# ---------------------------------------------------------------------------
# push_outbox
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, data: bytes = b"") -> None:
        self._data = data

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *a):  # noqa: ANN002, ANN204
        return False

    def read(self, n: int = -1) -> bytes:
        return self._data


def test_push_outbox_empty() -> None:
    fake_db = MagicMock()
    fake_db.get_pending_outbox.return_value = []
    with patch("app.db.xcmax_sync.SyncDb", return_value=fake_db):
        out = svc.push_outbox(remote_host="h", remote_port=1)
    assert out == {"sent": 0, "failed": 0, "total_pending": 0}


def test_push_outbox_sends_item() -> None:
    fake_db = MagicMock()
    fake_db.get_pending_outbox.return_value = [
        {
            "id": 1,
            "entity_type": "attendance",
            "entity_id": "9",
            "operation": "insert",
            "payload": {},
        }
    ]
    with (
        patch("app.db.xcmax_sync.SyncDb", return_value=fake_db),
        patch("urllib.request.urlopen", return_value=_FakeResp(b"ok")),
    ):
        out = svc.push_outbox(remote_host="h", remote_port=1)
    assert out["sent"] == 1
    fake_db.mark_outbox_sent.assert_called_once_with(1)


def test_push_outbox_http_error() -> None:
    fake_db = MagicMock()
    fake_db.get_pending_outbox.return_value = [
        {
            "id": 2,
            "entity_type": "attendance",
            "entity_id": "9",
            "operation": "insert",
            "payload": {},
        }
    ]
    err = urllib.error.HTTPError("u", 500, "Server Error", {}, None)  # type: ignore[arg-type]
    with (
        patch("app.db.xcmax_sync.SyncDb", return_value=fake_db),
        patch("urllib.request.urlopen", side_effect=err),
    ):
        out = svc.push_outbox(remote_host="h", remote_port=1)
    assert out["failed"] == 1
    fake_db.mark_outbox_failed.assert_called_once()


def test_push_outbox_recoverable_error() -> None:
    fake_db = MagicMock()
    fake_db.get_pending_outbox.return_value = [
        {
            "id": 3,
            "entity_type": "attendance",
            "entity_id": "9",
            "operation": "insert",
            "payload": {},
        }
    ]
    with (
        patch("app.db.xcmax_sync.SyncDb", return_value=fake_db),
        patch("urllib.request.urlopen", side_effect=OSError("netdown")),
    ):
        out = svc.push_outbox(remote_host="h", remote_port=1)
    assert out["failed"] == 1


# ---------------------------------------------------------------------------
# pull_from_remote
# ---------------------------------------------------------------------------


def test_pull_from_remote_with_changes() -> None:
    fake_db = MagicMock()
    fake_db.get_status.return_value = {"remote_cursor": 0}
    body = json.dumps({"data": [{"id": 5, "entity_type": "x"}]}).encode("utf-8")
    with (
        patch("app.db.xcmax_sync.SyncDb", return_value=fake_db),
        patch("urllib.request.urlopen", return_value=_FakeResp(body)),
    ):
        out = svc.pull_from_remote(remote_host="h", remote_port=1)
    assert out["pulled"] == 1
    fake_db.enqueue_inbox.assert_called_once()
    fake_db.update_remote_cursor.assert_called_once_with(5)


def test_pull_from_remote_empty() -> None:
    fake_db = MagicMock()
    fake_db.get_status.return_value = {"remote_cursor": 3}
    body = json.dumps({"data": []}).encode("utf-8")
    with (
        patch("app.db.xcmax_sync.SyncDb", return_value=fake_db),
        patch("urllib.request.urlopen", return_value=_FakeResp(body)),
    ):
        out = svc.pull_from_remote(remote_host="h", remote_port=1, since_cursor=3)
    assert out["pulled"] == 0


def test_pull_from_remote_error() -> None:
    fake_db = MagicMock()
    fake_db.get_status.return_value = {"remote_cursor": 0}
    with (
        patch("app.db.xcmax_sync.SyncDb", return_value=fake_db),
        patch("urllib.request.urlopen", side_effect=OSError("boom")),
    ):
        out = svc.pull_from_remote(remote_host="h", remote_port=1)
    assert out["pulled"] == 0
    assert "error" in out


# ---------------------------------------------------------------------------
# apply_inbox
# ---------------------------------------------------------------------------


def _seed_inbox(db_path, rows) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE sync_inbox (id INTEGER PRIMARY KEY, entity_type TEXT, entity_id TEXT, "
        "operation TEXT, payload_json TEXT, status TEXT)"
    )
    conn.executemany(
        "INSERT INTO sync_inbox (id, entity_type, entity_id, operation, payload_json, status) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_apply_inbox_applies_and_skips(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "inbox.db"
    _seed_inbox(
        db_path,
        [
            (1, "__rt_entity__", "a", "insert", json.dumps({"v": 1}), "pending"),
            (2, "__unknown_entity__", "b", "insert", "{}", "pending"),
        ],
    )
    import app.db.xcmax_sync as xs

    monkeypatch.setattr(xs, "_resolve_db_path", lambda: db_path)

    seen = []

    @svc.register_entity_applier("__rt_entity__")
    def _applier(item):  # noqa: ANN001
        seen.append(item)

    fake_db = MagicMock()
    try:
        with patch("app.db.xcmax_sync.SyncDb", return_value=fake_db):
            out = svc.apply_inbox(limit=10)
    finally:
        del svc._ENTITY_APPLIERS["__rt_entity__"]

    assert out["applied"] == 2
    assert len(seen) == 1
    assert fake_db.mark_inbox_applied.call_count == 2


def test_apply_inbox_conflict_on_applier_error(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "inbox2.db"
    _seed_inbox(
        db_path,
        [(1, "__boom_entity__", "a", "insert", "{}", "pending")],
    )
    import app.db.xcmax_sync as xs

    monkeypatch.setattr(xs, "_resolve_db_path", lambda: db_path)

    @svc.register_entity_applier("__boom_entity__")
    def _applier(item):  # noqa: ANN001
        raise ValueError("bad")

    fake_db = MagicMock()
    try:
        with patch("app.db.xcmax_sync.SyncDb", return_value=fake_db):
            out = svc.apply_inbox(limit=10)
    finally:
        del svc._ENTITY_APPLIERS["__boom_entity__"]

    assert out["conflicts"] == 1
    assert out["errors"] == 1
    fake_db.mark_inbox_conflict.assert_called_once()


def test_apply_inbox_read_failure(monkeypatch) -> None:
    import app.db.xcmax_sync as xs

    monkeypatch.setattr(xs, "_resolve_db_path", lambda: "/nonexistent/dir/x.db")
    fake_db = MagicMock()
    with (
        patch("app.db.xcmax_sync.SyncDb", return_value=fake_db),
        patch("sqlite3.connect", side_effect=OSError("cannot open")),
    ):
        out = svc.apply_inbox()
    assert out == {"applied": 0, "errors": 1}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
