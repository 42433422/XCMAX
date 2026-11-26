"""Employee inbox, replies and customer service summaries."""

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
from tests.test_application.test_im_employee_mixin_cov import (
    _exec_chain,
    _make_conversation,
    _make_message,
    _make_profile,
)

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
        mock_mark.assert_called_once_with(123, 8, 5, record_sync=False)

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
            patch.object(svc, "mark_read", side_effect=OSError("boom")),
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
        mock_send.assert_called_once_with(
            99,
            7,
            "hello",
            origin="manual",
            operator_user_id=None,
            record_sync=False,
        )


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
        with patch.object(svc, "ensure_employee_user", side_effect=OSError("nope")):
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
            patch.object(svc, "get_or_create_direct", side_effect=OSError("fail")),
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
                side_effect=OSError("boom"),
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


def test_customer_push_skips_sender_in_admin_recipients():
    svc = ImApplicationService(MagicMock())
    with (
        patch.object(svc, "enterprise_cs_user_id", return_value=9),
        patch.object(svc, "_display_name", return_value="Sender"),
        patch.object(svc, "_query_admin_user_ids", return_value=[2, 3]),
        patch("app.domain.shared_services.mobile_push.notify_user") as notify,
    ):
        svc._maybe_push_cs_message(7, 2, "hello", [9, 2])
    notify.assert_called_once_with(
        3,
        "客户咨询 · Sender",
        "hello",
        {"type": "cs_inbox", "conversation_id": "7", "route": "admin_cs_console"},
    )
