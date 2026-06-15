"""Tests for app.services.xcmax_sync_service — sync service coverage ramp."""

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


class TestPayloadUpdatedAtMs:
    def test_extracts_ms_from_meta(self):
        payload = {"meta": {"updated_at_ms": 1700000000000}}
        assert _payload_updated_at_ms(payload) == 1700000000000

    def test_returns_zero_when_meta_missing(self):
        assert _payload_updated_at_ms({}) == 0
        assert _payload_updated_at_ms({"meta": None}) == 0

    def test_returns_zero_when_updated_at_ms_missing(self):
        assert _payload_updated_at_ms({"meta": {}}) == 0

    def test_converts_non_int_to_int(self):
        assert _payload_updated_at_ms({"meta": {"updated_at_ms": "12345"}}) == 12345


# ---------------------------------------------------------------------------
# _read_sync_meta / _write_sync_meta — use real temp SQLite
# ---------------------------------------------------------------------------


class TestReadSyncMeta:
    def test_returns_empty_when_key_missing(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), \
             patch("app.db.xcmax_sync._db_path", None):
            from app.services.xcmax_sync_service import _read_sync_meta
            result = _read_sync_meta("nonexistent_key")
        assert result == {}

    def test_reads_written_value(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), \
             patch("app.db.xcmax_sync._db_path", None):
            from app.services.xcmax_sync_service import _read_sync_meta, _write_sync_meta
            _write_sync_meta("test_key", {"foo": "bar"})
            result = _read_sync_meta("test_key")
        assert result == {"foo": "bar"}

    def test_handles_corrupt_json(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), \
             patch("app.db.xcmax_sync._db_path", None):
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
        assert result == {}


class TestWriteSyncMeta:
    def test_write_and_read_roundtrip(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), \
             patch("app.db.xcmax_sync._db_path", None):
            from app.services.xcmax_sync_service import _read_sync_meta, _write_sync_meta
            _write_sync_meta("k1", {"x": 1})
            _write_sync_meta("k1", {"x": 2})  # overwrite
            result = _read_sync_meta("k1")
        assert result == {"x": 2}


# ---------------------------------------------------------------------------
# record_change
# ---------------------------------------------------------------------------


class TestRecordChange:
    def test_returns_positive_id_on_success(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), \
             patch("app.db.xcmax_sync._db_path", None):
            result = record_change("personnel", "123", "insert", {"name": "张三"})
        assert isinstance(result, int)
        assert result > 0

    def test_returns_negative_on_recoverable_error(self):
        with patch("app.db.xcmax_sync.SyncDb") as MockSyncDb:
            MockSyncDb.side_effect = OSError("disk full")
            result = record_change("personnel", "123", "insert", {"name": "张三"})
        assert result == -1

    def test_passes_all_params_to_sync_db(self):
        mock_db = MagicMock()
        mock_db.append_change.return_value = 42
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db):
            record_change(
                "attendance",
                "456",
                "update",
                {"status": "done"},
                actor="admin",
                version=2,
            )
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


# ---------------------------------------------------------------------------
# push_outbox
# ---------------------------------------------------------------------------


class TestPushOutbox:
    def test_empty_pending_returns_zeros(self):
        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = []
        with patch("app.db.xcmax_sync.SyncDb", return_value=mock_db):
            result = push_outbox()
        assert result == {"sent": 0, "failed": 0, "total_pending": 0}

    def test_push_marks_sent_on_success(self):
        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = [
            {"id": 1, "entity_type": "personnel", "entity_id": "1", "operation": "insert", "payload": {"name": "test"}},
        ]
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"ok"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.services.xcmax_sync_service.urllib.request.urlopen", return_value=mock_resp),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = push_outbox(remote_host="127.0.0.1", remote_port=8080)

        assert result["sent"] == 1
        assert result["failed"] == 0
        mock_db.mark_outbox_sent.assert_called_once_with(1)

    def test_push_marks_failed_on_http_5xx_error(self):
        import urllib.error

        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = [
            {"id": 1, "entity_type": "personnel", "entity_id": "1", "operation": "insert", "payload": {}},
        ]
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
        # 5xx should retry
        mock_db.mark_outbox_failed.assert_called_once_with(1, "HTTP 500: Internal", retry=True)

    def test_push_marks_failed_on_4xx_no_retry(self):
        import urllib.error

        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = [
            {"id": 1, "entity_type": "personnel", "entity_id": "1", "operation": "insert", "payload": {}},
        ]
        with (
            patch(
                "app.services.xcmax_sync_service.urllib.request.urlopen",
                side_effect=urllib.error.HTTPError("url", 404, "Not Found", {}, None),
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = push_outbox()

        assert result["failed"] == 1
        # 4xx should NOT retry
        mock_db.mark_outbox_failed.assert_called_once_with(1, "HTTP 404: Not Found", retry=False)

    def test_push_marks_failed_on_recoverable_error(self):
        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = [
            {"id": 1, "entity_type": "personnel", "entity_id": "1", "operation": "insert", "payload": {}},
        ]
        with (
            patch(
                "app.services.xcmax_sync_service.urllib.request.urlopen",
                side_effect=ConnectionError("refused"),
            ),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = push_outbox()

        assert result["failed"] == 1
        mock_db.mark_outbox_failed.assert_called_once()

    def test_push_multiple_items(self):
        mock_db = MagicMock()
        mock_db.get_pending_outbox.return_value = [
            {"id": 1, "entity_type": "personnel", "entity_id": "1", "operation": "insert", "payload": {}},
            {"id": 2, "entity_type": "department", "entity_id": "2", "operation": "update", "payload": {}},
        ]
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"ok"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.services.xcmax_sync_service.urllib.request.urlopen", return_value=mock_resp),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = push_outbox()

        assert result["sent"] == 2
        assert result["total_pending"] == 2


# ---------------------------------------------------------------------------
# pull_from_remote
# ---------------------------------------------------------------------------


class TestPullFromRemote:
    def test_pull_writes_changes_to_inbox(self):
        mock_db = MagicMock()
        mock_db.get_status.return_value = {"remote_cursor": 0}

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"data": [{"id": 10, "entity_type": "personnel", "entity_id": "1", "operation": "insert", "payload": {"name": "test"}}]}
        ).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.services.xcmax_sync_service.urllib.request.urlopen", return_value=mock_resp),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = pull_from_remote(remote_host="127.0.0.1", remote_port=8080)

        assert result["pulled"] == 1
        mock_db.enqueue_inbox.assert_called_once()
        mock_db.update_remote_cursor.assert_called_once()

    def test_pull_returns_zero_on_empty_data(self):
        mock_db = MagicMock()
        mock_db.get_status.return_value = {"remote_cursor": 0}

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": []}).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.services.xcmax_sync_service.urllib.request.urlopen", return_value=mock_resp),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = pull_from_remote()

        assert result["pulled"] == 0

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

        assert result["pulled"] == 0
        assert "error" in result

    def test_pull_uses_since_cursor(self):
        mock_db = MagicMock()
        mock_db.get_status.return_value = {"remote_cursor": 0}

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": []}).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.services.xcmax_sync_service.urllib.request.urlopen", return_value=mock_resp),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = pull_from_remote(since_cursor=42)

        assert result["since_cursor"] == 42

    def test_pull_uses_remote_cursor_from_status(self):
        mock_db = MagicMock()
        mock_db.get_status.return_value = {"remote_cursor": 100}

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": []}).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.services.xcmax_sync_service.urllib.request.urlopen", return_value=mock_resp),
            patch("app.db.xcmax_sync.SyncDb", return_value=mock_db),
        ):
            result = pull_from_remote()

        assert result["since_cursor"] == 100


# ---------------------------------------------------------------------------
# register_entity_applier
# ---------------------------------------------------------------------------


class TestRegisterEntityApplier:
    def test_registers_function(self):
        @register_entity_applier("test_entity_type_xyz")
        def my_applier(item):
            return "applied"

        assert "test_entity_type_xyz" in _ENTITY_APPLIERS
        assert _ENTITY_APPLIERS["test_entity_type_xyz"] is my_applier

    def test_registered_applier_is_callable(self):
        @register_entity_applier("test_entity_type_abc")
        def my_applier2(item):
            return item

        result = _ENTITY_APPLIERS["test_entity_type_abc"]({"key": "val"})
        assert result == {"key": "val"}


# ---------------------------------------------------------------------------
# apply_inbox
# ---------------------------------------------------------------------------


class TestApplyInbox:
    def test_applies_pending_items(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), \
             patch("app.db.xcmax_sync._db_path", None):
            # Create schema and insert a pending inbox item
            from app.db.xcmax_sync import _ensure_schema
            conn = sqlite3.connect(str(db_path))
            _ensure_schema(conn)
            conn.execute(
                "INSERT INTO sync_inbox (remote_cursor, entity_type, entity_id, operation, payload_json, origin_node, received_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (1, "personnel", "99", "insert", json.dumps({"name": "test"}), "remote", datetime.now().isoformat()),
            )
            conn.commit()
            conn.close()

            # Patch the applier to avoid real DB access
            mock_applier = MagicMock()
            with (
                patch.dict(_ENTITY_APPLIERS, {"personnel": mock_applier}, clear=False),
            ):
                result = apply_inbox()

        assert result["applied"] == 1
        assert result["errors"] == 0

    def test_skips_unknown_entity_type(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), \
             patch("app.db.xcmax_sync._db_path", None):
            from app.db.xcmax_sync import _ensure_schema
            conn = sqlite3.connect(str(db_path))
            _ensure_schema(conn)
            conn.execute(
                "INSERT INTO sync_inbox (remote_cursor, entity_type, entity_id, operation, payload_json, origin_node, received_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (1, "unknown_type_xyz", "99", "sync", "{}", "remote", datetime.now().isoformat()),
            )
            conn.commit()
            conn.close()

            result = apply_inbox()

        assert result["applied"] == 1

    def test_returns_error_on_db_failure(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        # SyncDb() needs to succeed, but the subsequent _resolve_db_path call inside
        # the try block should fail
        from app.db.xcmax_sync import _ensure_schema
        conn = sqlite3.connect(str(db_path))
        _ensure_schema(conn)
        conn.close()

        call_count = 0
        def resolve_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return db_path  # For SyncDb() init
            raise OSError("db error")  # For the try block

        with patch("app.db.xcmax_sync._resolve_db_path", side_effect=resolve_side_effect), \
             patch("app.db.xcmax_sync._db_path", None):
            result = apply_inbox()

        assert result["applied"] == 0
        assert result["errors"] == 1


# ---------------------------------------------------------------------------
# Entity appliers — lightweight unit tests (mock DB access)
# ---------------------------------------------------------------------------


class TestApplyPersonnel:
    def test_skips_when_name_empty(self):
        applier = _ENTITY_APPLIERS.get("personnel")
        assert applier is not None
        applier({"payload": {"name": ""}, "operation": "insert"})

    def test_skips_when_name_missing(self):
        applier = _ENTITY_APPLIERS.get("personnel")
        applier({"payload": {}, "operation": "insert"})

    def test_handles_db_error_gracefully(self):
        applier = _ENTITY_APPLIERS.get("personnel")
        with patch("app.mod_sdk.private_sqlite.resolve_mod_private_sqlite_path", side_effect=OSError("no db")):
            applier({"payload": {"name": "张三"}, "operation": "insert"})


class TestApplyDepartment:
    def test_skips_when_dept_empty(self):
        applier = _ENTITY_APPLIERS.get("department")
        assert applier is not None
        applier({"payload": {"department": ""}, "operation": "insert"})

    def test_handles_db_error_gracefully(self):
        applier = _ENTITY_APPLIERS.get("department")
        with patch("app.mod_sdk.private_sqlite.resolve_mod_private_sqlite_path", side_effect=OSError("no db")):
            applier({"payload": {"department": "研发部"}, "operation": "insert"})


class TestApplyAttendance:
    def test_skips_when_required_fields_missing(self):
        applier = _ENTITY_APPLIERS.get("attendance")
        assert applier is not None
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {}, "operation": "sync"})

    def test_delete_operation(self):
        applier = _ENTITY_APPLIERS.get("attendance")
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"id": 999}, "operation": "delete"})

    def test_handles_db_error_gracefully(self):
        applier = _ENTITY_APPLIERS.get("attendance")
        mock_db = MagicMock()
        mock_db.query.side_effect = OSError("db down")
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"purchase_unit": "u", "product_name": "p"}, "operation": "sync"})


class TestApplyApproval:
    def test_skips_when_no_record_id(self):
        applier = _ENTITY_APPLIERS.get("approval")
        assert applier is not None
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {}, "operation": "sync"})

    def test_skips_when_obj_not_found(self):
        applier = _ENTITY_APPLIERS.get("approval")
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"id": 999}, "operation": "sync"})

    def test_delete_operation(self):
        applier = _ENTITY_APPLIERS.get("approval")
        mock_db = MagicMock()
        mock_obj = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_obj
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"id": 1}, "operation": "delete"})
            mock_db.delete.assert_called_once_with(mock_obj)

    def test_updates_existing_approval(self):
        applier = _ENTITY_APPLIERS.get("approval")
        mock_db = MagicMock()
        mock_obj = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_obj
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"id": 1, "status": "approved", "title": "新标题"}, "operation": "sync"})
            assert mock_obj.status == "approved"
            assert mock_obj.title == "新标题"


class TestApplyApprovalFlow:
    def test_skips_when_flow_key_empty(self):
        applier = _ENTITY_APPLIERS.get("approval_flow")
        assert applier is not None
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {}, "operation": "sync"})

    def test_updates_existing_flow(self):
        applier = _ENTITY_APPLIERS.get("approval_flow")
        mock_db = MagicMock()
        mock_obj = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_obj
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"flow_key": "test_flow", "is_active": True}, "operation": "sync"})
            assert mock_obj.is_active is True

    def test_skips_when_flow_not_found(self):
        applier = _ENTITY_APPLIERS.get("approval_flow")
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"flow_key": "nonexistent"}, "operation": "sync"})
            mock_db.commit.assert_not_called()


class TestApplyPrintJob:
    def test_handles_db_error_gracefully(self):
        applier = _ENTITY_APPLIERS.get("print_job")
        assert applier is not None
        mock_db = MagicMock()
        mock_db.execute.side_effect = OSError("table not found")
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"status": "done"}, "operation": "sync", "entity_id": "e1"})


class TestApplyTemplate:
    def test_skips_when_template_id_empty(self):
        applier = _ENTITY_APPLIERS.get("template")
        assert applier is not None
        applier({"payload": {}, "operation": "sync", "entity_id": ""})

    def test_delete_operation(self):
        applier = _ENTITY_APPLIERS.get("template")
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"template_id": "tpl1"}, "operation": "delete", "entity_id": "tpl1"})
            mock_db.execute.assert_called()

    def test_upsert_operation(self):
        applier = _ENTITY_APPLIERS.get("template")
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"template_id": "tpl1", "name": "模板1", "category": "word"}, "operation": "sync", "entity_id": "tpl1"})
            mock_db.execute.assert_called()


class TestApplyModelConfig:
    def test_skips_when_no_user_id(self):
        applier = _ENTITY_APPLIERS.get("model_config")
        assert applier is not None
        mock_db = MagicMock()
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {}, "operation": "sync"})

    def test_updates_user_llm_config(self):
        applier = _ENTITY_APPLIERS.get("model_config")
        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"user_id": 1, "llm_config": {"model": "gpt-4"}}, "operation": "sync"})
            assert mock_user.default_llm_json is not None

    def test_skips_when_user_not_found(self):
        applier = _ENTITY_APPLIERS.get("model_config")
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            applier({"payload": {"user_id": 999, "llm_config": {"model": "gpt-4"}}, "operation": "sync"})
            mock_db.commit.assert_not_called()


class TestApplyEcosystem:
    def test_writes_to_sync_meta(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        applier = _ENTITY_APPLIERS.get("ecosystem")
        assert applier is not None
        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), \
             patch("app.db.xcmax_sync._db_path", None):
            from app.db.xcmax_sync import _ensure_schema
            conn = sqlite3.connect(str(db_path))
            _ensure_schema(conn)
            conn.close()
            applier({"payload": {"enabled": True}, "entity_id": "eco1", "operation": "sync"})


class TestApplyWorkflowEmployee:
    def test_delete_operation(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        applier = _ENTITY_APPLIERS.get("workflow_employee")
        assert applier is not None
        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), \
             patch("app.db.xcmax_sync._db_path", None):
            from app.db.xcmax_sync import _ensure_schema
            conn = sqlite3.connect(str(db_path))
            _ensure_schema(conn)
            conn.close()
            applier({"payload": {"employee_id": "emp1"}, "entity_id": "emp1", "operation": "delete"})

    def test_upsert_operation(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        applier = _ENTITY_APPLIERS.get("workflow_employee")
        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), \
             patch("app.db.xcmax_sync._db_path", None):
            from app.db.xcmax_sync import _ensure_schema
            conn = sqlite3.connect(str(db_path))
            _ensure_schema(conn)
            conn.close()
            applier({"payload": {"employee_id": "emp2", "status": "active"}, "entity_id": "emp2", "operation": "sync"})

    def test_skips_when_employee_id_empty(self):
        applier = _ENTITY_APPLIERS.get("workflow_employee")
        applier({"payload": {}, "entity_id": "", "operation": "sync"})


class TestApplyImMessage:
    def test_skips_delete_when_no_message_id(self):
        applier = _ENTITY_APPLIERS.get("im_message")
        assert applier is not None
        applier({"payload": {}, "operation": "delete"})

    def test_skips_insert_when_no_conversation_id(self):
        applier = _ENTITY_APPLIERS.get("im_message")
        applier({"payload": {"id": 1, "body": "hello"}, "operation": "insert"})

    def test_skips_insert_when_no_body(self):
        applier = _ENTITY_APPLIERS.get("im_message")
        applier({"payload": {"id": 1, "conversation_id": 1, "body": ""}, "operation": "insert"})

    def test_skips_insert_when_no_sender(self):
        applier = _ENTITY_APPLIERS.get("im_message")
        applier({"payload": {"id": 1, "conversation_id": 1, "body": "hello", "sender_user_id": 0}, "operation": "insert"})

    def test_lww_skips_older_message(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        applier = _ENTITY_APPLIERS.get("im_message")
        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), \
             patch("app.db.xcmax_sync._db_path", None):
            from app.services.xcmax_sync_service import _read_sync_meta, _write_sync_meta
            # Write a newer timestamp first
            _write_sync_meta("im_message:1", {"updated_at_ms": 2000, "id": 1})
            # Try to apply an older message - should skip
            applier({
                "payload": {"id": 1, "conversation_id": 1, "body": "old", "sender_user_id": 1,
                            "meta": {"updated_at_ms": 1000}},
                "operation": "insert",
                "entity_id": "1",
            })


class TestApplyImReadState:
    def test_skips_when_no_conversation_or_user(self):
        applier = _ENTITY_APPLIERS.get("im_read_state")
        assert applier is not None
        applier({"payload": {}, "entity_id": ""})

    def test_parses_entity_id_format(self):
        applier = _ENTITY_APPLIERS.get("im_read_state")
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        with patch("app.db.get_db", _mock_get_db(mock_db)):
            # entity_id "5:10" format → conversation_id=5, user_id=10
            applier({"payload": {}, "entity_id": "5:10"})

    def test_lww_skips_older_read_state(self, tmp_path):
        db_path = tmp_path / "test_sync.db"
        applier = _ENTITY_APPLIERS.get("im_read_state")
        with patch("app.db.xcmax_sync._resolve_db_path", return_value=db_path), \
             patch("app.db.xcmax_sync._db_path", None):
            from app.services.xcmax_sync_service import _write_sync_meta
            # Write a newer timestamp
            _write_sync_meta("im_read_state:1:1", {"updated_at_ms": 2000, "last_read_message_id": 50})
            # Try to apply an older read state
            applier({
                "payload": {"conversation_id": 1, "user_id": 1, "last_read_message_id": 30,
                            "meta": {"updated_at_ms": 1000}},
                "entity_id": "1:1",
            })
