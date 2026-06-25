"""Behavior tests for app.services.xcmax_sync_service.

These tests assert observable behavior of the bidirectional sync service:
  - helper math (utc_now_ms / _payload_updated_at_ms)
  - sync_meta read/write against a real temp SQLite
  - record_change / push_outbox / pull_from_remote against a mocked SyncDb + urllib
  - every registered entity applier, asserting the *rows it writes* (real SQLite for
    sync_meta-backed appliers) or the *exact ORM mutations* (mocked get_db for the
    SQLAlchemy-backed appliers), including both branches (skip vs apply, insert vs
    update, delete, LWW newer vs older).

The source modules are never modified; where the implementation swallows a class of
errors (``OPERATIONAL_ERRORS`` is very wide), the tests assert the *resulting* state
(e.g. no row written, no commit) rather than that an exception escaped.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import UTC, datetime
from unittest.mock import ANY, MagicMock, patch

import pytest

from app.services.xcmax_sync_service import (
    _ENTITY_APPLIERS,
    _payload_updated_at_ms,
    apply_inbox,
    pull_from_remote,
    push_outbox,
    record_change,
    register_entity_applier,
    utc_now_ms,
)


def _mock_get_db(mock_db):
    """Create a contextmanager mock for get_db generator."""

    @contextlib.contextmanager
    def _get_db():
        yield mock_db

    return _get_db


def _taiyangniao_schema(db_path):
    """Create the subset of taiyangniao_pro.db tables the personnel/department
    appliers write to, so we can assert the rows they insert."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE attendance_employees (
            source_file TEXT, employee_name TEXT, department TEXT, main_department TEXT,
            attendance_group TEXT, employee_no TEXT, position TEXT, user_id TEXT,
            UNIQUE(employee_name)
        );
        CREATE TABLE products (
            source_file TEXT, model_number TEXT, name TEXT, specification TEXT,
            price REAL, unit TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE attendance_departments (
            source_file TEXT, department TEXT, main_department TEXT, attendance_group TEXT,
            UNIQUE(department)
        );
        CREATE TABLE customers (
            source_file TEXT, customer_name TEXT, contact_person TEXT, contact_phone TEXT,
            address TEXT, purchase_unit TEXT, created_at TEXT, updated_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestUtcNowMs:
    def test_returns_positive_int(self):
        val = utc_now_ms()
        assert isinstance(val, int)
        assert val > 0

    def test_returns_millisecond_precision(self):
        val = utc_now_ms()
        now_s = datetime.now(UTC).timestamp()
        assert abs(val / 1000 - now_s) < 2  # within 2 seconds

    def test_monotonic_non_decreasing(self):
        a = utc_now_ms()
        b = utc_now_ms()
        assert b >= a


class TestPayloadUpdatedAtMs:
    def test_extracts_ms_from_meta(self):
        payload = {"meta": {"updated_at_ms": 1700000000000}}
        assert _payload_updated_at_ms(payload) == 1700000000000

    def test_returns_zero_when_meta_missing(self):
        assert _payload_updated_at_ms({}) == 0
        assert _payload_updated_at_ms({"meta": None}) == 0

    def test_returns_zero_when_updated_at_ms_missing(self):
        assert _payload_updated_at_ms({"meta": {}}) == 0

    def test_returns_zero_when_value_falsy(self):
        # 0 / None coerce to 0 via the `or 0` guard
        assert _payload_updated_at_ms({"meta": {"updated_at_ms": 0}}) == 0
        assert _payload_updated_at_ms({"meta": {"updated_at_ms": None}}) == 0

    def test_converts_non_int_to_int(self):
        assert _payload_updated_at_ms({"meta": {"updated_at_ms": "12345"}}) == 12345


# ---------------------------------------------------------------------------
# _read_sync_meta / _write_sync_meta — use real temp SQLite
# ---------------------------------------------------------------------------


class TestReadSyncMeta:
    def test_returns_empty_when_key_missing(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            from app.services.xcmax_sync_service import _read_sync_meta

            result = _read_sync_meta("nonexistent_key")
        assert result == {}

    def test_reads_written_value(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            from app.services.xcmax_sync_service import _read_sync_meta, _write_sync_meta

            _write_sync_meta("test_key", {"foo": "bar"})
            result = _read_sync_meta("test_key")
        assert result == {"foo": "bar"}

    def test_handles_corrupt_json(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            from app.services.xcmax_sync_service import _read_sync_meta, _write_sync_meta

            _write_sync_meta("bad_key", {"a": 1})
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "UPDATE sync_meta SET value=? WHERE key=?",
                ("not-json{{{", "bad_key"),
            )
            conn.commit()
            conn.close()
            result = _read_sync_meta("bad_key")
        # corrupt JSON is tolerated and degrades to {} rather than raising
        assert result == {}


class TestWriteSyncMeta:
    def test_write_and_read_roundtrip(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            from app.services.xcmax_sync_service import _read_sync_meta, _write_sync_meta

            _write_sync_meta("k1", {"x": 1})
            _write_sync_meta("k1", {"x": 2})  # overwrite (INSERT OR REPLACE)
            result = _read_sync_meta("k1")
        assert result == {"x": 2}

    def test_preserves_unicode_payload(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            from app.services.xcmax_sync_service import _read_sync_meta, _write_sync_meta

            _write_sync_meta("u1", {"name": "张三", "n": 7})
            assert _read_sync_meta("u1") == {"name": "张三", "n": 7}


# ---------------------------------------------------------------------------
# record_change
# ---------------------------------------------------------------------------


class TestRecordChange:
    def test_returns_positive_id_on_success(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            result = record_change("personnel", "123", "insert", {"name": "张三"})
        assert isinstance(result, int)
        assert result > 0

    def test_persists_change_and_enqueues_outbox(self, tmp_path):
        """A local change must land in sync_changes AND sync_outbox (origin=local)."""
        db_path = tmp_path / "test_sync.db"
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            change_id = record_change("attendance", "777", "insert", {"product_name": "罐头"})
        conn = sqlite3.connect(str(db_path))
        change_row = conn.execute(
            "SELECT entity_type, entity_id, operation, payload_json FROM sync_changes WHERE id=?",
            (change_id,),
        ).fetchone()
        outbox_row = conn.execute(
            "SELECT entity_type, entity_id, operation, status FROM sync_outbox WHERE change_id=?",
            (change_id,),
        ).fetchone()
        conn.close()
        assert change_row == ("attendance", "777", "insert", '{"product_name": "罐头"}')
        assert outbox_row == ("attendance", "777", "insert", "pending")

    def test_returns_negative_on_recoverable_error(self):
        with patch("app.db.xcmax_sync.SyncDb") as MockSyncDb:
            MockSyncDb.side_effect = OSError("disk full")
            result = record_change("personnel", "123", "insert", {"name": "张三"})
        assert result == -1

    def test_passes_all_params_to_sync_db(self):
        mock_db = MagicMock()
        mock_db.append_change.return_value = 42
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db):
            returned = record_change(
                "attendance",
                "456",
                "update",
                {"status": "done"},
                actor="admin",
                version=2,
            )
        assert returned == 42
        mock_db.append_change.assert_called_once_with(
            entity_type="attendance",
            entity_id="456",
            operation="update",
            payload={"status": "done"},
            version=2,
            actor="admin",
            origin_node=ANY,
            enqueue_outbox=True,
        )

    def test_coerces_entity_id_to_str(self):
        """An int entity_id must be stringified before hitting the DB layer."""
        mock_db = MagicMock()
        mock_db.append_change.return_value = 1
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db):
            record_change("personnel", 999, "insert", {})
        assert mock_db.append_change.call_args.kwargs["entity_id"] == "999"


# ---------------------------------------------------------------------------
# push_outbox
# ---------------------------------------------------------------------------


def _http_ok_response():
    resp = MagicMock()
    resp.read.return_value = b"ok"
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _outbox_item(item_id, entity_type="personnel", op="insert", payload=None):
    return {
        "id": item_id,
        "entity_type": entity_type,
        "entity_id": str(item_id),
        "operation": op,
        "payload": payload or {},
    }


class TestPushOutbox:
    def test_empty_pending_returns_zeros(self):
        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = []
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db):
            result = push_outbox()
        assert result == {"sent": 0, "failed": 0, "total_pending": 0}
        mock_db.mark_outbox_sent.assert_not_called()

    def test_push_marks_sent_on_success(self):
        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = [_outbox_item(1, payload={"name": "t"})]
        with (
            patch(
                "app.services.xcmax_sync_service.urllib.request.urlopen",
                return_value=_http_ok_response(),
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = push_outbox(remote_host="127.0.0.1", remote_port=8080)

        assert result == {"sent": 1, "failed": 0, "total_pending": 1}
        mock_db.mark_outbox_sent.assert_called_once_with(1)
        mock_db.mark_outbox_failed.assert_not_called()

    def test_push_posts_to_receive_endpoint_with_payload(self):
        """The HTTP request must target /api/xcmax/sync/receive with a JSON body
        carrying the entity fields — proving the wire contract, not just a mock call."""
        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = [
            _outbox_item(1, entity_type="attendance", op="update", payload={"status": "x"})
        ]
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _http_ok_response()

        with (
            patch(
                "app.services.xcmax_sync_service.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            push_outbox(remote_host="1.2.3.4", remote_port=8888)

        assert captured["url"] == "http://1.2.3.4:8888/api/xcmax/sync/receive"
        assert captured["method"] == "POST"
        assert captured["body"]["entity_type"] == "attendance"
        assert captured["body"]["operation"] == "update"
        assert captured["body"]["payload"] == {"status": "x"}
        assert "origin_node" in captured["body"]

    def test_push_marks_failed_on_http_5xx_error_with_retry(self):
        import urllib.error

        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = [_outbox_item(1)]
        with (
            patch(
                "app.services.xcmax_sync_service.urllib.request.urlopen",
                side_effect=urllib.error.HTTPError("url", 500, "Internal", {}, None),
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = push_outbox()

        assert result["failed"] == 1
        assert result["sent"] == 0
        # 5xx is transient → retry=True so the item stays pending
        mock_db.mark_outbox_failed.assert_called_once_with(1, "HTTP 500: Internal", retry=True)
        mock_db.mark_outbox_sent.assert_not_called()

    def test_push_marks_failed_on_4xx_no_retry(self):
        import urllib.error

        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = [_outbox_item(1)]
        with (
            patch(
                "app.services.xcmax_sync_service.urllib.request.urlopen",
                side_effect=urllib.error.HTTPError("url", 404, "Not Found", {}, None),
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = push_outbox()

        assert result["failed"] == 1
        # 4xx is a permanent client error → retry=False so it is dead-lettered
        mock_db.mark_outbox_failed.assert_called_once_with(1, "HTTP 404: Not Found", retry=False)

    def test_push_marks_failed_on_recoverable_error_with_retry(self):
        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = [_outbox_item(1)]
        with (
            patch(
                "app.services.xcmax_sync_service.urllib.request.urlopen",
                side_effect=ConnectionError("refused"),
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = push_outbox()

        assert result["failed"] == 1
        # connection error is transient → retry=True
        mock_db.mark_outbox_failed.assert_called_once_with(1, "refused", retry=True)

    def test_push_handles_mixed_success_and_failure(self):
        """First item succeeds, second fails: counts split and each item marked correctly."""
        import urllib.error

        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = [
            _outbox_item(1),
            _outbox_item(2, entity_type="department", op="update"),
        ]
        calls = iter([_http_ok_response(), urllib.error.HTTPError("u", 503, "Busy", {}, None)])

        def fake_urlopen(req, timeout=None):
            nxt = next(calls)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt

        with (
            patch(
                "app.services.xcmax_sync_service.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = push_outbox()

        assert result == {"sent": 1, "failed": 1, "total_pending": 2}
        mock_db.mark_outbox_sent.assert_called_once_with(1)
        mock_db.mark_outbox_failed.assert_called_once_with(2, "HTTP 503: Busy", retry=True)


# ---------------------------------------------------------------------------
# pull_from_remote
# ---------------------------------------------------------------------------


def _json_response(obj):
    resp = MagicMock()
    resp.read.return_value = json.dumps(obj).encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestPullFromRemote:
    def test_pull_writes_changes_to_inbox_and_advances_cursor(self):
        mock_db = MagicMock()
        mock_db.get_status.return_value = {"remote_cursor": 0}
        changes = [
            {
                "id": 10,
                "entity_type": "personnel",
                "entity_id": "1",
                "operation": "insert",
                "payload": {"name": "test"},
            }
        ]
        with (
            patch(
                "app.services.xcmax_sync_service.urllib.request.urlopen",
                return_value=_json_response({"data": changes}),
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = pull_from_remote(remote_host="127.0.0.1", remote_port=8080)

        assert result == {"pulled": 1, "since_cursor": 0}
        mock_db.enqueue_inbox.assert_called_once_with(changes, remote_cursor=10)
        # cursor advances to the last change id (10)
        mock_db.update_remote_cursor.assert_called_once_with(10)

    def test_pull_returns_zero_on_empty_data_without_touching_cursor(self):
        mock_db = MagicMock()
        mock_db.get_status.return_value = {"remote_cursor": 0}
        with (
            patch(
                "app.services.xcmax_sync_service.urllib.request.urlopen",
                return_value=_json_response({"data": []}),
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = pull_from_remote()

        assert result["pulled"] == 0
        mock_db.enqueue_inbox.assert_not_called()
        mock_db.update_remote_cursor.assert_not_called()

    def test_pull_returns_error_on_failure(self):
        mock_db = MagicMock()
        mock_db.get_status.return_value = {"remote_cursor": 0}
        with (
            patch(
                "app.services.xcmax_sync_service.urllib.request.urlopen",
                side_effect=ConnectionError("timeout"),
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = pull_from_remote()

        assert result == {"pulled": 0, "error": "timeout"}
        mock_db.enqueue_inbox.assert_not_called()

    def test_pull_explicit_since_cursor_overrides_status(self):
        mock_db = MagicMock()
        mock_db.get_status.return_value = {"remote_cursor": 5}
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            return _json_response({"data": []})

        with (
            patch(
                "app.services.xcmax_sync_service.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = pull_from_remote(since_cursor=42)

        assert result["since_cursor"] == 42
        # explicit cursor wins over status' remote_cursor and is sent in the query
        assert "since_cursor=42" in captured["url"]

    def test_pull_falls_back_to_status_remote_cursor(self):
        mock_db = MagicMock()
        mock_db.get_status.return_value = {"remote_cursor": 100}
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            return _json_response({"data": []})

        with (
            patch(
                "app.services.xcmax_sync_service.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = pull_from_remote()

        assert result["since_cursor"] == 100
        assert "since_cursor=100" in captured["url"]


# ---------------------------------------------------------------------------
# register_entity_applier
# ---------------------------------------------------------------------------


class TestRegisterEntityApplier:
    def test_registers_and_returns_same_function(self):
        @register_entity_applier("test_entity_type_xyz")
        def my_applier(item):
            return "applied"

        # decorator must register under the key AND return the original function
        assert _ENTITY_APPLIERS["test_entity_type_xyz"] is my_applier
        assert my_applier({}) == "applied"

    def test_registered_applier_is_invoked_with_item(self):
        @register_entity_applier("test_entity_type_abc")
        def my_applier2(item):
            return item["payload"]["k"]

        result = _ENTITY_APPLIERS["test_entity_type_abc"]({"payload": {"k": "val"}})
        assert result == "val"

    def test_last_registration_wins(self):
        @register_entity_applier("dup_key_qrs")
        def first(item):
            return "first"

        @register_entity_applier("dup_key_qrs")
        def second(item):
            return "second"

        assert _ENTITY_APPLIERS["dup_key_qrs"]({}) == "second"


# ---------------------------------------------------------------------------
# apply_inbox
# ---------------------------------------------------------------------------


def _insert_inbox_row(db_path, *, entity_type, entity_id, operation, payload):
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO sync_inbox (remote_cursor, entity_type, entity_id, operation, "
        "payload_json, origin_node, received_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            entity_type,
            entity_id,
            operation,
            json.dumps(payload),
            "remote",
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


class TestApplyInbox:
    def test_applies_pending_item_and_marks_applied(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            from app.db.xcmax_sync import _ensure_schema

            conn = sqlite3.connect(str(db_path))
            _ensure_schema(conn)
            conn.close()
            _insert_inbox_row(
                db_path,
                entity_type="personnel",
                entity_id="99",
                operation="insert",
                payload={"name": "test"},
            )

            captured = {}
            mock_applier = MagicMock(side_effect=lambda item: captured.update(item=item))
            with patch.dict(_ENTITY_APPLIERS, {"personnel": mock_applier}, clear=False):
                result = apply_inbox()

            # row transitioned pending -> applied
            conn = sqlite3.connect(str(db_path))
            status = conn.execute("SELECT status FROM sync_inbox WHERE entity_id='99'").fetchone()[
                0
            ]
            conn.close()

        assert result["applied"] == 1
        assert result["errors"] == 0
        assert status == "applied"
        # the applier received the reconstructed item with parsed payload
        assert captured["item"]["entity_type"] == "personnel"
        assert captured["item"]["payload"] == {"name": "test"}

    def test_unknown_entity_type_is_skipped_but_still_marked_applied(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            from app.db.xcmax_sync import _ensure_schema

            conn = sqlite3.connect(str(db_path))
            _ensure_schema(conn)
            conn.close()
            _insert_inbox_row(
                db_path,
                entity_type="unknown_type_xyz",
                entity_id="99",
                operation="sync",
                payload={},
            )

            result = apply_inbox()

            conn = sqlite3.connect(str(db_path))
            status = conn.execute("SELECT status FROM sync_inbox").fetchone()[0]
            conn.close()

        # No applier registered, yet the row is consumed (counted + marked) so it does
        # not get re-processed forever.
        assert result["applied"] == 1
        assert result["errors"] == 0
        assert status == "applied"

    def test_applier_exception_marks_conflict_and_counts_error(self, tmp_path):
        """If an applier raises an operational error, the inbox row is flagged
        'conflict' and the error is counted — proving the conflict path, not a crash."""
        db_path = tmp_path / "test_sync.db"
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            from app.db.xcmax_sync import _ensure_schema

            conn = sqlite3.connect(str(db_path))
            _ensure_schema(conn)
            conn.close()
            _insert_inbox_row(
                db_path,
                entity_type="boom_type_jkl",
                entity_id="5",
                operation="sync",
                payload={},
            )

            boom = MagicMock(side_effect=ValueError("kaboom"))
            with patch.dict(_ENTITY_APPLIERS, {"boom_type_jkl": boom}, clear=False):
                result = apply_inbox()

            conn = sqlite3.connect(str(db_path))
            status, note = conn.execute(
                "SELECT status, conflict_note FROM sync_inbox WHERE entity_id='5'"
            ).fetchone()
            conn.close()

        assert result["applied"] == 0
        assert result["errors"] == 1
        assert result["conflicts"] == 1
        assert status == "conflict"
        assert "kaboom" in note

    def test_returns_error_on_db_read_failure(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        from app.db.xcmax_sync import _ensure_schema

        conn = sqlite3.connect(str(db_path))
        _ensure_schema(conn)
        conn.close()

        call_count = 0

        def resolve_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return db_path  # SyncDb() init succeeds
            raise OSError("db error")  # the read inside the try block fails

        with (
            patch("app.db.xcmax_sync._resolve_db_path", side_effect=resolve_side_effect),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            result = apply_inbox()

        assert result == {"applied": 0, "errors": 1}


# ---------------------------------------------------------------------------
# Entity appliers — personnel / department (real taiyangniao_pro.db SQLite)
# ---------------------------------------------------------------------------


class TestApplyPersonnel:
    def test_inserts_employee_and_product_rows(self, tmp_path):
        db_path = tmp_path / "taiyangniao_pro.db"
        _taiyangniao_schema(db_path)
        applier = _ENTITY_APPLIERS["personnel"]
        with patch(
            "app.mod_sdk.private_sqlite.resolve_mod_private_sqlite_path",
            return_value=db_path,
        ):
            applier(
                {
                    "payload": {
                        "name": "张三",
                        "department": "研发部",
                        "position": "工程师",
                        "employee_no": "E01",
                    },
                    "operation": "insert",
                }
            )
        conn = sqlite3.connect(str(db_path))
        emp = conn.execute(
            "SELECT employee_name, department, position, employee_no, source_file "
            "FROM attendance_employees"
        ).fetchone()
        prod = conn.execute("SELECT name, specification, unit FROM products").fetchone()
        conn.close()
        assert emp == ("张三", "研发部", "工程师", "E01", "xcmax_sync")
        # the personnel applier also mirrors the employee into the products table
        assert prod == ("张三", "工程师", "研发部")

    def test_accepts_employee_name_alias(self, tmp_path):
        db_path = tmp_path / "taiyangniao_pro.db"
        _taiyangniao_schema(db_path)
        applier = _ENTITY_APPLIERS["personnel"]
        with patch(
            "app.mod_sdk.private_sqlite.resolve_mod_private_sqlite_path",
            return_value=db_path,
        ):
            applier({"payload": {"employee_name": "李四"}, "operation": "insert"})
        conn = sqlite3.connect(str(db_path))
        names = [r[0] for r in conn.execute("SELECT employee_name FROM attendance_employees")]
        conn.close()
        assert names == ["李四"]

    def test_skips_when_name_empty_no_rows_written(self, tmp_path):
        db_path = tmp_path / "taiyangniao_pro.db"
        _taiyangniao_schema(db_path)
        applier = _ENTITY_APPLIERS["personnel"]
        with patch(
            "app.mod_sdk.private_sqlite.resolve_mod_private_sqlite_path",
            return_value=db_path,
        ):
            applier({"payload": {"name": "   "}, "operation": "insert"})
            applier({"payload": {}, "operation": "insert"})
        conn = sqlite3.connect(str(db_path))
        emp_count = conn.execute("SELECT COUNT(*) FROM attendance_employees").fetchone()[0]
        prod_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        conn.close()
        assert emp_count == 0
        assert prod_count == 0

    def test_db_error_is_swallowed(self):
        applier = _ENTITY_APPLIERS["personnel"]
        with patch(
            "app.mod_sdk.private_sqlite.resolve_mod_private_sqlite_path",
            side_effect=OSError("no db"),
        ):
            # must not raise even though the underlying DB path resolution fails
            applier({"payload": {"name": "张三"}, "operation": "insert"})


class TestApplyDepartment:
    def test_inserts_department_and_customer_rows(self, tmp_path):
        db_path = tmp_path / "taiyangniao_pro.db"
        _taiyangniao_schema(db_path)
        applier = _ENTITY_APPLIERS["department"]
        with patch(
            "app.mod_sdk.private_sqlite.resolve_mod_private_sqlite_path",
            return_value=db_path,
        ):
            applier(
                {
                    "payload": {"department": "研发部", "attendance_group": "G1"},
                    "operation": "insert",
                }
            )
        conn = sqlite3.connect(str(db_path))
        dept = conn.execute(
            "SELECT department, attendance_group FROM attendance_departments"
        ).fetchone()
        cust = conn.execute("SELECT customer_name, source_file FROM customers").fetchone()
        conn.close()
        assert dept == ("研发部", "G1")
        # department applier mirrors into customers
        assert cust == ("研发部", "xcmax_sync")

    def test_skips_when_dept_empty_no_rows_written(self, tmp_path):
        db_path = tmp_path / "taiyangniao_pro.db"
        _taiyangniao_schema(db_path)
        applier = _ENTITY_APPLIERS["department"]
        with patch(
            "app.mod_sdk.private_sqlite.resolve_mod_private_sqlite_path",
            return_value=db_path,
        ):
            applier({"payload": {"department": ""}, "operation": "insert"})
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM attendance_departments").fetchone()[0]
        conn.close()
        assert count == 0

    def test_db_error_is_swallowed(self):
        applier = _ENTITY_APPLIERS["department"]
        with patch(
            "app.mod_sdk.private_sqlite.resolve_mod_private_sqlite_path",
            side_effect=OSError("no db"),
        ):
            applier({"payload": {"department": "研发部"}, "operation": "insert"})


# ---------------------------------------------------------------------------
# Entity appliers — SQLAlchemy backed (mocked get_db, assert ORM mutations)
# ---------------------------------------------------------------------------


class TestApplyAttendance:
    def test_inserts_new_shipment_record(self):
        applier = _ENTITY_APPLIERS["attendance"]
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        captured = {}
        mock_db.add.side_effect = lambda o: captured.update(obj=o)
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {
                    "payload": {
                        "purchase_unit": "供应商A",
                        "product_name": "考勤组B",
                        "status": "done",
                        "quantity_tins": 5,
                    },
                    "operation": "sync",
                }
            )
        obj = captured["obj"]
        assert obj.purchase_unit == "供应商A"
        assert obj.product_name == "考勤组B"
        assert obj.status == "done"
        assert obj.quantity_tins == 5
        mock_db.commit.assert_called_once()

    def test_updates_existing_record_in_place(self):
        applier = _ENTITY_APPLIERS["attendance"]
        mock_db = MagicMock()
        existing = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {
                    "payload": {
                        "id": 5,
                        "purchase_unit": "u",
                        "product_name": "p",
                        "status": "shipped",
                        "model_number": "MN1",
                    },
                    "operation": "sync",
                }
            )
        # existing record mutated, no new row added
        assert existing.status == "shipped"
        assert existing.model_number == "MN1"
        mock_db.add.assert_not_called()
        mock_db.commit.assert_called_once()

    def test_skips_when_required_fields_missing(self):
        applier = _ENTITY_APPLIERS["attendance"]
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {}, "operation": "sync"})
        # no purchase_unit/product_name → nothing added, nothing committed
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_delete_missing_record_does_not_commit(self):
        applier = _ENTITY_APPLIERS["attendance"]
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"id": 999}, "operation": "delete"})
        mock_db.delete.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_delete_existing_record(self):
        applier = _ENTITY_APPLIERS["attendance"]
        mock_db = MagicMock()
        existing = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"id": 7}, "operation": "delete"})
        mock_db.delete.assert_called_once_with(existing)
        mock_db.commit.assert_called_once()

    def test_db_error_is_swallowed(self):
        applier = _ENTITY_APPLIERS["attendance"]
        mock_db = MagicMock()
        mock_db.query.side_effect = OSError("db down")
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"purchase_unit": "u", "product_name": "p"}, "operation": "sync"})


class TestApplyApproval:
    def test_skips_when_no_record_id(self):
        applier = _ENTITY_APPLIERS["approval"]
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {}, "operation": "sync"})
        mock_db.query.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_skips_when_obj_not_found(self):
        applier = _ENTITY_APPLIERS["approval"]
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"id": 999}, "operation": "sync"})
        mock_db.commit.assert_not_called()

    def test_delete_operation(self):
        applier = _ENTITY_APPLIERS["approval"]
        mock_db = MagicMock()
        obj = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = obj
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"id": 1}, "operation": "delete"})
        mock_db.delete.assert_called_once_with(obj)
        mock_db.commit.assert_called_once()

    def test_updates_only_present_columns(self):
        applier = _ENTITY_APPLIERS["approval"]
        mock_db = MagicMock()
        obj = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = obj
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {
                    "payload": {"id": 1, "status": "approved", "title": "新标题"},
                    "operation": "sync",
                }
            )
        assert obj.status == "approved"
        assert obj.title == "新标题"
        mock_db.delete.assert_not_called()
        mock_db.commit.assert_called_once()


class TestApplyApprovalFlow:
    def test_skips_when_flow_key_empty(self):
        applier = _ENTITY_APPLIERS["approval_flow"]
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {}, "operation": "sync"})
        mock_db.query.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_updates_existing_flow_fields(self):
        applier = _ENTITY_APPLIERS["approval_flow"]
        mock_db = MagicMock()
        obj = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = obj
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {
                    "payload": {"flow_key": "fk", "is_active": False, "flow_name": "流程"},
                    "operation": "sync",
                }
            )
        assert obj.is_active is False
        assert obj.flow_name == "流程"
        mock_db.commit.assert_called_once()

    def test_skips_when_flow_not_found(self):
        applier = _ENTITY_APPLIERS["approval_flow"]
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"flow_key": "nonexistent"}, "operation": "sync"})
        mock_db.commit.assert_not_called()


class TestApplyPrintJob:
    def test_upserts_print_job_row(self):
        applier = _ENTITY_APPLIERS["print_job"]
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {
                    "payload": {"status": "done", "template": "tpl"},
                    "operation": "sync",
                    "entity_id": "pj1",
                }
            )
        params = mock_db.execute.call_args[0][1]
        assert params["eid"] == "pj1"
        assert params["tpl"] == "tpl"
        assert params["status"] == "done"
        mock_db.commit.assert_called_once()

    def test_falls_back_to_log_when_table_missing(self):
        """If the print_jobs table is absent the applier degrades to logging and
        does NOT commit — it must never raise into the inbox loop."""
        applier = _ENTITY_APPLIERS["print_job"]
        mock_db = MagicMock()
        mock_db.execute.side_effect = OSError("no such table")
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"status": "done"}, "operation": "sync", "entity_id": "e1"})
        mock_db.commit.assert_not_called()


class TestApplyTemplate:
    def test_skips_when_template_id_empty(self):
        applier = _ENTITY_APPLIERS["template"]
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {}, "operation": "sync", "entity_id": ""})
        mock_db.execute.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_delete_issues_delete_statement(self):
        applier = _ENTITY_APPLIERS["template"]
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {"payload": {"template_id": "tpl1"}, "operation": "delete", "entity_id": "tpl1"}
            )
        sql = str(mock_db.execute.call_args[0][0])
        params = mock_db.execute.call_args[0][1]
        assert "DELETE FROM document_templates" in sql
        assert params == {"s": "tpl1"}
        mock_db.commit.assert_called_once()

    def test_upsert_passes_name_and_category(self):
        applier = _ENTITY_APPLIERS["template"]
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {
                    "payload": {"template_id": "tpl1", "name": "模板1", "category": "excel"},
                    "operation": "sync",
                    "entity_id": "tpl1",
                }
            )
        sql = str(mock_db.execute.call_args[0][0])
        params = mock_db.execute.call_args[0][1]
        assert "INSERT INTO document_templates" in sql
        assert params == {"slug": "tpl1", "name": "模板1", "cat": "excel"}
        mock_db.commit.assert_called_once()

    def test_falls_back_to_entity_id_for_template_id(self):
        applier = _ENTITY_APPLIERS["template"]
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {}, "operation": "sync", "entity_id": "from-entity"})
        params = mock_db.execute.call_args[0][1]
        # template_id defaults to entity_id, and name defaults to the slug
        assert params["slug"] == "from-entity"
        assert params["name"] == "from-entity"


class TestApplyModelConfig:
    def test_skips_when_no_user_id(self):
        applier = _ENTITY_APPLIERS["model_config"]
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {}, "operation": "sync"})
        mock_db.query.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_writes_llm_config_as_json(self):
        applier = _ENTITY_APPLIERS["model_config"]
        mock_db = MagicMock()
        user = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = user
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {
                    "payload": {"user_id": 1, "llm_config": {"model": "gpt-4", "temp": 0.7}},
                    "operation": "sync",
                }
            )
        # default_llm_json must be the exact JSON serialization of llm_config
        assert json.loads(user.default_llm_json) == {"model": "gpt-4", "temp": 0.7}
        mock_db.commit.assert_called_once()

    def test_skips_when_user_not_found(self):
        applier = _ENTITY_APPLIERS["model_config"]
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {"payload": {"user_id": 999, "llm_config": {"model": "gpt-4"}}, "operation": "sync"}
            )
        mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Entity appliers — sync_meta backed (real temp SQLite)
# ---------------------------------------------------------------------------


def _fresh_sync_db(db_path):
    from app.db.xcmax_sync import _ensure_schema

    conn = sqlite3.connect(str(db_path))
    _ensure_schema(conn)
    conn.close()


def _read_meta_value(db_path, key):
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT value FROM sync_meta WHERE key=?", (key,)).fetchone()
    conn.close()
    return json.loads(row[0]) if row else None


class TestApplyEcosystem:
    def test_writes_payload_to_namespaced_meta_key(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        applier = _ENTITY_APPLIERS["ecosystem"]
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            _fresh_sync_db(db_path)
            applier(
                {
                    "payload": {"enabled": True, "name": "eco"},
                    "entity_id": "eco1",
                    "operation": "sync",
                }
            )
            value = _read_meta_value(db_path, "ecosystem:eco1")
        assert value == {"enabled": True, "name": "eco"}

    def test_default_entity_id_key(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        applier = _ENTITY_APPLIERS["ecosystem"]
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            _fresh_sync_db(db_path)
            applier({"payload": {"enabled": False}, "operation": "sync"})
            value = _read_meta_value(db_path, "ecosystem:default")
        assert value == {"enabled": False}


class TestApplyWorkflowEmployee:
    def test_upsert_writes_meta_then_delete_removes_it(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        applier = _ENTITY_APPLIERS["workflow_employee"]
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            _fresh_sync_db(db_path)
            applier(
                {
                    "payload": {"employee_id": "emp2", "status": "active"},
                    "entity_id": "emp2",
                    "operation": "sync",
                }
            )
            after_upsert = _read_meta_value(db_path, "workflow_employee:emp2")
            applier(
                {"payload": {"employee_id": "emp2"}, "entity_id": "emp2", "operation": "delete"}
            )
            after_delete = _read_meta_value(db_path, "workflow_employee:emp2")
        assert after_upsert == {"employee_id": "emp2", "status": "active"}
        # delete removes the meta key entirely
        assert after_delete is None

    def test_skips_when_employee_id_empty(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        applier = _ENTITY_APPLIERS["workflow_employee"]
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
        ):
            _fresh_sync_db(db_path)
            applier({"payload": {}, "entity_id": "", "operation": "sync"})
            conn = sqlite3.connect(str(db_path))
            count = conn.execute("SELECT COUNT(*) FROM sync_meta").fetchone()[0]
            conn.close()
        assert count == 0


# ---------------------------------------------------------------------------
# Entity appliers — IM (LWW semantics)
# ---------------------------------------------------------------------------


class TestApplyImMessage:
    def test_inserts_message_and_records_lww_meta(self, tmp_path):
        """A fresh message inserts a real ImMessage and stamps sync_meta with its
        updated_at_ms + id for later last-write-wins comparisons."""
        db_path = tmp_path / "test_sync.db"
        applier = _ENTITY_APPLIERS["im_message"]
        mock_db = MagicMock()
        captured = {}
        mock_db.add.side_effect = lambda o: captured.update(obj=o)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.get.return_value = None
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
            patch("app.db.get_db", _mock_get_db(mock_db)),
        ):
            _fresh_sync_db(db_path)
            applier(
                {
                    "payload": {
                        "id": 77,
                        "conversation_id": 5,
                        "body": "hello",
                        "sender_user_id": 3,
                        "meta": {"updated_at_ms": 1500},
                    },
                    "operation": "insert",
                    "entity_id": "77",
                }
            )
            meta = _read_meta_value(db_path, "im_message:77")
        obj = captured["obj"]
        assert obj.body == "hello"
        assert obj.conversation_id == 5
        assert obj.sender_user_id == 3
        mock_db.commit.assert_called_once()
        assert meta == {"updated_at_ms": 1500, "id": 77}

    def test_delete_with_no_message_id_is_noop(self):
        applier = _ENTITY_APPLIERS["im_message"]
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {}, "operation": "delete"})
        # no id → never touches the DB
        mock_db.query.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_delete_existing_message(self):
        applier = _ENTITY_APPLIERS["im_message"]
        mock_db = MagicMock()
        obj = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = obj
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"id": 9}, "operation": "delete"})
        mock_db.delete.assert_called_once_with(obj)
        mock_db.commit.assert_called_once()

    def test_skips_insert_when_no_conversation_id(self):
        applier = _ENTITY_APPLIERS["im_message"]
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"id": 1, "body": "hello"}, "operation": "insert"})
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_skips_insert_when_body_blank(self):
        applier = _ENTITY_APPLIERS["im_message"]
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {"payload": {"id": 1, "conversation_id": 1, "body": "   "}, "operation": "insert"}
            )
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_skips_insert_when_no_sender(self):
        applier = _ENTITY_APPLIERS["im_message"]
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier(
                {
                    "payload": {"id": 1, "conversation_id": 1, "body": "hi", "sender_user_id": 0},
                    "operation": "insert",
                }
            )
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_lww_skips_older_message_without_db_write(self, tmp_path):
        """An incoming message older than the recorded version must be dropped before
        any DB write (no add, no commit)."""
        db_path = tmp_path / "test_sync.db"
        applier = _ENTITY_APPLIERS["im_message"]
        mock_db = MagicMock()
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
            patch("app.db.get_db", _mock_get_db(mock_db)),
        ):
            from app.services.xcmax_sync_service import _write_sync_meta

            _fresh_sync_db(db_path)
            _write_sync_meta("im_message:1", {"updated_at_ms": 2000, "id": 1})
            applier(
                {
                    "payload": {
                        "id": 1,
                        "conversation_id": 1,
                        "body": "old",
                        "sender_user_id": 1,
                        "meta": {"updated_at_ms": 1000},
                    },
                    "operation": "insert",
                    "entity_id": "1",
                }
            )
        # older message rejected before reaching get_db()
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()


class TestApplyImReadState:
    def test_skips_when_no_conversation_or_user(self):
        applier = _ENTITY_APPLIERS["im_read_state"]
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {}, "entity_id": ""})
        mock_db.execute.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_parses_entity_id_into_conversation_and_user(self):
        applier = _ENTITY_APPLIERS["im_read_state"]
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            # "5:10" → conversation_id=5, user_id=10; reaches the member lookup
            applier({"payload": {}, "entity_id": "5:10"})
        # member lookup executed (proving the colon-form parse), but no member → no commit
        mock_db.execute.assert_called_once()
        mock_db.commit.assert_not_called()

    def test_advances_read_cursor_and_writes_meta(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        applier = _ENTITY_APPLIERS["im_read_state"]
        mock_db = MagicMock()
        member = MagicMock()
        member.last_read_message_id = 10
        mock_db.execute.return_value.scalar_one_or_none.return_value = member
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
            patch("app.db.get_db", _mock_get_db(mock_db)),
        ):
            _fresh_sync_db(db_path)
            applier(
                {
                    "payload": {
                        "conversation_id": 2,
                        "user_id": 3,
                        "last_read_message_id": 40,
                        "meta": {"updated_at_ms": 5000},
                    },
                    "entity_id": "2:3",
                }
            )
            meta = _read_meta_value(db_path, "im_read_state:2:3")
        # cursor advances to max(existing 10, incoming 40)
        assert member.last_read_message_id == 40
        mock_db.commit.assert_called_once()
        assert meta == {"updated_at_ms": 5000, "last_read_message_id": 40}

    def test_lww_skips_older_read_state_without_db_write(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        applier = _ENTITY_APPLIERS["im_read_state"]
        mock_db = MagicMock()
        with (
            patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path),
            patch("app.db.xcmax_sync._db_path", None),
            patch("app.db.get_db", _mock_get_db(mock_db)),
        ):
            from app.services.xcmax_sync_service import _write_sync_meta

            _fresh_sync_db(db_path)
            _write_sync_meta(
                "im_read_state:1:1", {"updated_at_ms": 2000, "last_read_message_id": 50}
            )
            applier(
                {
                    "payload": {
                        "conversation_id": 1,
                        "user_id": 1,
                        "last_read_message_id": 30,
                        "meta": {"updated_at_ms": 1000},
                    },
                    "entity_id": "1:1",
                }
            )
            # stored meta untouched
            meta = _read_meta_value(db_path, "im_read_state:1:1")
        mock_db.execute.assert_not_called()
        mock_db.commit.assert_not_called()
        assert meta == {"updated_at_ms": 2000, "last_read_message_id": 50}
