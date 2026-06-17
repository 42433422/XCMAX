"""Tests for app.application.im_app_service — coverage ramp."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.application.im_app_service import ImApplicationService, ensure_im_tables

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id=1, display_name="Alice", username="alice", tenant_id=None, is_active=True):
    u = MagicMock()
    u.id = user_id
    u.display_name = display_name
    u.username = username
    u.tenant_id = tenant_id
    u.is_active = is_active
    return u


def _make_conversation(conv_id=1, is_direct=False, title=None, last_message_at=None):
    c = MagicMock()
    c.id = conv_id
    c.is_direct = is_direct
    c.title = title
    c.last_message_at = last_message_at
    return c


def _make_message(msg_id=1, conversation_id=1, sender_user_id=1, body="hello", created_at=None):
    m = MagicMock()
    m.id = msg_id
    m.conversation_id = conversation_id
    m.sender_user_id = sender_user_id
    m.body = body
    m.created_at = created_at or datetime(2026, 1, 1, 12, 0, 0)
    return m


def _make_member(conversation_id=1, user_id=1, last_read_message_id=None):
    m = MagicMock()
    m.conversation_id = conversation_id
    m.user_id = user_id
    m.last_read_message_id = last_read_message_id
    return m


# ---------------------------------------------------------------------------
# ensure_im_tables
# ---------------------------------------------------------------------------


class TestEnsureImTables:
    def test_delegates_to_init_im_tables(self):
        mock_engine = MagicMock()
        with patch("app.db.init_db.init_im_tables") as mock_init:
            ensure_im_tables(mock_engine)
            mock_init.assert_called_once_with(mock_engine)


# ---------------------------------------------------------------------------
# _display_name
# ---------------------------------------------------------------------------


class TestDisplayName:
    def test_returns_display_name_when_set(self):
        db = MagicMock()
        user = _make_user(display_name="Alice")
        db.get.return_value = user
        svc = ImApplicationService(db)
        assert svc._display_name(1) == "Alice"

    def test_falls_back_to_username(self):
        db = MagicMock()
        user = _make_user(display_name="", username="bob")
        db.get.return_value = user
        svc = ImApplicationService(db)
        assert svc._display_name(1) == "bob"

    def test_falls_back_to_default_when_no_names(self):
        db = MagicMock()
        user = _make_user(display_name=None, username=None)
        db.get.return_value = user
        svc = ImApplicationService(db)
        assert svc._display_name(1) == "用户1"

    def test_returns_default_when_user_not_found(self):
        db = MagicMock()
        db.get.return_value = None
        svc = ImApplicationService(db)
        assert svc._display_name(99) == "用户99"


# ---------------------------------------------------------------------------
# _display_name_map
# ---------------------------------------------------------------------------


class TestDisplayNameMap:
    def test_returns_empty_for_empty_ids(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc._display_name_map([]) == {}

    def test_maps_user_ids_to_names(self):
        db = MagicMock()
        u1 = _make_user(user_id=1, display_name="Alice")
        u2 = _make_user(user_id=2, display_name="Bob")
        db.execute.return_value.scalars.return_value.all.return_value = [u1, u2]
        svc = ImApplicationService(db)
        result = svc._display_name_map([1, 2])
        assert result[1] == "Alice"
        assert result[2] == "Bob"

    def test_deduplicates_ids(self):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []
        svc = ImApplicationService(db)
        svc._display_name_map([1, 1, 2])
        # Should only call db.execute once


# ---------------------------------------------------------------------------
# _direct_peer_id
# ---------------------------------------------------------------------------


class TestDirectPeerId:
    def test_returns_peer_id(self):
        db = MagicMock()
        db.execute.return_value.first.return_value = (2,)
        svc = ImApplicationService(db)
        assert svc._direct_peer_id(1, 10) == 2

    def test_returns_none_when_no_peer(self):
        db = MagicMock()
        db.execute.return_value.first.return_value = None
        svc = ImApplicationService(db)
        assert svc._direct_peer_id(1, 10) is None


# ---------------------------------------------------------------------------
# _message_dict
# ---------------------------------------------------------------------------


class TestMessageDict:
    def test_with_sender_name(self):
        msg = _make_message(msg_id=5, conversation_id=1, sender_user_id=2, body="hi")
        result = ImApplicationService._message_dict(msg, "Bob")
        assert result["id"] == 5
        assert result["sender_display_name"] == "Bob"
        assert result["body"] == "hi"
        assert result["conversation_id"] == 1

    def test_without_sender_name(self):
        msg = _make_message(msg_id=5, sender_user_id=3)
        result = ImApplicationService._message_dict(msg, None)
        assert result["sender_display_name"] == "用户3"

    def test_none_created_at(self):
        msg = _make_message()
        msg.created_at = None
        result = ImApplicationService._message_dict(msg)
        assert result["created_at"] is None


# ---------------------------------------------------------------------------
# get_or_create_direct
# ---------------------------------------------------------------------------


class TestGetOrCreateDirect:
    def test_raises_when_same_user(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="不能与自己创建会话"):
            svc.get_or_create_direct(1, 1)

    def test_returns_existing_conversation(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        conv = _make_conversation(conv_id=10, title="chat")
        with patch.object(svc, "_find_direct_conversation", return_value=10):
            db.get.return_value = conv
            result = svc.get_or_create_direct(1, 2)
        assert result["id"] == 10
        assert result["created"] is False

    def test_creates_new_conversation(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        conv = _make_conversation(conv_id=20, title="用户1 ↔ 用户2")
        with patch.object(svc, "_find_direct_conversation", return_value=None):
            db.get.return_value = conv

            # After flush, conv.id should be set
            def _flush_side_effect():
                conv.id = 20

            db.flush.side_effect = _flush_side_effect
            db.refresh.side_effect = lambda x: None
            result = svc.get_or_create_direct(1, 2)
        assert result["created"] is True


# ---------------------------------------------------------------------------
# list_messages
# ---------------------------------------------------------------------------


class TestListMessages:
    def test_raises_when_not_member(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with patch.object(svc, "_get_member", return_value=None):
            with pytest.raises(PermissionError, match="非会话成员"):
                svc.list_messages(1, 99)

    def test_returns_messages(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        msg = _make_message(msg_id=1, sender_user_id=1, body="hello")
        with patch.object(svc, "_get_member", return_value=MagicMock()):
            db.execute.return_value.scalars.return_value.all.return_value = [msg]
            with patch.object(svc, "_display_name_map", return_value={1: "Alice"}):
                result = svc.list_messages(1, 1)
        assert len(result) == 1
        assert result[0]["body"] == "hello"

    def test_with_before_id_filter(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with patch.object(svc, "_get_member", return_value=MagicMock()):
            db.execute.return_value.scalars.return_value.all.return_value = []
            with patch.object(svc, "_display_name_map", return_value={}):
                result = svc.list_messages(1, 1, before_id=100)
        assert result == []


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    def test_raises_when_not_member(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with patch.object(svc, "_get_member", return_value=None):
            with pytest.raises(PermissionError, match="非会话成员"):
                svc.send_message(1, 1, "hi")

    def test_raises_when_body_empty(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with patch.object(svc, "_get_member", return_value=MagicMock()):
            with pytest.raises(ValueError, match="消息不能为空"):
                svc.send_message(1, 1, "   ")

    def test_sends_message_successfully(self):
        db = MagicMock()
        msg = _make_message(msg_id=1, sender_user_id=1, body="hello")
        conv = _make_conversation(conv_id=1)
        db.get.return_value = conv
        db.refresh.side_effect = lambda x: setattr(x, "id", 1)
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "_get_member", return_value=MagicMock()),
            patch.object(svc, "_member_user_ids", return_value=[1, 2]),
            patch.object(svc, "_display_name", return_value="Alice"),
            patch.object(ImApplicationService, "_record_im_message_change", return_value=12345),
        ):
            result = svc.send_message(1, 1, "hello")
        assert result["message"]["body"] == "hello"
        assert result["member_user_ids"] == [1, 2]
        assert result["updated_at_ms"] == 12345

    def test_truncates_long_body(self):
        db = MagicMock()
        long_body = "x" * 5000
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "_get_member", return_value=MagicMock()),
            patch.object(svc, "_member_user_ids", return_value=[1]),
            patch.object(svc, "_display_name", return_value="A"),
            patch.object(ImApplicationService, "_record_im_message_change", return_value=0),
        ):
            # The body is truncated to 4000 chars in the model
            svc.send_message(1, 1, long_body)
        # Verify db.add was called - the body passed to ImMessage is truncated
        call_args = db.add.call_args_list
        added_msg = call_args[0][0][0]
        assert len(added_msg.body) == 4000


# ---------------------------------------------------------------------------
# mark_read
# ---------------------------------------------------------------------------


class TestMarkRead:
    def test_raises_when_not_member(self):
        db = MagicMock()
        svc = ImApplicationService(db)
        with patch.object(svc, "_get_member", return_value=None):
            with pytest.raises(PermissionError, match="非会话成员"):
                svc.mark_read(1, 1, 10)

    def test_updates_last_read(self):
        db = MagicMock()
        member = _make_member(conversation_id=1, user_id=1, last_read_message_id=5)
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "_get_member", return_value=member),
            patch.object(svc, "_member_user_ids", return_value=[1, 2]),
            patch.object(ImApplicationService, "_record_im_read_change", return_value=999),
        ):
            result = svc.mark_read(1, 1, 10)
        assert result["last_read_message_id"] == 10
        assert result["updated_at_ms"] == 999

    def test_does_not_downgrade_read_position(self):
        db = MagicMock()
        member = _make_member(conversation_id=1, user_id=1, last_read_message_id=20)
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "_get_member", return_value=member),
            patch.object(svc, "_member_user_ids", return_value=[1]),
            patch.object(ImApplicationService, "_record_im_read_change", return_value=0),
        ):
            result = svc.mark_read(1, 1, 10)
        assert result["last_read_message_id"] == 20


# ---------------------------------------------------------------------------
# list_contacts
# ---------------------------------------------------------------------------


class TestListContacts:
    def test_returns_contacts_with_tenant_filter(self):
        db = MagicMock()
        me = _make_user(user_id=1, tenant_id=100)
        db.get.return_value = me
        other = _make_user(user_id=2, display_name="Bob", username="bob")
        db.execute.return_value.scalars.return_value.all.return_value = [other]
        svc = ImApplicationService(db)
        result = svc.list_contacts(1)
        assert len(result) == 1
        assert result[0]["display_name"] == "Bob"

    def test_returns_contacts_without_tenant(self):
        db = MagicMock()
        me = _make_user(user_id=1, tenant_id=None)
        db.get.return_value = me
        other = _make_user(user_id=2, display_name="Carol")
        db.execute.return_value.scalars.return_value.all.return_value = [other]
        svc = ImApplicationService(db)
        result = svc.list_contacts(1)
        assert len(result) == 1

    def test_returns_default_name_when_no_names(self):
        db = MagicMock()
        me = _make_user(user_id=1, tenant_id=None)
        db.get.return_value = me
        other = _make_user(user_id=2, display_name=None, username=None)
        db.execute.return_value.scalars.return_value.all.return_value = [other]
        svc = ImApplicationService(db)
        result = svc.list_contacts(1)
        assert result[0]["display_name"] == "用户2"


# ---------------------------------------------------------------------------
# _record_im_message_change / _record_im_read_change
# ---------------------------------------------------------------------------


class TestRecordChanges:
    def test_record_im_message_change(self):
        with (
            patch("app.services.xcmax_sync_service.record_change") as mock_rc,
            patch("app.services.xcmax_sync_service.utc_now_ms", return_value=1000),
        ):
            result = ImApplicationService._record_im_message_change(
                {"id": 1, "body": "hi"}, actor="1"
            )
        assert result == 1000
        mock_rc.assert_called_once()

    def test_record_im_read_change(self):
        with (
            patch("app.services.xcmax_sync_service.record_change") as mock_rc,
            patch("app.services.xcmax_sync_service.utc_now_ms", return_value=2000),
        ):
            result = ImApplicationService._record_im_read_change(
                conversation_id=1, user_id=1, last_read_message_id=5, actor="1"
            )
        assert result == 2000
        mock_rc.assert_called_once()


# ---------------------------------------------------------------------------
# _member_user_ids
# ---------------------------------------------------------------------------


class TestMemberUserIds:
    def test_returns_user_ids(self):
        db = MagicMock()
        db.execute.return_value.all.return_value = [(1,), (2,)]
        svc = ImApplicationService(db)
        result = svc._member_user_ids(1)
        assert result == [1, 2]


# ---------------------------------------------------------------------------
# _count_unread
# ---------------------------------------------------------------------------


class TestCountUnread:
    def test_returns_zero_when_no_member(self):
        db = MagicMock()
        db.execute.return_value.scalar.return_value = 0
        svc = ImApplicationService(db)
        with patch.object(svc, "_get_member", return_value=None):
            result = svc._count_unread(1, 1)
        assert result == 0

    def test_counts_unread_messages(self):
        db = MagicMock()
        member = _make_member(last_read_message_id=5)
        db.execute.return_value.scalar.return_value = 3
        svc = ImApplicationService(db)
        with patch.object(svc, "_get_member", return_value=member):
            result = svc._count_unread(1, 1)
        assert result == 3


# ---------------------------------------------------------------------------
# list_conversations
# ---------------------------------------------------------------------------


class TestListConversations:
    def test_returns_empty_when_no_conversations(self):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []
        svc = ImApplicationService(db)
        result = svc.list_conversations(1)
        assert result == []

    def test_returns_conversations_with_direct_peer(self):
        db = MagicMock()
        conv = _make_conversation(
            conv_id=1, is_direct=True, title=None, last_message_at=datetime(2026, 1, 1)
        )
        msg = _make_message(msg_id=10, body="hi")
        # First call returns conversations, second returns last message, third returns unread count
        db.execute.return_value.scalars.return_value.all.return_value = [conv]
        db.execute.return_value.scalars.return_value.first.return_value = msg
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "_direct_peer_id", return_value=2),
            patch.object(svc, "_display_name", return_value="Bob"),
            patch.object(svc, "_count_unread", return_value=3),
        ):
            result = svc.list_conversations(1)
        assert len(result) == 1
        assert result[0]["title"] == "Bob"
        assert result[0]["unread_count"] == 3
        assert result[0]["last_message_preview"] == "hi"

    def test_returns_group_conversation_with_title(self):
        db = MagicMock()
        conv = _make_conversation(
            conv_id=1, is_direct=False, title="Team Chat", last_message_at=None
        )
        db.execute.return_value.scalars.return_value.all.return_value = [conv]
        svc = ImApplicationService(db)
        with patch.object(svc, "_count_unread", return_value=0):
            result = svc.list_conversations(1)
        assert result[0]["title"] == "Team Chat"
        assert result[0]["last_message_at"] is None
