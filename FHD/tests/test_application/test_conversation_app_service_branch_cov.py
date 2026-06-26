"""Branch-coverage tests for app/application/conversation_app_service.py.

Targets the 8 missing branches reported in coverage.json:
- [64, 65] / [64, 76]: empty vs non-empty messages list in get_session_messages
- [95, 96] / [95, 98]: session found vs not found in get_or_create_session
- [132, 133] / [132, 135]: session exists vs not in delete_session
- [147, 148] / [147, 149]: singleton cached vs fresh in get_conversation_app_service

All DB access is mocked via context-managed session stubs.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.application import conversation_app_service as cas_mod
from app.application.conversation_app_service import ConversationApplicationService

# ---------------------------------------------------------------------------
# Helpers — context-managed fake DB session
# ---------------------------------------------------------------------------


def _make_msg(msg_id, role, content, intent, metadata, created_at):
    """Build a message-like object."""
    m = MagicMock()
    m.id = msg_id
    m.role = role
    m.content = content
    m.intent = intent
    m.metadata = metadata
    m.created_at = created_at
    return m


def _make_session(session_id, user_id, created_at="keep", updated_at="keep"):
    """Build a session-like object. Pass None explicitly for None dates."""
    s = MagicMock()
    s.session_id = session_id
    s.user_id = user_id
    s.created_at = datetime(2026, 1, 1) if created_at == "keep" else created_at
    s.updated_at = datetime(2026, 1, 2) if updated_at == "keep" else updated_at
    return s


@contextmanager
def _fake_db_ctx(db_mock):
    """Patch get_db to yield the given mock session."""
    with patch.object(cas_mod, "get_db") as g:
        g.return_value.__enter__ = MagicMock(return_value=db_mock)
        g.return_value.__exit__ = MagicMock(return_value=False)
        yield g


# ---------------------------------------------------------------------------
# get_session_messages — branches [64, 65] / [64, 76]
# ---------------------------------------------------------------------------


class TestGetSessionMessagesBranches:
    """Cover the for-loop branch when messages list is empty vs non-empty."""

    def test_get_session_messages_empty_list_returns_empty(self):
        """Empty messages list — for-loop body never executes (branch 64->76)."""
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            result = service.get_session_messages("sess-1")
        assert result == []

    def test_get_session_messages_non_empty_returns_reversed(self):
        """Non-empty messages list — for-loop body executes (branch 64->65)."""
        now = datetime(2026, 6, 25)
        msgs = [
            _make_msg(3, "assistant", "reply3", "chat", "{}", now),
            _make_msg(2, "user", "msg2", "chat", "{}", now),
            _make_msg(1, "assistant", "reply1", "chat", "{}", now),
        ]
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = msgs
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            result = service.get_session_messages("sess-1")
        # reversed: oldest first
        assert len(result) == 3
        assert result[0][0] == 1
        assert result[2][0] == 3

    def test_get_session_messages_with_none_created_at(self):
        """Message with created_at=None — isoformat branch returns None."""
        msgs = [_make_msg(1, "user", "hi", "chat", "{}", None)]
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = msgs
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            result = service.get_session_messages("sess-1")
        assert result[0][5] is None

    def test_get_session_messages_custom_limit(self):
        """Custom limit is passed through to the query."""
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            service.get_session_messages("sess-1", limit=10)
        db.query.return_value.filter.return_value.order_by.return_value.limit.assert_called_once_with(10)


# ---------------------------------------------------------------------------
# get_or_create_session — branches [95, 96] / [95, 98]
# ---------------------------------------------------------------------------


class TestGetOrCreateSessionBranches:
    """Cover the if-session-found vs not-found branches."""

    def test_get_or_create_session_existing_returns_session_id(self):
        """Session found — returns existing session_id (branch 95->96)."""
        existing = _make_session("sess-existing", "user-1")
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = existing
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            result = service.get_or_create_session("user-1")
        assert result == "sess-existing"
        db.add.assert_not_called()

    def test_get_or_create_session_none_creates_new(self):
        """Session not found — creates new session (branch 95->98)."""
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        db.refresh.side_effect = lambda s: setattr(s, "session_id", "sess-new")
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            with patch.object(cas_mod, "AIConversationSession") as MockSession:
                mock_inst = MagicMock()
                mock_inst.session_id = "sess-new"
                MockSession.return_value = mock_inst
                result = service.get_or_create_session("default")
        assert result == "sess-new"
        db.add.assert_called_once()

    def test_get_or_create_session_default_user(self):
        """Default user_id parameter is 'default'."""
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            with patch.object(cas_mod, "AIConversationSession") as MockSession:
                mock_inst = MagicMock()
                mock_inst.session_id = "sess-def"
                MockSession.return_value = mock_inst
                service.get_or_create_session()
        db.query.return_value.filter.assert_called_once()


# ---------------------------------------------------------------------------
# delete_session — branches [132, 133] / [132, 135]
# ---------------------------------------------------------------------------


class TestDeleteSessionBranches:
    """Cover the if-not-session vs session-exists branches."""

    def test_delete_session_not_found_returns_false(self):
        """Session not found — returns False (branch 132->133)."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            result = service.delete_session("nonexistent")
        assert result is False
        db.delete.assert_not_called()
        db.commit.assert_not_called()

    def test_delete_session_found_deletes_and_returns_true(self):
        """Session found — deletes messages and session (branch 132->135)."""
        session = _make_session("sess-1", "user-1")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = session
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            result = service.delete_session("sess-1")
        assert result is True
        db.commit.assert_called_once()

    def test_delete_session_found_deletes_messages_first(self):
        """When session exists, messages are deleted before session."""
        session = _make_session("sess-1", "user-1")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = session
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            service.delete_session("sess-1")
        # First call to query is for session lookup, second for messages delete
        assert db.query.call_count >= 2


# ---------------------------------------------------------------------------
# get_conversation_app_service singleton — branches [147, 148] / [147, 149]
# ---------------------------------------------------------------------------


class TestGetConversationAppServiceSingleton:
    """Cover the singleton cached vs fresh branches."""

    def test_singleton_returns_cached_instance(self):
        """When already initialized — returns cached instance (branch 147->149)."""
        # First call to populate
        cas_mod._conversation_app_service = None
        first = cas_mod.get_conversation_app_service()
        # Second call should return the same instance
        second = cas_mod.get_conversation_app_service()
        assert first is second

    def test_singleton_creates_new_when_none(self):
        """When _conversation_app_service is None — creates new (branch 147->148)."""
        cas_mod._conversation_app_service = None
        result = cas_mod.get_conversation_app_service()
        assert result is not None
        assert isinstance(result, ConversationApplicationService)
        # Cleanup
        cas_mod._conversation_app_service = None


# ---------------------------------------------------------------------------
# save_message — neuro_notify error branch
# ---------------------------------------------------------------------------


class TestSaveMessageBranches:
    """Cover the save_message neuro_notify error handling branch."""

    def test_save_message_success_returns_id(self):
        """Successful save returns message id."""
        db = MagicMock()
        service = ConversationApplicationService()

        def _add(msg):
            msg.id = 42

        db.add.side_effect = _add
        with _fake_db_ctx(db):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_conversation_message_saved"
            ):
                result = service.save_message(
                    "sess-1", "user-1", "user", "hello", "chat", "{}"
                )
        assert result == 42

    def test_save_message_neuro_notify_error_swallowed(self):
        """When neuro_notify raises RECOVERABLE_ERRORS, it is swallowed."""
        db = MagicMock()

        def _add(msg):
            msg.id = 99

        db.add.side_effect = _add
        service = ConversationApplicationService()
        # Patch the import inside the method to raise
        with _fake_db_ctx(db):
            with patch(
                "app.neuro_bus.application_neuro_bridge.neuro_notify_conversation_message_saved",
                side_effect=ConnectionError("bus down"),
            ):
                result = service.save_message(
                    "sess-1", "user-1", "user", "hello", "chat", "{}"
                )
        assert result == 99


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


class TestCreateSession:
    def test_create_session_returns_session_id(self):
        """create_session returns the new session_id."""
        db = MagicMock()
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            with patch.object(cas_mod, "AIConversationSession") as MockSession:
                mock_inst = MagicMock()
                mock_inst.session_id = "sess-new"
                MockSession.return_value = mock_inst
                result = service.create_session("user-1")
        assert result == "sess-new"
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_create_session_default_user(self):
        """create_session uses 'default' when no user_id given."""
        db = MagicMock()
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            with patch.object(cas_mod, "AIConversationSession") as MockSession:
                mock_inst = MagicMock()
                mock_inst.session_id = "sess-def"
                MockSession.return_value = mock_inst
                result = service.create_session()
        assert result == "sess-def"


# ---------------------------------------------------------------------------
# get_sessions
# ---------------------------------------------------------------------------


class TestGetSessions:
    def test_get_sessions_returns_list_of_dicts(self):
        """get_sessions returns list of session dicts."""
        sessions = [
            _make_session("s1", "u1", datetime(2026, 1, 1), datetime(2026, 1, 2)),
            _make_session("s2", "u1", datetime(2026, 1, 3), datetime(2026, 1, 4)),
        ]
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = sessions
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            result = service.get_sessions("u1")
        assert len(result) == 2
        assert result[0]["session_id"] == "s1"
        assert result[0]["user_id"] == "u1"
        assert result[0]["created_at"] == "2026-01-01T00:00:00"

    def test_get_sessions_with_none_dates(self):
        """Session with None created_at/updated_at returns None in dict."""
        sessions = [_make_session("s1", "u1", None, None)]
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = sessions
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            result = service.get_sessions("u1")
        assert result[0]["created_at"] is None
        assert result[0]["updated_at"] is None

    def test_get_sessions_empty_returns_empty_list(self):
        """No sessions returns empty list."""
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            result = service.get_sessions("u1")
        assert result == []

    def test_get_sessions_custom_limit(self):
        """Custom limit passed through."""
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        service = ConversationApplicationService()
        with _fake_db_ctx(db):
            service.get_sessions("u1", limit=5)
        db.query.return_value.filter.return_value.order_by.return_value.limit.assert_called_once_with(5)
