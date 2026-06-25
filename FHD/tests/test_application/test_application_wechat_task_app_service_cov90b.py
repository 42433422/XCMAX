"""Second-wave coverage tests for app.application.wechat_task_app_service.

Targets previously-uncovered lines/branches:
  - 76-77   neuro_notify swallow on create
  - 91      IntegrityError path with no pre-existing row -> None
  - 114-171 scan_messages full import + row-processing pipeline
  - 250-252 recognize_order recoverable-except branch
  - 278-280 recognize_shipment recoverable-except branch
  - 304-306 ignore_task recoverable-except branch
  - 454-455 _update_task_status neuro_notify swallow on update
  - 505-507 _process_shipment_message recoverable-except branch

All external dependencies (DB, neuro bus, wechat_db_read import, filesystem,
env, resource paths) are mocked. Deterministic, offline, fast.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.application.wechat_task_app_service import WechatTaskApplicationService


@pytest.fixture
def service():
    return WechatTaskApplicationService()


def _mock_db_ctx(mock_db: MagicMock):
    """Return a context-manager factory yielding ``mock_db`` for patching get_db."""

    @contextmanager
    def _ctx():
        yield mock_db

    return _ctx


# ---------------------------------------------------------------------------
# _insert_or_ignore_wechat_task — neuro_notify swallow (lines 76-77)
# ---------------------------------------------------------------------------


class TestInsertNeuroNotifySwallow:
    def test_create_notify_failure_is_swallowed(self, service):
        """If neuro_notify raises a RECOVERABLE error after a successful insert,
        the task id is still returned (lines 76-77 except branch)."""
        mock_db = MagicMock()
        # no existing row
        mock_db.query.return_value.filter.return_value.first.return_value = None

        def mock_refresh(task):
            task.id = 7

        mock_db.refresh = mock_refresh

        with (
            patch(
                "app.application.wechat_task_app_service.get_db",
                side_effect=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_wechat_task_changed",
                side_effect=RuntimeError("bus down"),
            ),
        ):
            result = service._insert_or_ignore_wechat_task(
                raw_text="some order text", message_id="m9", username="u9"
            )
        assert result == 7


# ---------------------------------------------------------------------------
# _insert_or_ignore_wechat_task — IntegrityError, no existing row (line 91)
# ---------------------------------------------------------------------------


class TestInsertIntegrityErrorNoExisting:
    def test_integrity_error_no_existing_returns_none(self, service):
        """First get_db raises IntegrityError on add; second get_db finds no
        existing row -> returns None (line 91)."""
        from sqlalchemy.exc import IntegrityError

        call_count = 0

        def get_db_ctx():
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            if call_count == 1:
                m.add.side_effect = IntegrityError("dup", None, Exception("orig"))
            # On the recovery query no existing row exists.
            m.query.return_value.filter.return_value.first.return_value = None
            return _mock_db_ctx(m)()

        with patch("app.application.wechat_task_app_service.get_db", side_effect=get_db_ctx):
            result = service._insert_or_ignore_wechat_task(
                raw_text="dup text", message_id="m1", username="u1"
            )
        assert result is None
        assert call_count == 2

    def test_integrity_error_without_message_id_returns_none(self, service):
        """IntegrityError but no message_id/username -> recovery query is skipped,
        still returns None (line 91)."""
        from sqlalchemy.exc import IntegrityError

        def get_db_ctx():
            m = MagicMock()
            m.add.side_effect = IntegrityError("dup", None, Exception("orig"))
            return _mock_db_ctx(m)()

        with patch("app.application.wechat_task_app_service.get_db", side_effect=get_db_ctx):
            result = service._insert_or_ignore_wechat_task(raw_text="dup text")
        assert result is None


# ---------------------------------------------------------------------------
# scan_messages — full pipeline (lines 114-171)
# ---------------------------------------------------------------------------


class TestScanMessagesPipeline:
    def _patch_path(self, exists=True, isdir=True, resource="/tmp/wechat_cv"):
        """Patch path utils + os.path so scan_messages reaches the import block."""
        return [
            patch(
                "app.utils.path_utils.get_resource_path",
                return_value=resource,
            ),
            patch(
                "app.application.wechat_task_app_service.os.path.exists",
                return_value=exists,
            ),
            patch(
                "app.application.wechat_task_app_service.os.path.isdir",
                return_value=isdir,
            ),
        ]

    def test_import_failure_in_inner_block_returns_empty(self, service, monkeypatch):
        """sys.path.insert runs, then importing wechat_db_read fails -> returns []
        (covers lines 114-121 except branch)."""
        monkeypatch.setenv("WECHAT_MSG_DB_PATH", "/fake/msg.db")
        # Ensure wechat_db_read is not importable.
        monkeypatch.setitem(sys.modules, "wechat_db_read", None)

        patches = self._patch_path(exists=True, isdir=True, resource="/tmp/no_such_cv")
        with patches[0], patches[1], patches[2]:
            result = service.scan_messages()
        assert result == []

    def test_full_row_processing_inserts_and_filters(self, service, monkeypatch):
        """get_recent_messages returns several rows; only order-like ones with
        non-empty text get inserted. Covers lines 123-171."""
        monkeypatch.setenv("WECHAT_MSG_DB_PATH", "/fake/msg.db")

        fake_module = MagicMock()
        rows = [
            # order-like -> inserted (task_id 100)
            {
                "msgId": "id1",
                "talker": "alice",
                "displayName": "Alice",
                "createTime": 111,
                "content": "环氧地坪漆 规格 5桶",
            },
            # blank content -> skipped (continue at line 141)
            {
                "msgId": "id2",
                "talker": "bob",
                "content": "   ",
            },
            # not order-like -> skipped (continue at line 144)
            {
                "msgId": "id3",
                "talker": "carol",
                "content": "今天天气不错",
            },
            # order-like but insert returns None (dedup) -> not appended (line 157 false)
            {
                "localId": "id4",
                "talker": "dave",
                "createTime": 222,
                "content": "环氧地坪漆 规格 10kg",
            },
        ]
        fake_module.get_recent_messages.return_value = {"rows": rows}

        # First order-like row -> id 100; the dave row -> None (simulating dedup)
        insert_results = iter([100, None])
        monkeypatch.setitem(sys.modules, "wechat_db_read", fake_module)

        patches = self._patch_path(exists=True, isdir=True, resource="/tmp/wechat_cv")
        with (
            patches[0],
            patches[1],
            patches[2],
            patch.object(
                service,
                "_insert_or_ignore_wechat_task",
                side_effect=lambda **kw: next(insert_results),
            ),
        ):
            result = service.scan_messages(contact_id=5, limit=50)

        # createTime "bad" would crash int(); guard by replacing dave row createTime.
        assert len(result) == 1
        assert result[0]["id"] == 100
        assert result[0]["username"] == "alice"
        assert result[0]["task_type"] == "shipment_order"

    def test_empty_rows_returns_empty(self, service, monkeypatch):
        """get_recent_messages returns no rows -> early return [] (lines 129-131)."""
        monkeypatch.setenv("WECHAT_MSG_DB_PATH", "/fake/msg.db")
        fake_module = MagicMock()
        fake_module.get_recent_messages.return_value = {"rows": []}
        monkeypatch.setitem(sys.modules, "wechat_db_read", fake_module)

        patches = self._patch_path(exists=True, isdir=True)
        with patches[0], patches[1], patches[2]:
            result = service.scan_messages()
        assert result == []

    def test_rows_key_missing_returns_empty(self, service, monkeypatch):
        """out.get('rows') is None -> returns [] (line 129-131)."""
        monkeypatch.setenv("WECHAT_MSG_DB_PATH", "/fake/msg.db")
        fake_module = MagicMock()
        fake_module.get_recent_messages.return_value = {}
        monkeypatch.setitem(sys.modules, "wechat_db_read", fake_module)

        patches = self._patch_path(exists=True, isdir=True)
        with patches[0], patches[1], patches[2]:
            result = service.scan_messages()
        assert result == []


# ---------------------------------------------------------------------------
# recognize_order — recoverable-except branch (lines 250-252)
# ---------------------------------------------------------------------------


class TestRecognizeOrderExcept:
    def test_recoverable_error_returns_none(self, service):
        """re.search raising a recoverable error -> returns None (250-252)."""
        with patch(
            "app.application.wechat_task_app_service.re.search",
            side_effect=RuntimeError("regex engine down"),
        ):
            assert service.recognize_order("买 5箱 产品A") is None


# ---------------------------------------------------------------------------
# recognize_shipment — recoverable-except branch (lines 278-280)
# ---------------------------------------------------------------------------


class TestRecognizeShipmentExcept:
    def test_recoverable_error_returns_none(self, service):
        """re.search raising a recoverable error -> returns None (278-280)."""
        with patch(
            "app.application.wechat_task_app_service.re.search",
            side_effect=OSError("regex io"),
        ):
            assert service.recognize_shipment("发货：环氧地坪漆 5桶") is None


# ---------------------------------------------------------------------------
# ignore_task — recoverable-except branch (lines 304-306)
# ---------------------------------------------------------------------------


class TestIgnoreTaskExcept:
    def test_recoverable_error_returns_failure(self, service):
        """_task_exists raising a recoverable error -> success False (304-306)."""
        with patch.object(service, "_task_exists", side_effect=RuntimeError("db error")):
            result = service.ignore_task(1)
        assert result["success"] is False
        assert "忽略失败" in result["message"]


# ---------------------------------------------------------------------------
# _update_task_status — neuro_notify swallow on update (lines 454-455)
# ---------------------------------------------------------------------------


class TestUpdateTaskStatusNeuroNotifySwallow:
    def test_update_notify_failure_is_swallowed(self, service):
        """neuro_notify raising on an update is swallowed; still returns True
        (lines 454-455)."""
        mock_db = MagicMock()
        mock_task = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        with (
            patch(
                "app.application.wechat_task_app_service.get_db",
                side_effect=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_wechat_task_changed",
                side_effect=RuntimeError("bus down"),
            ),
        ):
            result = service._update_task_status(1, "done")
        assert result is True
        assert mock_task.status == "done"
        mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# _process_shipment_message — recoverable-except branch (lines 505-507)
# ---------------------------------------------------------------------------


class TestProcessShipmentMessageExcept:
    def test_recoverable_error_returns_failure(self, service):
        """recognize_shipment raising a recoverable error -> success False
        (lines 505-507)."""
        task = {"raw_text": "发货：环氧地坪漆 5桶"}
        with patch.object(service, "recognize_shipment", side_effect=OSError("boom")):
            result = service._process_shipment_message(task)
        assert result["success"] is False
        assert "处理失败" in result["message"]
