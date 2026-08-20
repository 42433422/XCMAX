"""Tests for app.application.im_employee_mixin — coverage ramp.

Exercises every branch of ImEmployeeMixin via the concrete
ImApplicationService subclass. Only the SQLAlchemy session (an external
dependency) is mocked; sibling methods on the same service are stubbed via
``patch.object`` only when their own coverage is already established.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.application.im_app_service import ImApplicationService
from app.application.im_employee_mixin import (
    AI_EMPLOYEE_ROLE,
    AI_EMPLOYEE_USERNAME_PREFIX,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    user_id: int = 1,
    display_name: str = "Alice",
    username: str = "alice",
    is_active: bool = True,
    role: str = "user",
) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    u.display_name = display_name
    u.username = username
    u.is_active = is_active
    u.role = role
    u.password = "!"
    u.email = ""
    u.created_at = datetime(2026, 1, 1)
    return u


def _make_profile(
    profile_id: int = 1,
    employee_id: str = "emp1",
    user_id: int = 10,
    mod_id: str = "",
    display_name: str = "",
    avatar_url: str = "",
    owner_user_id: int = 0,
) -> MagicMock:
    p = MagicMock()
    p.id = profile_id
    p.employee_id = employee_id
    p.user_id = user_id
    p.mod_id = mod_id
    p.display_name = display_name
    p.avatar_url = avatar_url
    p.owner_user_id = owner_user_id
    return p


def _make_conversation(
    conv_id: int = 1,
    is_direct: bool = True,
    title: str | None = None,
    last_message_at: datetime | None = None,
) -> MagicMock:
    c = MagicMock()
    c.id = conv_id
    c.is_direct = is_direct
    c.title = title
    c.last_message_at = last_message_at
    return c


def _make_message(
    msg_id: int = 1,
    conversation_id: int = 1,
    sender_user_id: int = 1,
    body: str = "hello",
    created_at: datetime | None = None,
) -> MagicMock:
    m = MagicMock()
    m.id = msg_id
    m.conversation_id = conversation_id
    m.sender_user_id = sender_user_id
    m.body = body
    m.created_at = created_at or datetime(2026, 1, 1, 12, 0, 0)
    return m


def _exec_chain(
    *,
    first: Any = None,
    all_list: list[Any] | None = None,
    scalar: Any = None,
) -> MagicMock:
    """Build a chain whose .scalars().first()/.all()/.scalar() return given values."""
    chain = MagicMock()
    chain.scalars.return_value.first.return_value = first
    chain.scalars.return_value.all.return_value = all_list if all_list is not None else []
    chain.scalars.return_value.scalar.return_value = scalar
    chain.first.return_value = first
    chain.all.return_value = all_list if all_list is not None else []
    chain.scalar.return_value = scalar
    return chain


def _wire_flush_id(db: MagicMock, *, new_id: int = 100) -> None:
    """Make db.flush() assign ``new_id`` to the most recently added object."""

    def _flush(*_args: Any, **_kwargs: Any) -> None:
        if db.add.call_args_list:
            last_added = db.add.call_args_list[-1][0][0]
            if getattr(last_added, "id", None) is None:
                last_added.id = new_id

    db.flush.side_effect = _flush
    db.refresh.side_effect = lambda _x: None


# ---------------------------------------------------------------------------
# enterprise_cs_user_id
# ---------------------------------------------------------------------------


class TestEnterpriseCsUserId:
    def test_returns_int_id_when_cs_user_exists(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        cs = _make_user(user_id=42, username="enterprise-cs")
        with patch.object(svc, "_ensure_enterprise_dedicated_cs_user", return_value=cs):
            assert svc.enterprise_cs_user_id() == 42

    def test_returns_none_when_cs_user_is_none(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        with patch.object(svc, "_ensure_enterprise_dedicated_cs_user", return_value=None):
            assert svc.enterprise_cs_user_id() is None


# ---------------------------------------------------------------------------
# ensure_employee_user
# ---------------------------------------------------------------------------


class TestEnsureEmployeeUser:
    def test_raises_on_empty_employee_id(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="employee_id 必填"):
            svc.ensure_employee_user("")

    def test_raises_on_whitespace_only_employee_id(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="employee_id 必填"):
            svc.ensure_employee_user("   ")

    def test_raises_on_none_employee_id(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="employee_id 必填"):
            svc.ensure_employee_user(None)  # type: ignore[arg-type]

    def test_creates_new_user_and_new_profile(self) -> None:
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(first=None),  # User lookup
            _exec_chain(first=None),  # Profile lookup
        ]
        _wire_flush_id(db, new_id=200)
        svc = ImApplicationService(db)

        result = svc.ensure_employee_user(
            "emp-1", mod_id="mod-1", display_name="Bob", avatar_url="http://a"
        )

        assert result == 200
        # user add + profile add = 2 add calls
        assert db.add.call_count == 2
        db.commit.assert_called_once()
        db.refresh.assert_called_once()

    def test_creates_new_user_falls_back_to_eid_when_display_name_empty(self) -> None:
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(first=None),
            _exec_chain(first=None),
        ]
        _wire_flush_id(db, new_id=300)
        svc = ImApplicationService(db)

        svc.ensure_employee_user("emp-2")

        added_user = db.add.call_args_list[0][0][0]
        assert added_user.display_name == "emp-2"

    def test_existing_user_no_changes_skips_flush(self) -> None:
        row = _make_user(
            user_id=11,
            display_name="Same",
            username=f"{AI_EMPLOYEE_USERNAME_PREFIX}emp1",
        )
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(first=row),  # User lookup
            _exec_chain(first=None),  # Profile lookup (new profile)
        ]
        _wire_flush_id(db, new_id=999)  # should not be invoked for row (existing)
        svc = ImApplicationService(db)

        result = svc.ensure_employee_user("emp1", display_name="Same")

        assert result == 11
        # only the profile should be added (no flush triggered for unchanged user)
        # flush is only called inside the "changed" branch — assert not called for user
        # (it IS still called nowhere for the user branch; db.flush should have 0 calls)
        db.flush.assert_not_called()

    def test_existing_user_display_name_changed_triggers_flush(self) -> None:
        row = _make_user(
            user_id=12,
            display_name="OldName",
            username=f"{AI_EMPLOYEE_USERNAME_PREFIX}emp1",
        )
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(first=row),
            _exec_chain(first=None),
        ]
        _wire_flush_id(db, new_id=12)
        svc = ImApplicationService(db)

        result = svc.ensure_employee_user("emp1", display_name="NewName")

        assert result == 12
        assert row.display_name == "NewName"
        db.flush.assert_called_once()

    def test_existing_user_inactive_gets_reactivated(self) -> None:
        row = _make_user(
            user_id=13,
            display_name="Bob",
            is_active=False,
            username=f"{AI_EMPLOYEE_USERNAME_PREFIX}emp1",
        )
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(first=row),
            _exec_chain(first=None),
        ]
        _wire_flush_id(db, new_id=13)
        svc = ImApplicationService(db)

        svc.ensure_employee_user("emp1", display_name="Bob")

        assert row.is_active is True
        db.flush.assert_called_once()

    def test_existing_user_both_changes_trigger_single_flush(self) -> None:
        row = _make_user(
            user_id=14,
            display_name="Old",
            is_active=False,
            username=f"{AI_EMPLOYEE_USERNAME_PREFIX}emp1",
        )
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(first=row),
            _exec_chain(first=None),
        ]
        _wire_flush_id(db, new_id=14)
        svc = ImApplicationService(db)

        svc.ensure_employee_user("emp1", display_name="New")

        assert row.display_name == "New"
        assert row.is_active is True
        # only one flush call despite both fields changing
        db.flush.assert_called_once()

    def test_existing_profile_no_owner_update_when_owner_zero(self) -> None:
        row = _make_user(user_id=15, display_name="Bob")
        profile = _make_profile(profile_id=2, employee_id="emp1", user_id=99, owner_user_id=0)
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(first=row),
            _exec_chain(first=profile),
        ]
        _wire_flush_id(db, new_id=15)
        svc = ImApplicationService(db)

        result = svc.ensure_employee_user(
            "emp1",
            mod_id="m1",
            display_name="BobNew",
            avatar_url="http://x",
            owner_user_id=0,
        )

        assert result == 15
        assert profile.user_id == 15
        assert profile.mod_id == "m1"
        assert profile.display_name == "BobNew"
        assert profile.avatar_url == "http://x"
        # owner_user_id should NOT be updated since 0 is not > 0
        assert profile.owner_user_id == 0
        # no add calls (both existed)
        db.add.assert_not_called()

    def test_existing_profile_owner_update_when_owner_positive(self) -> None:
        row = _make_user(user_id=16, display_name="Bob")
        profile = _make_profile(profile_id=3, employee_id="emp1", user_id=99, owner_user_id=0)
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(first=row),
            _exec_chain(first=profile),
        ]
        _wire_flush_id(db, new_id=16)
        svc = ImApplicationService(db)

        svc.ensure_employee_user(
            "emp1", mod_id="", display_name="Bob", avatar_url="", owner_user_id=7
        )

        assert profile.owner_user_id == 7

    def test_existing_profile_keeps_avatar_when_new_empty(self) -> None:
        row = _make_user(user_id=17, display_name="Bob")
        profile = _make_profile(
            profile_id=4, employee_id="emp1", user_id=99, avatar_url="http://old"
        )
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(first=row),
            _exec_chain(first=profile),
        ]
        _wire_flush_id(db, new_id=17)
        svc = ImApplicationService(db)

        svc.ensure_employee_user("emp1", display_name="Bob", avatar_url="")

        # avatar_url stays because new avatar is empty
        assert profile.avatar_url == "http://old"

    def test_existing_profile_keeps_mod_id_when_new_empty(self) -> None:
        row = _make_user(user_id=18, display_name="Bob")
        profile = _make_profile(profile_id=5, employee_id="emp1", user_id=99, mod_id="old-mod")
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(first=row),
            _exec_chain(first=profile),
        ]
        _wire_flush_id(db, new_id=18)
        svc = ImApplicationService(db)

        svc.ensure_employee_user("emp1", mod_id="", display_name="Bob")

        assert profile.mod_id == "old-mod"

    def test_strips_employee_id(self) -> None:
        """employee_id should be stripped before use."""
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(first=None),
            _exec_chain(first=None),
        ]
        _wire_flush_id(db, new_id=500)
        svc = ImApplicationService(db)

        svc.ensure_employee_user("  emp-pad  ", display_name="X")

        # Profile created with stripped employee_id
        added_profile = db.add.call_args_list[1][0][0]
        assert added_profile.employee_id == "emp-pad"

    def test_strips_display_name_and_avatar(self) -> None:
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(first=None),
            _exec_chain(first=None),
        ]
        _wire_flush_id(db, new_id=501)
        svc = ImApplicationService(db)

        svc.ensure_employee_user("emp3", display_name="  Spaced  ", avatar_url="  http://a  ")

        added_user = db.add.call_args_list[0][0][0]
        assert added_user.display_name == "Spaced"
        added_profile = db.add.call_args_list[1][0][0]
        assert added_profile.avatar_url == "http://a"

    def test_username_uses_prefix_concatenated_with_eid(self) -> None:
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(first=None),
            _exec_chain(first=None),
        ]
        _wire_flush_id(db, new_id=502)
        svc = ImApplicationService(db)

        svc.ensure_employee_user("emp-uniq")

        added_user = db.add.call_args_list[0][0][0]
        assert added_user.username == f"{AI_EMPLOYEE_USERNAME_PREFIX}emp-uniq"
        assert added_user.role == AI_EMPLOYEE_ROLE
        assert added_user.is_active is True
        assert added_user.password == "!"


# ---------------------------------------------------------------------------
# get_employee_owner
# ---------------------------------------------------------------------------


class TestGetEmployeeOwner:
    def test_returns_zero_for_empty_employee_id(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("") == 0

    def test_returns_zero_for_whitespace_employee_id(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("   ") == 0

    def test_returns_zero_for_none_employee_id(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.get_employee_owner(None) == 0  # type: ignore[arg-type]

    def test_returns_zero_when_profile_not_found(self) -> None:
        db = MagicMock()
        db.execute.return_value.first.return_value = None
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("emp1") == 0

    def test_returns_owner_id_when_valid(self) -> None:
        db = MagicMock()
        db.execute.return_value.first.return_value = (42,)
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("emp1") == 42

    def test_returns_zero_when_owner_id_is_zero(self) -> None:
        db = MagicMock()
        db.execute.return_value.first.return_value = (0,)
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("emp1") == 0

    def test_returns_zero_when_owner_id_is_negative(self) -> None:
        db = MagicMock()
        db.execute.return_value.first.return_value = (-5,)
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("emp1") == 0

    def test_returns_zero_when_owner_id_is_none(self) -> None:
        db = MagicMock()
        db.execute.return_value.first.return_value = (None,)
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("emp1") == 0

    def test_returns_zero_on_type_error(self) -> None:
        db = MagicMock()
        # row[0] raises TypeError when row is not subscriptable
        bad_row = MagicMock()
        bad_row.__getitem__.side_effect = TypeError("not subscriptable")
        db.execute.return_value.first.return_value = bad_row
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("emp1") == 0

    def test_returns_zero_on_value_error(self) -> None:
        db = MagicMock()
        # row[0] returns a non-numeric string → int() raises ValueError
        bad_row = MagicMock()
        bad_row.__getitem__.return_value = "not-an-int"
        db.execute.return_value.first.return_value = bad_row
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("emp1") == 0

    def test_strips_employee_id_before_query(self) -> None:
        db = MagicMock()
        db.execute.return_value.first.return_value = (7,)
        svc = ImApplicationService(db)
        assert svc.get_employee_owner("  emp1  ") == 7


# ---------------------------------------------------------------------------
# set_employee_owner
# ---------------------------------------------------------------------------


class TestSetEmployeeOwner:
    def test_returns_false_for_empty_employee_id(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.set_employee_owner("", 5) is False

    def test_returns_false_for_zero_owner_user_id(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.set_employee_owner("emp1", 0) is False

    def test_returns_false_for_negative_owner_user_id(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.set_employee_owner("emp1", -1) is False

    def test_returns_false_when_profile_not_found(self) -> None:
        db = MagicMock()
        db.execute.return_value.scalars.return_value.first.return_value = None
        svc = ImApplicationService(db)
        assert svc.set_employee_owner("emp1", 5) is False

    def test_raises_when_owner_user_does_not_exist(self) -> None:
        profile = _make_profile(profile_id=1, employee_id="emp1")
        db = MagicMock()
        # First execute: profile lookup (returns profile)
        # Second execute: User.id lookup (returns None)
        db.execute.side_effect = [
            _exec_chain(first=profile),
            _exec_chain(first=None),
        ]
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="owner_user_id=5 不存在"):
            svc.set_employee_owner("emp1", 5)

    def test_sets_owner_and_commits_when_owner_exists(self) -> None:
        profile = _make_profile(profile_id=1, employee_id="emp1", owner_user_id=0)
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(first=profile),
            _exec_chain(first=99),  # owner exists
        ]
        svc = ImApplicationService(db)

        result = svc.set_employee_owner("emp1", 99)

        assert result is True
        assert profile.owner_user_id == 99
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# send_employee_message
# ---------------------------------------------------------------------------


class TestSendEmployeeMessage:
    def test_raises_on_empty_body(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="消息不能为空"):
            svc.send_employee_message(1, "emp1", "   ")

    def test_raises_on_none_body(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="消息不能为空"):
            svc.send_employee_message(1, "emp1", None)  # type: ignore[arg-type]

    def test_raises_on_zero_boss_uid(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="boss_user_id 非法"):
            svc.send_employee_message(0, "emp1", "hi")

    def test_raises_on_negative_boss_uid(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="boss_user_id 非法"):
            svc.send_employee_message(-3, "emp1", "hi")

    def test_raises_when_boss_user_not_found(self) -> None:
        db = MagicMock()
        db.execute.return_value.scalars.return_value.first.return_value = None
        svc = ImApplicationService(db)
        with pytest.raises(ValueError, match="boss_user_id=10 不存在"):
            svc.send_employee_message(10, "emp1", "hi")

    def test_success_path_returns_payload(self) -> None:
        boss = _make_user(user_id=10, display_name="Boss")
        db = MagicMock()
        db.execute.return_value.scalars.return_value.first.return_value = boss
        svc = ImApplicationService(db)

        with (
            patch.object(svc, "ensure_employee_user", return_value=200) as mock_ensure,
            patch.object(
                svc, "get_or_create_direct", return_value={"id": 7, "created": True}
            ) as mock_conv,
            patch.object(
                svc,
                "send_message",
                return_value={
                    "message": {"id": 99, "body": "hi"},
                    "member_user_ids": [10, 200],
                    "updated_at_ms": 1234,
                },
            ) as mock_send,
        ):
            result = svc.send_employee_message(
                10,
                "emp1",
                "  hi  ",
                mod_id="m1",
                display_name="Bob",
                avatar_url="http://a",
                owner_user_id=5,
            )

        assert result["conversation_id"] == 7
        assert result["employee_user_id"] == 200
        assert result["message"]["body"] == "hi"
        assert result["member_user_ids"] == [10, 200]
        assert result["created"] is True
        # ensure_employee_user should be called with stripped body
        mock_ensure.assert_called_once_with(
            "emp1",
            mod_id="m1",
            display_name="Bob",
            avatar_url="http://a",
            owner_user_id=5,
        )
        mock_conv.assert_called_once_with(10, 200)
        mock_send.assert_called_once_with(7, 200, "hi")


# ---------------------------------------------------------------------------
# list_cs_inbox
# ---------------------------------------------------------------------------


class TestListCsInbox:
    def test_returns_empty_when_cs_user_is_none(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        with patch.object(svc, "enterprise_cs_user_id", return_value=None):
            assert svc.list_cs_inbox() == []

    def test_returns_empty_when_no_conversations(self) -> None:
        db = MagicMock()
        db.execute.return_value.all.return_value = []
        svc = ImApplicationService(db)
        with patch.object(svc, "enterprise_cs_user_id", return_value=5):
            assert svc.list_cs_inbox() == []

    def test_returns_inbox_with_peer_and_messages(self) -> None:
        conv = _make_conversation(
            conv_id=11, is_direct=True, title="cs", last_message_at=datetime(2026, 7, 1)
        )
        db = MagicMock()
        # First execute: ImConversationMember.conversation_id lookup
        # Second execute: ImConversation lookup
        db.execute.side_effect = [
            _exec_chain(all_list=[(11,)]),
            _exec_chain(all_list=[conv]),
        ]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=5),
            patch.object(svc, "_direct_peer_id", return_value=20),
            patch.object(svc, "_display_name", return_value="Customer"),
            patch.object(svc, "_count_unread", return_value=3),
        ):
            result = svc.list_cs_inbox()

        assert len(result) == 1
        item = result[0]
        assert item["id"] == 11
        assert item["customer_user_id"] == 20
        assert item["customer_name"] == "Customer"
        assert item["last_message_at"] == "2026-07-01T00:00:00"
        assert item["unread_count"] == 3

    def test_skips_conversation_without_peer_id(self) -> None:
        conv = _make_conversation(conv_id=12, is_direct=True, last_message_at=datetime(2026, 7, 2))
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(all_list=[(12,)]),
            _exec_chain(all_list=[conv]),
        ]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=5),
            patch.object(svc, "_direct_peer_id", return_value=None),
        ):
            result = svc.list_cs_inbox()
        assert result == []

    def test_returns_empty_string_for_missing_last_message_at(self) -> None:
        conv = _make_conversation(conv_id=13, is_direct=True, last_message_at=None)
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(all_list=[(13,)]),
            _exec_chain(all_list=[conv]),
        ]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=5),
            patch.object(svc, "_direct_peer_id", return_value=25),
            patch.object(svc, "_display_name", return_value="C"),
            patch.object(svc, "_count_unread", return_value=0),
        ):
            result = svc.list_cs_inbox()
        assert result[0]["last_message_at"] == ""


# ---------------------------------------------------------------------------
# cs_inbox_messages
# ---------------------------------------------------------------------------


class TestCsInboxMessages:
    def test_returns_empty_when_cs_user_is_none(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        with patch.object(svc, "enterprise_cs_user_id", return_value=None):
            assert svc.cs_inbox_messages(123) == []

    def test_returns_messages_and_marks_read(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        messages = [
            {"id": 1, "body": "a"},
            {"id": 5, "body": "b"},
        ]
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=8),
            patch.object(svc, "list_messages", return_value=messages) as mock_list,
            patch.object(svc, "mark_read") as mock_mark,
        ):
            result = svc.cs_inbox_messages(123)

        assert result == messages
        mock_list.assert_called_once_with(123, 8, limit=100)
        mock_mark.assert_called_once_with(123, 8, 5)

    def test_returns_empty_messages_without_mark_read(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=8),
            patch.object(svc, "list_messages", return_value=[]),
            patch.object(svc, "mark_read") as mock_mark,
        ):
            result = svc.cs_inbox_messages(123)

        assert result == []
        mock_mark.assert_not_called()

    def test_returns_messages_when_last_id_is_zero(self) -> None:
        """If last message id is 0/missing, mark_read is skipped but messages returned."""
        db = MagicMock()
        svc = ImApplicationService(db)
        messages = [{"id": 0, "body": "x"}]
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=8),
            patch.object(svc, "list_messages", return_value=messages),
            patch.object(svc, "mark_read") as mock_mark,
        ):
            result = svc.cs_inbox_messages(123)

        assert result == messages
        mock_mark.assert_not_called()

    def test_swallows_mark_read_exception_and_returns_messages(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        messages = [{"id": 9, "body": "x"}]
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=8),
            patch.object(svc, "list_messages", return_value=messages),
            patch.object(svc, "mark_read", side_effect=RuntimeError("boom")),
        ):
            result = svc.cs_inbox_messages(123)

        # Even though mark_read raised, messages are still returned
        assert result == messages

    def test_swallows_exception_when_messages_have_no_id_field(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        messages = [{"body": "x"}]  # no 'id' key
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=8),
            patch.object(svc, "list_messages", return_value=messages),
            patch.object(svc, "mark_read") as mock_mark,
        ):
            result = svc.cs_inbox_messages(123)

        assert result == messages
        mock_mark.assert_not_called()


# ---------------------------------------------------------------------------
# cs_reply
# ---------------------------------------------------------------------------


class TestCsReply:
    def test_raises_when_cs_user_is_none(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        with patch.object(svc, "enterprise_cs_user_id", return_value=None):
            with pytest.raises(ValueError, match="客服通道不可用"):
                svc.cs_reply(99, "hello")

    def test_returns_send_message_result_when_cs_available(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        expected = {"message": {"id": 1}, "member_user_ids": [1, 2]}
        with (
            patch.object(svc, "enterprise_cs_user_id", return_value=7),
            patch.object(svc, "send_message", return_value=expected) as mock_send,
        ):
            result = svc.cs_reply(99, "hello")

        assert result == expected
        mock_send.assert_called_once_with(99, 7, "hello")


# ---------------------------------------------------------------------------
# employee_im_summary
# ---------------------------------------------------------------------------


class TestEmployeeImSummary:
    def test_returns_empty_when_boss_uid_zero(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.employee_im_summary(0, [{"id": "e1"}]) == {}

    def test_returns_empty_when_boss_uid_negative(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.employee_im_summary(-5, [{"id": "e1"}]) == {}

    def test_returns_empty_when_boss_uid_none(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.employee_im_summary(None, [{"id": "e1"}]) == {}  # type: ignore[arg-type]

    def test_returns_empty_when_employees_empty(self) -> None:
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.employee_im_summary(10, []) == {}

    def test_returns_empty_when_no_valid_employee_ids(self) -> None:
        """All employees with empty/missing id should be filtered out."""
        db = MagicMock()
        svc = ImApplicationService(db)
        assert svc.employee_im_summary(10, [{"id": ""}, {}, {"id": "   "}]) == {}

    def test_returns_empty_when_no_profiles_and_ensure_fails(self) -> None:
        """All eids require ensure_employee_user; if all raise, returns {}."""
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []  # no profiles
        svc = ImApplicationService(db)
        with patch.object(svc, "ensure_employee_user", side_effect=RuntimeError("nope")):
            result = svc.employee_im_summary(10, [{"id": "e1"}, {"id": "e2"}])
        assert result == {}

    def test_summary_with_existing_profiles_and_conversations(self) -> None:
        """Profiles exist, conversations exist, last message present."""
        profile_e1 = _make_profile(profile_id=1, employee_id="e1", user_id=21)
        profile_e2 = _make_profile(profile_id=2, employee_id="e2", user_id=22)
        conv1 = _make_conversation(
            conv_id=101, is_direct=True, last_message_at=datetime(2026, 7, 1)
        )
        last_msg = _make_message(msg_id=500, body="hi")
        db = MagicMock()
        # 1st execute: AiEmployeeProfile lookup
        # 2nd execute: ImConversation query (returns [conv1])
        # 3rd execute: ImMessage query for last_msg of conv1
        db.execute.side_effect = [
            _exec_chain(all_list=[profile_e1, profile_e2]),
            _exec_chain(all_list=[conv1]),
            _exec_chain(first=last_msg),
        ]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "_direct_peer_id", return_value=21),
            patch.object(svc, "_count_unread", return_value=2),
            patch.object(svc, "get_or_create_direct", return_value={"id": 102}),
        ):
            result = svc.employee_im_summary(
                10,
                [
                    {
                        "id": "e1",
                        "name": "Alice",
                        "mod_id": "m1",
                        "avatar_url": "http://a",
                    },
                    {"id": "e2", "name": "Bob"},
                ],
            )

        assert "e1" in result
        assert result["e1"]["im_conv_id"] == 101
        assert result["e1"]["im_last_message"] == "hi"
        assert result["e1"]["im_last_message_at"] == "2026-07-01T00:00:00"
        assert result["e1"]["im_unread_count"] == 2

    def test_summary_truncates_long_last_message(self) -> None:
        profile = _make_profile(profile_id=1, employee_id="e1", user_id=21)
        conv = _make_conversation(conv_id=101, is_direct=True, last_message_at=datetime(2026, 7, 1))
        long_body = "x" * 200
        last_msg = _make_message(msg_id=500, body=long_body)
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(all_list=[profile]),
            _exec_chain(all_list=[conv]),
            _exec_chain(first=last_msg),
        ]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "_direct_peer_id", return_value=21),
            patch.object(svc, "_count_unread", return_value=0),
        ):
            result = svc.employee_im_summary(10, [{"id": "e1", "name": "A"}])

        assert result["e1"]["im_last_message"] == "x" * 120

    def test_summary_with_no_last_message(self) -> None:
        profile = _make_profile(profile_id=1, employee_id="e1", user_id=21)
        conv = _make_conversation(conv_id=101, is_direct=True, last_message_at=None)
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(all_list=[profile]),
            _exec_chain(all_list=[conv]),
            _exec_chain(first=None),  # no last message
        ]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "_direct_peer_id", return_value=21),
            patch.object(svc, "_count_unread", return_value=0),
        ):
            result = svc.employee_im_summary(10, [{"id": "e1", "name": "A"}])

        assert result["e1"]["im_last_message"] == ""
        assert result["e1"]["im_last_message_at"] == ""

    def test_summary_skips_conversation_when_peer_not_in_uid_map(self) -> None:
        profile = _make_profile(profile_id=1, employee_id="e1", user_id=21)
        conv = _make_conversation(conv_id=101, is_direct=True, last_message_at=datetime(2026, 7, 1))
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(all_list=[profile]),
            _exec_chain(all_list=[conv]),
        ]
        svc = ImApplicationService(db)
        # peer_id 999 not in uid_to_eid (which only has 21 -> e1), so conv is skipped.
        # get_or_create_direct fails in fallback, so e1 should not appear.
        with (
            patch.object(svc, "_direct_peer_id", return_value=999),
            patch.object(svc, "_count_unread", return_value=0),
            patch.object(svc, "get_or_create_direct", side_effect=RuntimeError("fail")),
        ):
            result = svc.employee_im_summary(10, [{"id": "e1", "name": "A"}])
        assert "e1" not in result

    def test_summary_skips_conversation_when_peer_id_is_zero(self) -> None:
        profile = _make_profile(profile_id=1, employee_id="e1", user_id=21)
        conv = _make_conversation(conv_id=101, is_direct=True, last_message_at=None)
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(all_list=[profile]),
            _exec_chain(all_list=[conv]),
        ]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "_direct_peer_id", return_value=0),
            patch.object(svc, "_count_unread", return_value=0),
            patch.object(
                svc,
                "get_or_create_direct",
                return_value={"id": 0, "created": False},
            ),
        ):
            result = svc.employee_im_summary(10, [{"id": "e1", "name": "A"}])

        # No matching conv (peer_id 0); fallback returns conv_id 0 which is filtered out
        assert result == {}

    def test_summary_falls_back_to_get_or_create_direct_for_missing_eid(self) -> None:
        profile = _make_profile(profile_id=1, employee_id="e1", user_id=21)
        # No conversations found (empty list)
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(all_list=[profile]),
            _exec_chain(all_list=[]),
        ]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "_count_unread", return_value=0),
            patch.object(
                svc,
                "get_or_create_direct",
                return_value={"id": 300, "created": True},
            ) as mock_gocd,
        ):
            result = svc.employee_im_summary(10, [{"id": "e1", "name": "A"}])

        assert result["e1"]["im_conv_id"] == 300
        assert result["e1"]["im_last_message"] == ""
        assert result["e1"]["im_last_message_at"] == ""
        assert result["e1"]["im_unread_count"] == 0
        mock_gocd.assert_called_once_with(10, 21)

    def test_summary_swallows_get_or_create_direct_exception(self) -> None:
        profile = _make_profile(profile_id=1, employee_id="e1", user_id=21)
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(all_list=[profile]),
            _exec_chain(all_list=[]),  # no conversations
        ]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "_count_unread", return_value=0),
            patch.object(
                svc,
                "get_or_create_direct",
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = svc.employee_im_summary(10, [{"id": "e1", "name": "A"}])

        # Exception swallowed; e1 not in result
        assert result == {}

    def test_summary_ensures_employee_user_for_missing_profile(self) -> None:
        """When profile doesn't exist for an eid, ensure_employee_user is called."""
        db = MagicMock()
        # 1st execute: AiEmployeeProfile lookup (returns empty)
        # 2nd execute: ImConversation lookup (returns empty since uid_to_uid populated by ensure)
        db.execute.side_effect = [
            _exec_chain(all_list=[]),
            _exec_chain(all_list=[]),
        ]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "ensure_employee_user", return_value=33) as mock_ensure,
            patch.object(svc, "_count_unread", return_value=0),
            patch.object(
                svc,
                "get_or_create_direct",
                return_value={"id": 400, "created": True},
            ),
        ):
            result = svc.employee_im_summary(
                10,
                [
                    {
                        "id": "e1",
                        "name": "Alice",
                        "mod_id": "m1",
                        "avatar_url": "http://a",
                    }
                ],
            )

        mock_ensure.assert_called_once_with(
            "e1", mod_id="m1", display_name="Alice", avatar_url="http://a"
        )
        assert result["e1"]["im_conv_id"] == 400

    def test_summary_extracts_mod_id_from_market_pkg_id_fallback(self) -> None:
        """When mod_id is missing, falls back to market_pkg_id."""
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(all_list=[]),
            _exec_chain(all_list=[]),
        ]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "ensure_employee_user", return_value=33) as mock_ensure,
            patch.object(svc, "_count_unread", return_value=0),
            patch.object(
                svc,
                "get_or_create_direct",
                return_value={"id": 400, "created": True},
            ),
        ):
            svc.employee_im_summary(
                10,
                [{"id": "e1", "market_pkg_id": "mp-1", "market_avatar": "http://m"}],
            )

        # ensure_employee_user called with mod_id=market_pkg_id, avatar=market_avatar
        mock_ensure.assert_called_once_with(
            "e1", mod_id="mp-1", display_name="e1", avatar_url="http://m"
        )

    def test_summary_uses_label_then_title_then_eid_for_display_name(self) -> None:
        db = MagicMock()
        db.execute.side_effect = [
            _exec_chain(all_list=[]),
            _exec_chain(all_list=[]),
            _exec_chain(all_list=[]),
            _exec_chain(all_list=[]),
        ]
        svc = ImApplicationService(db)
        with (
            patch.object(svc, "ensure_employee_user", return_value=1) as mock_ensure,
            patch.object(svc, "_count_unread", return_value=0),
            patch.object(svc, "get_or_create_direct", return_value={"id": 1, "created": True}),
        ):
            svc.employee_im_summary(
                10,
                [
                    {"id": "e1", "label": "L1"},
                    {"id": "e2", "title": "T2"},
                    {"id": "e3"},  # falls back to eid
                ],
            )

        # Three calls; check display_name passed for each
        calls = mock_ensure.call_args_list
        assert calls[0].kwargs["display_name"] == "L1"
        assert calls[1].kwargs["display_name"] == "T2"
        assert calls[2].kwargs["display_name"] == "e3"
