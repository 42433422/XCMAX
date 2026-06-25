"""Branch coverage for app.application.conversation_app_service.

Covers save_message neuro-notify branch, get_or_create_session, delete_session (0/8 branches).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


def _mock_db_ctx(mock_db):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _make_message(**overrides):
    m = MagicMock()
    defaults = {
        "id": 1,
        "role": "user",
        "content": "hello",
        "intent": "",
        "metadata": "",
        "created_at": datetime(2026, 1, 1),
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_session(**overrides):
    s = MagicMock()
    defaults = {
        "session_id": "sess-1",
        "user_id": "default",
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 2),
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


class TestSaveMessage:
    def _svc(self):
        from app.application.conversation_app_service import ConversationApplicationService

        return ConversationApplicationService()

    def test_save_message_success_with_notify(self):
        mock_db = MagicMock()
        mock_msg = MagicMock()
        mock_msg.id = 1

        with (
            patch(
                "app.application.conversation_app_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch("app.application.conversation_app_service.AIConversation", return_value=mock_msg),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_conversation_message_saved",
                return_value=None,
            ) as mock_notify,
        ):
            result = self._svc().save_message("sess", "u1", "user", "hi")
        assert result == 1
        mock_notify.assert_called_once()

    def test_save_message_notify_failure_swallowed(self):
        mock_db = MagicMock()
        mock_msg = MagicMock()
        mock_msg.id = 1

        with (
            patch(
                "app.application.conversation_app_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch("app.application.conversation_app_service.AIConversation", return_value=mock_msg),
            patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_conversation_message_saved",
                side_effect=RuntimeError("bus down"),
            ),
        ):
            # Should not raise — error is caught by RECOVERABLE_ERRORS
            result = self._svc().save_message("sess", "u1", "user", "hi")
        assert result == 1


class TestGetSessionMessages:
    def _svc(self):
        from app.application.conversation_app_service import ConversationApplicationService

        return ConversationApplicationService()

    def test_returns_messages_reversed(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        # Return in descending order; method reverses to ascending
        msgs = [
            _make_message(id=3, created_at=datetime(2026, 1, 3)),
            _make_message(id=2, created_at=datetime(2026, 1, 2)),
            _make_message(id=1, created_at=datetime(2026, 1, 1)),
        ]
        mock_q.all.return_value = msgs
        with patch(
            "app.application.conversation_app_service.get_db", return_value=_mock_db_ctx(mock_db)
        ):
            result = self._svc().get_session_messages("sess")
        # Reversed → oldest first
        assert result[0][0] == 1
        assert result[-1][0] == 3

    def test_message_with_none_created_at(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.all.return_value = [_make_message(created_at=None)]
        with patch(
            "app.application.conversation_app_service.get_db", return_value=_mock_db_ctx(mock_db)
        ):
            result = self._svc().get_session_messages("sess")
        assert result[0][5] is None  # created_at slot

    def test_empty_messages(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.all.return_value = []
        with patch(
            "app.application.conversation_app_service.get_db", return_value=_mock_db_ctx(mock_db)
        ):
            result = self._svc().get_session_messages("sess")
        assert result == []


class TestCreateSession:
    def _svc(self):
        from app.application.conversation_app_service import ConversationApplicationService

        return ConversationApplicationService()

    def test_create_session_returns_id(self):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.session_id = "new-sess"

        with (
            patch(
                "app.application.conversation_app_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.application.conversation_app_service.AIConversationSession",
                return_value=mock_session,
            ),
        ):
            result = self._svc().create_session("u1")
        assert result == "new-sess"


class TestGetOrCreateSession:
    def _svc(self):
        from app.application.conversation_app_service import ConversationApplicationService

        return ConversationApplicationService()

    def test_returns_existing_session(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.first.return_value = _make_session(session_id="existing")
        with patch(
            "app.application.conversation_app_service.get_db", return_value=_mock_db_ctx(mock_db)
        ):
            result = self._svc().get_or_create_session("u1")
        assert result == "existing"
        mock_db.add.assert_not_called()

    def test_creates_new_when_none_exists(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.first.return_value = None
        mock_session = MagicMock()
        mock_session.session_id = "fresh"

        with (
            patch(
                "app.application.conversation_app_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.application.conversation_app_service.AIConversationSession",
                return_value=mock_session,
            ),
        ):
            result = self._svc().get_or_create_session("u1")
        assert result == "fresh"
        mock_db.add.assert_called_once()


class TestGetSessions:
    def _svc(self):
        from app.application.conversation_app_service import ConversationApplicationService

        return ConversationApplicationService()

    def test_returns_session_list(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.all.return_value = [_make_session()]
        with patch(
            "app.application.conversation_app_service.get_db", return_value=_mock_db_ctx(mock_db)
        ):
            result = self._svc().get_sessions("u1")
        assert len(result) == 1
        assert result[0]["session_id"] == "sess-1"

    def test_session_with_none_dates(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.all.return_value = [_make_session(created_at=None, updated_at=None)]
        with patch(
            "app.application.conversation_app_service.get_db", return_value=_mock_db_ctx(mock_db)
        ):
            result = self._svc().get_sessions("u1")
        assert result[0]["created_at"] is None
        assert result[0]["updated_at"] is None


class TestDeleteSession:
    def _svc(self):
        from app.application.conversation_app_service import ConversationApplicationService

        return ConversationApplicationService()

    def test_delete_existing_session(self):
        mock_db = MagicMock()
        # First query: session lookup → returns existing session
        session_q = MagicMock()
        session_q.filter.return_value = session_q
        session_q.order_by.return_value = session_q
        session_q.first.return_value = _make_session()
        # Second query: message deletion
        msg_q = MagicMock()
        msg_q.filter.return_value = msg_q
        mock_db.query.side_effect = [session_q, msg_q]
        with patch(
            "app.application.conversation_app_service.get_db", return_value=_mock_db_ctx(mock_db)
        ):
            result = self._svc().delete_session("sess-1")
        assert result is True
        msg_q.filter.return_value.delete.assert_called_once()
        mock_db.delete.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_delete_nonexistent_session(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.first.return_value = None
        with patch(
            "app.application.conversation_app_service.get_db", return_value=_mock_db_ctx(mock_db)
        ):
            result = self._svc().delete_session("ghost")
        assert result is False


class TestSingleton:
    def test_get_conversation_app_service_singleton(self):
        import app.application.conversation_app_service as mod

        mod._conversation_app_service = None
        from app.application.conversation_app_service import get_conversation_app_service

        s1 = get_conversation_app_service()
        s2 = get_conversation_app_service()
        assert s1 is s2
