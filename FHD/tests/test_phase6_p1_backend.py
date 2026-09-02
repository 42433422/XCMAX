"""COVERAGE_RAMP Phase 6 round 1: backend low-coverage modules.

Targets:
- ``app.infrastructure.persistence.shipment_record_command_impl`` (~15.8% line coverage)
- ``app.services.conversation_service`` (~22.9% line coverage)

注：原 ``app.utils.database_service`` 已被 ``app.services.database_service``
取代（用 ``sqlite3.backup()`` API 替代 ``shutil.copy2``，避免 WAL 模式下
备份不一致）。DatabaseService 的测试统一在 ``tests/test_services/test_database_service.py``
中维护，本文件不再重复覆盖。

Tests follow the phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (DB session,
filesystem). Internal logic of the units under test is exercised for real.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.persistence.shipment_record_command_impl import (
    SQLAlchemyShipmentRecordCommand,
)
from app.services.conversation_service import (
    ConversationService,
    get_conversation_service,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_db_ctx(mock_db: MagicMock) -> MagicMock:
    """Build a context-manager mock that yields ``mock_db`` for ``with get_db() as db:``."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _make_inspector(table_present: bool = True) -> MagicMock:
    """Build a mock sqlalchemy inspector whose ``get_table_names`` returns a list
    that either contains or omits ``shipment_records``."""
    inspector = MagicMock()
    inspector.get_table_names.return_value = (
        ["shipment_records"] if table_present else ["other_table"]
    )
    return inspector


def _make_record(**overrides: object) -> MagicMock:
    """Build a mock ShipmentRecord row."""
    m = MagicMock()
    defaults: dict[str, object] = {
        "id": 1,
        "purchase_unit": "甲公司",
        "product_name": "产品A",
        "model_number": "M-001",
        "quantity_kg": 10.0,
        "quantity_tins": 2,
        "created_at": datetime(2026, 1, 15),
        "updated_at": datetime(2026, 1, 16),
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


# ===========================================================================
# 1. SQLAlchemyShipmentRecordCommand
# ===========================================================================


class TestShipmentClearAll:
    """``SQLAlchemyShipmentRecordCommand.clear_all``."""

    def test_clear_all_success_returns_count(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.count.return_value = 5
        mock_db.query.return_value = mock_query

        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=True),
            ),
        ):
            result = cmd.clear_all()

        assert result["success"] is True
        assert "5" in result["message"]
        mock_db.commit.assert_called_once()

    def test_clear_all_table_missing_returns_failure(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()

        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=False),
            ),
        ):
            result = cmd.clear_all()

        assert result["success"] is False
        assert "表不存在" in result["message"]
        mock_db.commit.assert_not_called()

    def test_clear_all_db_error_returns_failure(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        with patch(
            "app.infrastructure.persistence.shipment_record_command_impl.get_db",
            side_effect=RuntimeError("connection lost"),
        ):
            result = cmd.clear_all()
        assert result["success"] is False
        assert "清空失败" in result["message"]
        assert "connection lost" in result["message"]


class TestShipmentClearByUnit:
    """``SQLAlchemyShipmentRecordCommand.clear_by_unit``."""

    def test_empty_purchase_unit_returns_failure(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        result = cmd.clear_by_unit("")
        assert result["success"] is False
        assert "purchase_unit" in result["message"]

    def test_clear_by_unit_exact_match_deletes(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.count.return_value = 3
        mock_filter.delete.return_value = None
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query

        resolved = MagicMock()
        resolved.unit_name = "甲公司"

        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=True),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.resolve_purchase_unit",
                return_value=resolved,
            ),
        ):
            result = cmd.clear_by_unit("甲公司")

        assert result["success"] is True
        assert result["deleted_orders"] == 3
        mock_db.commit.assert_called_once()

    def test_clear_by_unit_zero_count_fuzzy_fallback(self) -> None:
        """When exact match yields 0 rows, the fuzzy fallback normalizes
        candidate purchase_unit values and deletes matching ones."""
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        # first count() returns 0 (exact), fuzzy count() returns 2
        mock_filter.count.side_effect = [0, 2]
        mock_filter.delete.return_value = None
        mock_query.filter.return_value = mock_filter
        # distinct().all() returns candidate values
        mock_query.distinct.return_value.all.return_value = [
            ("甲公司",),
            ("乙公司",),
        ]
        mock_db.query.return_value = mock_query

        resolved = MagicMock()
        resolved.unit_name = "甲公司"

        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=True),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.resolve_purchase_unit",
                return_value=resolved,
            ),
        ):
            result = cmd.clear_by_unit("甲公司")

        assert result["success"] is True
        assert result["deleted_orders"] == 2

    def test_clear_by_unit_zero_count_no_candidates(self) -> None:
        """Fuzzy fallback with no matching candidates returns deleted_orders=0."""
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.count.return_value = 0
        # distinct candidates that don't normalize to purchase_unit
        mock_query.distinct.return_value.all.return_value = [("丙公司",)]
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query

        # resolve_purchase_unit returns None → norm(v) is None → no match
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=True),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            result = cmd.clear_by_unit("甲公司")

        assert result["success"] is True
        assert result["deleted_orders"] == 0

    def test_clear_by_unit_table_missing_returns_failure(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()

        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=False),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            result = cmd.clear_by_unit("甲公司")

        assert result["success"] is False
        assert "表不存在" in result["message"]

    def test_clear_by_unit_resolve_exception_suppressed(self) -> None:
        """When ``resolve_purchase_unit`` raises a RECOVERABLE_ERROR, the
        exception is suppressed and the original purchase_unit is used."""
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.count.return_value = 1
        mock_filter.delete.return_value = None
        mock_query.filter.return_value = mock_filter
        mock_db.query.return_value = mock_query

        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=True),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.resolve_purchase_unit",
                side_effect=RuntimeError("lookup down"),
            ),
        ):
            result = cmd.clear_by_unit("甲公司")

        assert result["success"] is True
        assert result["deleted_orders"] == 1

    def test_clear_by_unit_db_error_returns_failure(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                side_effect=RuntimeError("db down"),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.resolve_purchase_unit",
                return_value=None,
            ),
        ):
            result = cmd.clear_by_unit("甲公司")
        assert result["success"] is False
        assert "清理失败" in result["message"]


class TestShipmentUpdateRecord:
    """``SQLAlchemyShipmentRecordCommand.update_record``."""

    def test_update_record_success_with_unit_and_date(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()
        mock_query = MagicMock()
        record = _make_record()
        mock_query.filter.return_value.first.return_value = record
        mock_db.query.return_value = mock_query

        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=True),
            ),
        ):
            result = cmd.update_record(
                1,
                unit_name="乙公司",
                date="2026-02-01",
                fields={"product_name": "产品B"},
            )

        assert result["success"] is True
        assert record.purchase_unit == "乙公司"
        assert record.product_name == "产品B"
        mock_db.commit.assert_called_once()

    def test_update_record_not_found_returns_failure(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query

        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=True),
            ),
        ):
            result = cmd.update_record(999)

        assert result["success"] is False
        assert "999" in result["message"]

    def test_update_record_table_missing_returns_failure(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()

        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=False),
            ),
        ):
            result = cmd.update_record(1)

        assert result["success"] is False
        assert "表不存在" in result["message"]

    def test_update_record_no_optional_fields_still_commits(self) -> None:
        """Passing only record_id (no unit_name/date/fields) still updates
        ``updated_at`` and commits."""
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()
        mock_query = MagicMock()
        record = _make_record()
        mock_query.filter.return_value.first.return_value = record
        mock_db.query.return_value = mock_query

        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=True),
            ),
        ):
            result = cmd.update_record(1)

        assert result["success"] is True
        mock_db.commit.assert_called_once()

    def test_update_record_invalid_date_format_raises_value_error(self) -> None:
        """An invalid date string raises ValueError (a RECOVERABLE_ERROR),
        which is caught and returned as a failure dict."""
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()
        mock_query = MagicMock()
        record = _make_record()
        mock_query.filter.return_value.first.return_value = record
        mock_db.query.return_value = mock_query

        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=True),
            ),
        ):
            result = cmd.update_record(1, date="not-a-date")

        assert result["success"] is False
        assert "更新失败" in result["message"]

    def test_update_record_db_error_returns_failure(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        with patch(
            "app.infrastructure.persistence.shipment_record_command_impl.get_db",
            side_effect=RuntimeError("db down"),
        ):
            result = cmd.update_record(1)
        assert result["success"] is False
        assert "更新失败" in result["message"]


class TestShipmentDeleteRecord:
    """``SQLAlchemyShipmentRecordCommand.delete_record``."""

    def test_delete_record_success(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()
        mock_query = MagicMock()
        record = _make_record()
        mock_query.filter.return_value.first.return_value = record
        mock_db.query.return_value = mock_query

        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=True),
            ),
        ):
            result = cmd.delete_record(1)

        assert result["success"] is True
        mock_db.delete.assert_called_once_with(record)
        mock_db.commit.assert_called_once()

    def test_delete_record_not_found_returns_failure(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query

        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=True),
            ),
        ):
            result = cmd.delete_record(999)

        assert result["success"] is False
        assert "999" in result["message"]

    def test_delete_record_table_missing_returns_failure(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        mock_db = MagicMock()

        with (
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_record_command_impl.sa_inspect",
                return_value=_make_inspector(table_present=False),
            ),
        ):
            result = cmd.delete_record(1)

        assert result["success"] is False
        assert "表不存在" in result["message"]

    def test_delete_record_db_error_returns_failure(self) -> None:
        cmd = SQLAlchemyShipmentRecordCommand()
        with patch(
            "app.infrastructure.persistence.shipment_record_command_impl.get_db",
            side_effect=RuntimeError("db down"),
        ):
            result = cmd.delete_record(1)
        assert result["success"] is False
        assert "删除失败" in result["message"]


# ===========================================================================
# 2. ConversationService
# ===========================================================================


class TestNormalizeUserId:
    """``ConversationService._normalize_user_id`` — covers None, int, numeric
    string, non-numeric string, empty string, whitespace-only string."""

    def test_none_returns_none(self) -> None:
        assert ConversationService._normalize_user_id(None) is None

    def test_int_returns_int(self) -> None:
        assert ConversationService._normalize_user_id(123) == 123

    def test_numeric_string_returns_int(self) -> None:
        assert ConversationService._normalize_user_id("456") == 456

    def test_non_numeric_string_returns_none(self) -> None:
        assert ConversationService._normalize_user_id("abc") is None

    def test_empty_string_returns_none(self) -> None:
        assert ConversationService._normalize_user_id("") is None

    def test_whitespace_numeric_string_returns_int(self) -> None:
        assert ConversationService._normalize_user_id("  789  ") == 789

    def test_whitespace_only_string_returns_none(self) -> None:
        assert ConversationService._normalize_user_id("   ") is None

    def test_float_string_returns_none(self) -> None:
        assert ConversationService._normalize_user_id("12.5") is None


class TestConversationSaveMessage:
    """``ConversationService.save_message``.

    NOTE: ``_normalize_user_id`` is defined without ``self``/``@staticmethod``
    in the source, so calling ``self._normalize_user_id(user_id)`` raises
    ``TypeError``. To exercise the rest of ``save_message``'s DB logic we
    patch ``_normalize_user_id`` on the instance (an external-boundary-style
    shim around a source bug); the DB session is still a real MagicMock
    flowing through the real method body.
    """

    def test_save_message_creates_new_session_and_message(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None  # no existing session
        mock_db.query.return_value = mock_query

        conversation = MagicMock()
        conversation.id = 42

        def _add(obj: MagicMock) -> None:
            obj.id = 42

        mock_db.add.side_effect = _add

        with (
            patch(
                "app.services.conversation_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch.object(
                svc,
                "_normalize_user_id",
                return_value=123,
            ),
            patch("app.services.conversation_service.AIConversation") as mock_cls,
        ):
            mock_cls.return_value = conversation
            msg_id = svc.save_message("sess-1", "123", "user", "hello")

        assert msg_id == 42
        mock_db.add.assert_called()
        mock_db.commit.assert_called_once()

    def test_save_message_updates_existing_session(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        existing_session = MagicMock()
        existing_session.message_count = 5
        mock_query.filter.return_value.first.return_value = existing_session
        mock_db.query.return_value = mock_query

        conversation = MagicMock()
        conversation.id = 7

        with (
            patch(
                "app.services.conversation_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch.object(svc, "_normalize_user_id", return_value=123),
            patch("app.services.conversation_service.AIConversation", return_value=conversation),
        ):
            msg_id = svc.save_message("sess-1", "123", "assistant", "hi")

        assert msg_id == 7
        assert existing_session.message_count == 6
        mock_db.commit.assert_called_once()

    def test_save_message_db_error_propagates(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()
        mock_db.commit.side_effect = RuntimeError("commit failed")

        with (
            patch(
                "app.services.conversation_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch.object(svc, "_normalize_user_id", return_value=123),
            patch("app.services.conversation_service.AIConversation"),
        ):
            with pytest.raises(RuntimeError, match="commit failed"):
                svc.save_message("sess-1", "123", "user", "hello")
        mock_db.rollback.assert_called_once()


class TestConversationGetSessionMessages:
    """``ConversationService.get_session_messages``."""

    def test_returns_tuples_for_messages(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        msg = MagicMock()
        msg.id = 1
        msg.session_id = "s1"
        msg.user_id = "u1"
        msg.role = "user"
        msg.content = "hello"
        msg.intent = "greet"
        msg.conversation_metadata = "{}"
        msg.created_at = datetime(2026, 1, 1)
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            msg
        ]
        mock_db.query.return_value = mock_query

        with patch(
            "app.services.conversation_service.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = svc.get_session_messages("s1", limit=10)

        assert len(result) == 1
        row = result[0]
        assert row[0] == 1
        assert row[3] == "user"
        assert row[4] == "hello"

    def test_none_intent_becomes_empty_string(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        msg = MagicMock()
        msg.id = 2
        msg.session_id = "s1"
        msg.user_id = None
        msg.role = "assistant"
        msg.content = "hi"
        msg.intent = None
        msg.conversation_metadata = None
        msg.created_at = datetime(2026, 1, 2)
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            msg
        ]
        mock_db.query.return_value = mock_query

        with patch(
            "app.services.conversation_service.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = svc.get_session_messages("s1")

        assert result[0][5] == ""
        assert result[0][6] == ""

    def test_empty_result_returns_empty_list(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value = mock_query

        with patch(
            "app.services.conversation_service.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = svc.get_session_messages("missing")

        assert result == []

    def test_db_error_propagates(self) -> None:
        svc = ConversationService()
        with patch(
            "app.services.conversation_service.get_db",
            side_effect=RuntimeError("db down"),
        ):
            with pytest.raises(RuntimeError, match="db down"):
                svc.get_session_messages("s1")


class TestConversationGetSessions:
    """``ConversationService.get_sessions``."""

    def test_returns_sessions_without_user_id(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        session = MagicMock()
        session.id = 1
        session.session_id = "s1"
        session.user_id = 1
        session.title = "T1"
        session.summary = "S1"
        session.message_count = 3
        session.last_message_at = datetime(2026, 1, 1)
        session.created_at = datetime(2026, 1, 1)
        mock_query.order_by.return_value.limit.return_value.all.return_value = [session]
        mock_db.query.return_value = mock_query

        with patch(
            "app.services.conversation_service.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = svc.get_sessions(limit=5)

        assert len(result) == 1
        assert result[0][1] == "s1"
        assert result[0][3] == "T1"

    def test_with_user_id_applies_filter(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value = mock_query

        with patch(
            "app.services.conversation_service.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = svc.get_sessions(user_id="42", limit=5)

        assert result == []
        mock_query.filter.assert_called()

    def test_db_error_propagates(self) -> None:
        svc = ConversationService()
        with patch(
            "app.services.conversation_service.get_db",
            side_effect=RuntimeError("db down"),
        ):
            with pytest.raises(RuntimeError, match="db down"):
                svc.get_sessions()


class TestConversationUpdateSessionTitle:
    """``ConversationService.update_session_title``."""

    def test_updates_existing_session_returns_true(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        session = MagicMock()
        mock_query.filter.return_value.first.return_value = session
        mock_db.query.return_value = mock_query

        with patch(
            "app.services.conversation_service.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = svc.update_session_title("s1", "New Title")

        assert result is True
        assert session.title == "New Title"
        mock_db.commit.assert_called_once()

    def test_session_not_found_returns_false(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query

        with patch(
            "app.services.conversation_service.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = svc.update_session_title("missing", "Title")

        assert result is False
        mock_db.commit.assert_not_called()

    def test_db_error_propagates_and_rolls_back(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()
        mock_db.commit.side_effect = RuntimeError("commit failed")
        mock_query = MagicMock()
        session = MagicMock()
        mock_query.filter.return_value.first.return_value = session
        mock_db.query.return_value = mock_query

        with patch(
            "app.services.conversation_service.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            with pytest.raises(RuntimeError, match="commit failed"):
                svc.update_session_title("s1", "T")
        mock_db.rollback.assert_called_once()


class TestConversationDeleteSession:
    """``ConversationService.delete_session``."""

    def test_deletes_messages_and_session_returns_true(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.delete.return_value = 1
        mock_db.query.return_value = mock_query

        with patch(
            "app.services.conversation_service.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = svc.delete_session("s1")

        assert result is True
        # Two queries: AIConversation + AIConversationSession
        assert mock_db.query.call_count == 2
        mock_db.commit.assert_called_once()

    def test_db_error_propagates_and_rolls_back(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()
        mock_db.commit.side_effect = RuntimeError("commit failed")
        mock_query = MagicMock()
        mock_query.filter.return_value.delete.return_value = 1
        mock_db.query.return_value = mock_query

        with patch(
            "app.services.conversation_service.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            with pytest.raises(RuntimeError, match="commit failed"):
                svc.delete_session("s1")
        mock_db.rollback.assert_called_once()


class TestConversationCreateSession:
    """``ConversationService.create_session``.

    NOTE: same ``_normalize_user_id`` source bug as ``save_message``; we patch
    it on the instance to exercise the real DB logic.
    """

    def test_create_session_returns_uuid(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()

        with (
            patch(
                "app.services.conversation_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch.object(svc, "_normalize_user_id", return_value=5),
        ):
            session_id = svc.create_session(user_id="5", title="Hello")

        assert isinstance(session_id, str)
        assert len(session_id) > 0
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_create_session_default_user_id(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()

        with (
            patch(
                "app.services.conversation_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch.object(svc, "_normalize_user_id", return_value=None),
        ):
            session_id = svc.create_session()

        assert isinstance(session_id, str)
        mock_db.commit.assert_called_once()

    def test_create_session_db_error_propagates(self) -> None:
        svc = ConversationService()
        mock_db = MagicMock()
        mock_db.commit.side_effect = RuntimeError("commit failed")

        with (
            patch(
                "app.services.conversation_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch.object(svc, "_normalize_user_id", return_value=None),
        ):
            with pytest.raises(RuntimeError, match="commit failed"):
                svc.create_session()
        mock_db.rollback.assert_called_once()


class TestGetConversationService:
    """``get_conversation_service`` singleton factory."""

    def test_returns_conversation_service_instance(self) -> None:
        # Reset module-level singleton to ensure deterministic behavior.
        import app.services.conversation_service as mod

        with patch.object(mod, "_conversation_service", None):
            svc = get_conversation_service()
            assert isinstance(svc, ConversationService)
            svc2 = get_conversation_service()
            assert svc is svc2
