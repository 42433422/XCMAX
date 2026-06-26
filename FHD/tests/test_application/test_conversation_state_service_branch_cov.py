"""Branch-coverage tests for app.application.conversation_state_service.

Targets all conditional branches in:
* ``_read_all`` — file missing / empty lines / JSONDecodeError / OSError
* ``get_state`` — existing row vs new row creation
* ``get_all_states`` — filtering by user_id
* ``toggle_pinned`` / ``mark_unread`` / ``mark_read`` / ``toggle_followed``
  / ``toggle_hidden`` — updater branches (current > 0 vs ==0, default True/False)
* ``delete`` — found vs not found
* ``_public`` — defaults for missing fields
* ``_update`` — target found vs target is None
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.application.conversation_state_service import (
    ConversationStateService,
    _safe_json_line,
)


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "conv_state"


@pytest.fixture
def service(storage_root: Path) -> ConversationStateService:
    return ConversationStateService(storage_root=storage_root)


class TestSafeJsonLine:
    def test_compact_separators_and_newline(self) -> None:
        line = _safe_json_line({"a": 1, "b": "中文"})
        assert line.endswith("\n")
        assert json.loads(line) == {"a": 1, "b": "中文"}
        # ensure_ascii=False → 中文 preserved
        assert "中文" in line

    def test_no_extra_whitespace(self) -> None:
        line = _safe_json_line({"a": 1})
        assert line == '{"a":1}\n'


class TestReadAll:
    def test_file_missing_returns_empty(self, storage_root: Path) -> None:
        svc = ConversationStateService(storage_root=storage_root)
        # _state_path parent exists but file does not
        assert svc._read_all() == []

    def test_empty_lines_skipped(self, service: ConversationStateService) -> None:
        service._state_path.write_text(
            "\n" + _safe_json_line({"user_id": 1, "conversation_id": "c1"}) + "\n\n",
            encoding="utf-8",
        )
        rows = service._read_all()
        assert len(rows) == 1
        assert rows[0]["conversation_id"] == "c1"

    def test_json_decode_error_skipped(self, service: ConversationStateService) -> None:
        service._state_path.write_text(
            "not-json\n" + _safe_json_line({"user_id": 1, "conversation_id": "c1"}),
            encoding="utf-8",
        )
        rows = service._read_all()
        assert len(rows) == 1

    def test_os_error_returns_empty(self, service: ConversationStateService) -> None:
        with patch.object(Path, "exists", return_value=True):
            with patch.object(
                Path,
                "open",
                side_effect=OSError("disk error"),
            ):
                assert service._read_all() == []

    def test_strips_whitespace_lines(self, service: ConversationStateService) -> None:
        # Lines with only whitespace should be skipped (line.strip() == "")
        service._state_path.write_text("   \n\t\n", encoding="utf-8")
        assert service._read_all() == []


class TestGetState:
    def test_existing_row_returned(self, service: ConversationStateService) -> None:
        service._state_path.write_text(
            _safe_json_line(
                {
                    "user_id": 5,
                    "conversation_id": "conv-1",
                    "is_pinned": True,
                    "is_hidden": False,
                    "is_followed": False,
                    "unread_count": 3,
                }
            ),
            encoding="utf-8",
        )
        state = service.get_state(user_id=5, conversation_id="conv-1")
        assert state["is_pinned"] is True
        assert state["is_followed"] is False
        assert state["unread_count"] == 3

    def test_new_row_created_when_missing(
        self, service: ConversationStateService
    ) -> None:
        state = service.get_state(user_id=7, conversation_id="conv-new")
        assert state["user_id"] == 7
        assert state["conversation_id"] == "conv-new"
        assert state["is_pinned"] is False
        assert state["is_hidden"] is False
        assert state["is_followed"] is True
        assert state["unread_count"] == 0
        # row persisted
        rows = service._read_all()
        assert len(rows) == 1
        assert rows[0]["conversation_id"] == "conv-new"

    def test_user_id_coerced_to_int(self, service: ConversationStateService) -> None:
        # row stored with user_id as string should still match int user_id
        service._state_path.write_text(
            _safe_json_line({"user_id": "9", "conversation_id": "c"}),
            encoding="utf-8",
        )
        state = service.get_state(user_id=9, conversation_id="c")
        assert state["user_id"] == 9

    def test_conversation_id_coerced_to_str(
        self, service: ConversationStateService
    ) -> None:
        service._state_path.write_text(
            _safe_json_line({"user_id": 1, "conversation_id": 123}),
            encoding="utf-8",
        )
        state = service.get_state(user_id=1, conversation_id="123")
        assert state["conversation_id"] == "123"

    def test_missing_user_id_in_row_treated_as_zero(
        self, service: ConversationStateService
    ) -> None:
        # row.get("user_id") returns None → int(None or 0) == 0
        service._state_path.write_text(
            _safe_json_line({"conversation_id": "c0"}),
            encoding="utf-8",
        )
        state = service.get_state(user_id=0, conversation_id="c0")
        assert state["user_id"] == 0


class TestGetAllStates:
    def test_filters_by_user_id(self, service: ConversationStateService) -> None:
        service._state_path.write_text(
            _safe_json_line({"user_id": 1, "conversation_id": "a"})
            + _safe_json_line({"user_id": 2, "conversation_id": "b"})
            + _safe_json_line({"user_id": 1, "conversation_id": "c"}),
            encoding="utf-8",
        )
        states = service.get_all_states(user_id=1)
        assert {s["conversation_id"] for s in states} == {"a", "c"}

    def test_returns_empty_for_unknown_user(
        self, service: ConversationStateService
    ) -> None:
        service._state_path.write_text(
            _safe_json_line({"user_id": 1, "conversation_id": "a"}),
            encoding="utf-8",
        )
        assert service.get_all_states(user_id=99) == []


class TestTogglePinned:
    def test_toggle_from_false_to_true(
        self, service: ConversationStateService
    ) -> None:
        service._state_path.write_text(
            _safe_json_line(
                {
                    "user_id": 1,
                    "conversation_id": "c",
                    "is_pinned": False,
                    "is_hidden": False,
                    "is_followed": True,
                    "unread_count": 0,
                }
            ),
            encoding="utf-8",
        )
        out = service.toggle_pinned(user_id=1, conversation_id="c")
        assert out["is_pinned"] is True

    def test_toggle_from_true_to_false(
        self, service: ConversationStateService
    ) -> None:
        service._state_path.write_text(
            _safe_json_line(
                {
                    "user_id": 1,
                    "conversation_id": "c",
                    "is_pinned": True,
                }
            ),
            encoding="utf-8",
        )
        out = service.toggle_pinned(user_id=1, conversation_id="c")
        assert out["is_pinned"] is False

    def test_toggle_creates_row_when_missing(
        self, service: ConversationStateService
    ) -> None:
        out = service.toggle_pinned(user_id=2, conversation_id="new")
        assert out["is_pinned"] is True  # default False → toggled to True


class TestMarkUnread:
    def test_increment_from_zero(self, service: ConversationStateService) -> None:
        service._state_path.write_text(
            _safe_json_line({"user_id": 1, "conversation_id": "c", "unread_count": 0}),
            encoding="utf-8",
        )
        out = service.mark_unread(user_id=1, conversation_id="c")
        assert out["unread_count"] == 1

    def test_increment_from_positive(self, service: ConversationStateService) -> None:
        service._state_path.write_text(
            _safe_json_line({"user_id": 1, "conversation_id": "c", "unread_count": 5}),
            encoding="utf-8",
        )
        out = service.mark_unread(user_id=1, conversation_id="c")
        assert out["unread_count"] == 6

    def test_missing_unread_count_treated_as_zero(
        self, service: ConversationStateService
    ) -> None:
        service._state_path.write_text(
            _safe_json_line({"user_id": 1, "conversation_id": "c"}),
            encoding="utf-8",
        )
        out = service.mark_unread(user_id=1, conversation_id="c")
        assert out["unread_count"] == 1

    def test_creates_row_when_missing(
        self, service: ConversationStateService
    ) -> None:
        out = service.mark_unread(user_id=3, conversation_id="new")
        assert out["unread_count"] == 1


class TestMarkRead:
    def test_resets_to_zero(self, service: ConversationStateService) -> None:
        service._state_path.write_text(
            _safe_json_line({"user_id": 1, "conversation_id": "c", "unread_count": 7}),
            encoding="utf-8",
        )
        out = service.mark_read(user_id=1, conversation_id="c")
        assert out["unread_count"] == 0

    def test_creates_row_when_missing(
        self, service: ConversationStateService
    ) -> None:
        out = service.mark_read(user_id=4, conversation_id="new")
        assert out["unread_count"] == 0


class TestToggleFollowed:
    def test_toggle_from_true_to_false(
        self, service: ConversationStateService
    ) -> None:
        service._state_path.write_text(
            _safe_json_line(
                {"user_id": 1, "conversation_id": "c", "is_followed": True}
            ),
            encoding="utf-8",
        )
        out = service.toggle_followed(user_id=1, conversation_id="c")
        assert out["is_followed"] is False

    def test_toggle_from_false_to_true(
        self, service: ConversationStateService
    ) -> None:
        service._state_path.write_text(
            _safe_json_line(
                {"user_id": 1, "conversation_id": "c", "is_followed": False}
            ),
            encoding="utf-8",
        )
        out = service.toggle_followed(user_id=1, conversation_id="c")
        assert out["is_followed"] is True

    def test_toggle_missing_field_defaults_true_then_false(
        self, service: ConversationStateService
    ) -> None:
        # row.get("is_followed", True) → True → toggled to False
        service._state_path.write_text(
            _safe_json_line({"user_id": 1, "conversation_id": "c"}),
            encoding="utf-8",
        )
        out = service.toggle_followed(user_id=1, conversation_id="c")
        assert out["is_followed"] is False


class TestToggleHidden:
    def test_toggle_from_false_to_true(
        self, service: ConversationStateService
    ) -> None:
        service._state_path.write_text(
            _safe_json_line(
                {"user_id": 1, "conversation_id": "c", "is_hidden": False}
            ),
            encoding="utf-8",
        )
        out = service.toggle_hidden(user_id=1, conversation_id="c")
        assert out["is_hidden"] is True

    def test_toggle_from_true_to_false(
        self, service: ConversationStateService
    ) -> None:
        service._state_path.write_text(
            _safe_json_line(
                {"user_id": 1, "conversation_id": "c", "is_hidden": True}
            ),
            encoding="utf-8",
        )
        out = service.toggle_hidden(user_id=1, conversation_id="c")
        assert out["is_hidden"] is False

    def test_creates_row_when_missing(
        self, service: ConversationStateService
    ) -> None:
        out = service.toggle_hidden(user_id=5, conversation_id="new")
        assert out["is_hidden"] is True  # default False → toggled True


class TestDelete:
    def test_delete_existing_row(self, service: ConversationStateService) -> None:
        service._state_path.write_text(
            _safe_json_line({"user_id": 1, "conversation_id": "c1"})
            + _safe_json_line({"user_id": 1, "conversation_id": "c2"}),
            encoding="utf-8",
        )
        result = service.delete(user_id=1, conversation_id="c1")
        assert result == {"deleted": True, "conversation_id": "c1"}
        # only c2 remains
        rows = service._read_all()
        assert len(rows) == 1
        assert rows[0]["conversation_id"] == "c2"

    def test_delete_missing_row_returns_not_deleted(
        self, service: ConversationStateService
    ) -> None:
        service._state_path.write_text(
            _safe_json_line({"user_id": 1, "conversation_id": "c1"}),
            encoding="utf-8",
        )
        result = service.delete(user_id=1, conversation_id="missing")
        assert result == {"deleted": False, "conversation_id": "missing"}

    def test_delete_with_string_user_id_matches_int(
        self, service: ConversationStateService
    ) -> None:
        service._state_path.write_text(
            _safe_json_line({"user_id": "1", "conversation_id": "c1"}),
            encoding="utf-8",
        )
        result = service.delete(user_id=1, conversation_id="c1")
        assert result["deleted"] is True


class TestPublic:
    def test_full_row(self) -> None:
        row = {
            "user_id": 1,
            "conversation_id": "c",
            "is_pinned": True,
            "is_hidden": True,
            "is_followed": False,
            "unread_count": 5,
        }
        out = ConversationStateService._public(row)
        assert out == {
            "user_id": 1,
            "conversation_id": "c",
            "is_pinned": True,
            "is_hidden": True,
            "is_followed": False,
            "unread_count": 5,
        }

    def test_missing_fields_use_defaults(self) -> None:
        out = ConversationStateService._public({})
        assert out["user_id"] == 0
        assert out["conversation_id"] == ""
        assert out["is_pinned"] is False
        assert out["is_hidden"] is False
        assert out["is_followed"] is True  # default True
        assert out["unread_count"] == 0

    def test_user_id_string_coerced(self) -> None:
        out = ConversationStateService._public({"user_id": "42"})
        assert out["user_id"] == 42

    def test_unread_count_none_treated_as_zero(self) -> None:
        out = ConversationStateService._public({"unread_count": None})
        assert out["unread_count"] == 0


class TestUpdate:
    def test_update_existing_row(self, service: ConversationStateService) -> None:
        service._state_path.write_text(
            _safe_json_line({"user_id": 1, "conversation_id": "c", "is_pinned": False}),
            encoding="utf-8",
        )
        out = service._update(1, "c", lambda r: dict(r, is_pinned=True))
        assert out["is_pinned"] is True

    def test_update_creates_new_row_when_target_none(
        self, service: ConversationStateService
    ) -> None:
        out = service._update(9, "new", lambda r: dict(r, is_pinned=True))
        assert out["is_pinned"] is True
        # persisted
        rows = service._read_all()
        assert any(r["conversation_id"] == "new" for r in rows)


class TestConstructor:
    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        svc = ConversationStateService(storage_root=nested)
        assert nested.exists()
        assert svc._state_path.parent == nested

    def test_default_storage_root(self) -> None:
        # When storage_root is None, uses get_app_data_dir()
        with patch(
            "app.application.conversation_state_service.get_app_data_dir",
            return_value="/tmp/test_conv_state_default",
        ):
            svc = ConversationStateService(storage_root=None)
            assert "conversation_state.jsonl" in str(svc._state_path)
