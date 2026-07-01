"""Behavior tests for app.fastapi_routes.mobile_extensions.cs_helpers.

Targets previously-uncovered lines: the _safe_user_id fallback branches
(__dict__ / sqlalchemy inspect), _safe_user_text except path, the
_coerce_user_cs_reply item/summary/error branches, and the full
_service_request_to_cs_messages builder.
"""

from __future__ import annotations

import json
import types
from unittest.mock import patch

from app.fastapi_routes.mobile_extensions.cs_helpers import (
    _coerce_user_cs_reply,
    _mobile_cs_source_id,
    _mobile_cs_source_name,
    _safe_user_id,
    _safe_user_text,
    _service_request_to_cs_messages,
)

# ============================== _safe_user_id ==============================


class TestSafeUserId:
    def test_plain_int_id(self):
        user = types.SimpleNamespace(id=42)
        assert _safe_user_id(user) == 42

    def test_numeric_string_id(self):
        user = types.SimpleNamespace(id="17")
        assert _safe_user_id(user) == 17

    def test_none_id_returns_zero(self):
        user = types.SimpleNamespace(id=None)
        assert _safe_user_id(user) == 0

    def test_getattr_raises_then_dict_fallback(self):
        """getattr(user, 'id') raises non-AttributeError -> except -> __dict__ fallback.

        getattr(..., None) only swallows AttributeError; a TypeError from the
        property propagates and is caught by the except (line 16), then the
        __dict__ fallback (18-21) supplies the id.
        """

        class Boom:
            __dict__ = {"id": "99"}

            @property
            def id(self):  # noqa: A003
                raise TypeError("boom")

        assert _safe_user_id(Boom()) == 99

    def test_dict_fallback_non_numeric_then_inspect(self):
        """__dict__ id present but non-numeric -> inner except pass -> inspect path."""

        class Boom:
            __dict__ = {"id": "not-a-number"}

            @property
            def id(self):  # noqa: A003
                raise TypeError("boom")

        obj = Boom()
        # __dict__["id"] is truthy but int() fails (lines 19-23), then sqlalchemy
        # inspect path runs (24-28). Force inspect to yield an identity.
        fake_state = types.SimpleNamespace(identity=(7,))
        with patch("sqlalchemy.inspect", return_value=fake_state):
            assert _safe_user_id(obj) == 7

    def test_inspect_identity_empty_returns_zero(self):
        """getattr raises, no usable __dict__ id, inspect identity empty -> 0 (line 28)."""

        class Boom:
            __dict__ = {}

            @property
            def id(self):  # noqa: A003
                raise TypeError("boom")

        fake_state = types.SimpleNamespace(identity=())
        with patch("sqlalchemy.inspect", return_value=fake_state):
            assert _safe_user_id(Boom()) == 0

    def test_inspect_raises_returns_zero(self):
        """Final except clause (lines 29-30) when sqlalchemy.inspect blows up."""

        class Boom:
            __dict__ = {}

            @property
            def id(self):  # noqa: A003
                raise TypeError("boom")

        with patch("sqlalchemy.inspect", side_effect=RuntimeError("no mapper")):
            assert _safe_user_id(Boom()) == 0


# ============================= _safe_user_text =============================


class TestSafeUserText:
    def test_plain_attr(self):
        user = types.SimpleNamespace(username="  alice  ")
        assert _safe_user_text(user, "username") == "alice"

    def test_missing_attr_returns_empty(self):
        user = types.SimpleNamespace()
        assert _safe_user_text(user, "username") == ""

    def test_none_value_returns_empty(self):
        user = types.SimpleNamespace(display_name=None)
        assert _safe_user_text(user, "display_name") == ""

    def test_getattr_raises_then_dict_fallback(self):
        """getattr raises non-AttributeError -> except -> __dict__ fallback (36-37)."""

        class Boom:
            __dict__ = {"username": "  bob  "}

            @property
            def username(self):
                raise TypeError("boom")

        assert _safe_user_text(Boom(), "username") == "bob"

    def test_getattr_raises_dict_missing_key(self):
        class Boom:
            __dict__ = {}

            @property
            def username(self):
                raise TypeError("boom")

        assert _safe_user_text(Boom(), "username") == ""


# ===================== source id / name (integration) =====================


class TestSourceHelpers:
    def test_source_id_with_user(self):
        user = types.SimpleNamespace(id=5)
        assert _mobile_cs_source_id(user) == "mobile:5"

    def test_source_id_anonymous(self):
        user = types.SimpleNamespace(id=0)
        assert _mobile_cs_source_id(user) == "mobile:anonymous"

    def test_source_name_prefers_display_name(self):
        user = types.SimpleNamespace(display_name="小明", username="ming")
        assert _mobile_cs_source_name(user) == "手机端 小明"

    def test_source_name_falls_back_to_username(self):
        user = types.SimpleNamespace(display_name="", username="ming")
        assert _mobile_cs_source_name(user) == "手机端 ming"

    def test_source_name_default(self):
        user = types.SimpleNamespace(display_name="", username="")
        assert _mobile_cs_source_name(user) == "手机端 移动端用户"


# ========================= _coerce_user_cs_reply ==========================


class TestCoerceUserCsReply:
    def test_non_dict_result_returns_fallback(self):
        assert _coerce_user_cs_reply("not a dict", "FB") == "FB"

    def test_ok_false_returns_fallback(self):
        result = {"data": {"ok": False}}
        assert _coerce_user_cs_reply(result, "FB") == "FB"

    def test_error_string_returns_fallback(self):
        result = {"data": {"error": "boom"}}
        assert _coerce_user_cs_reply(result, "FB") == "FB"

    def test_items_dict_first_message_text(self):
        result = {"data": {"items": [{"message_text": "hi there"}]}}
        assert _coerce_user_cs_reply(result, "FB") == "hi there"

    def test_items_dict_uses_reply_key_order(self):
        # message_text empty -> falls through to 'reply'
        result = {"data": {"items": [{"message_text": "  ", "reply": "the reply"}]}}
        assert _coerce_user_cs_reply(result, "FB") == "the reply"

    def test_items_dict_answer_then_summary_key(self):
        result = {"data": {"items": [{"answer": "ans"}]}}
        assert _coerce_user_cs_reply(result, "FB") == "ans"

    def test_items_first_is_string(self):
        result = {"data": {"items": ["  plain string  "]}}
        assert _coerce_user_cs_reply(result, "FB") == "plain string"

    def test_items_dict_all_blank_falls_to_summary(self):
        result = {"data": {"items": [{"message_text": ""}], "summary": "sum"}}
        assert _coerce_user_cs_reply(result, "FB") == "sum"

    def test_empty_items_uses_summary(self):
        result = {"data": {"items": [], "summary": "from summary"}}
        assert _coerce_user_cs_reply(result, "FB") == "from summary"

    def test_data_present_no_items_no_summary_then_top_error(self):
        result = {"data": {"ok": True}, "error": "outer-fail"}
        assert _coerce_user_cs_reply(result, "FB") == "FB"

    def test_top_level_error_logged_returns_fallback(self):
        # data not a dict so item block skipped; top-level error present
        result = {"data": None, "error": "outer-fail"}
        assert _coerce_user_cs_reply(result, "FB") == "FB"

    def test_no_error_no_data_returns_fallback(self):
        assert _coerce_user_cs_reply({}, "FB") == "FB"

    def test_items_first_non_dict_non_str_falls_to_summary(self):
        result = {"data": {"items": [123], "summary": "S"}}
        assert _coerce_user_cs_reply(result, "FB") == "S"


# ==================== _service_request_to_cs_messages ====================


class _Row:
    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.created_at = kw.get("created_at")
        self.updated_at = kw.get("updated_at")
        self.description = kw.get("description")
        self.title = kw.get("title")
        self.extra_data = kw.get("extra_data")
        self.response = kw.get("response")


class _TS:
    def __init__(self, s):
        self._s = s

    def isoformat(self):
        return self._s


class TestServiceRequestToCsMessages:
    def test_basic_user_message_only(self):
        row = _Row(id=10, description="help me", title="ignored")
        msgs = _service_request_to_cs_messages(row)
        assert len(msgs) == 1
        assert msgs[0]["message_id"] == "sr_10_user"
        assert msgs[0]["sender"] == "user"
        assert msgs[0]["body"] == "help me"
        assert msgs[0]["timestamp"] == ""

    def test_description_falls_back_to_title(self):
        row = _Row(id=2, description=None, title="my title")
        msgs = _service_request_to_cs_messages(row)
        assert msgs[0]["body"] == "my title"

    def test_timestamps_from_created_updated(self):
        row = _Row(
            id=3,
            description="d",
            created_at=_TS("2024-01-01T00:00:00"),
            updated_at=_TS("2024-01-02T00:00:00"),
            response="a reply",
        )
        msgs = _service_request_to_cs_messages(row)
        assert msgs[0]["timestamp"] == "2024-01-01T00:00:00"
        assert len(msgs) == 2
        assert msgs[1]["timestamp"] == "2024-01-02T00:00:00"

    def test_updated_defaults_to_created_when_missing(self):
        row = _Row(
            id=4,
            description="d",
            created_at=_TS("2024-05-05T00:00:00"),
            updated_at=None,
            response="resp",
        )
        msgs = _service_request_to_cs_messages(row)
        # cs message reuses created timestamp since updated_at missing
        assert msgs[1]["timestamp"] == "2024-05-05T00:00:00"

    def test_cs_reply_from_response(self):
        row = _Row(id=5, description="d", response="agent answer")
        msgs = _service_request_to_cs_messages(row)
        assert len(msgs) == 2
        assert msgs[1]["message_id"] == "sr_5_cs"
        assert msgs[1]["sender"] == "cs"
        assert msgs[1]["body"] == "agent answer"
        assert msgs[1]["msg_type"] == "text"

    def test_cs_reply_prefers_extra_ai_reply(self):
        row = _Row(
            id=6,
            description="d",
            response="from response",
            extra_data=json.dumps({"ai_reply": "from extra"}),
        )
        msgs = _service_request_to_cs_messages(row)
        assert msgs[1]["body"] == "from extra"

    def test_extra_data_invalid_json_ignored(self):
        row = _Row(id=7, description="d", extra_data="{not valid json", response="resp")
        msgs = _service_request_to_cs_messages(row)
        # falls back to row.response since extra parse failed
        assert len(msgs) == 2
        assert msgs[1]["body"] == "resp"

    def test_extra_data_non_dict_json_ignored(self):
        row = _Row(id=8, description="d", extra_data=json.dumps([1, 2, 3]), response="resp")
        msgs = _service_request_to_cs_messages(row)
        assert msgs[1]["body"] == "resp"

    def test_no_reply_means_single_message(self):
        row = _Row(id=9, description="d", response="", extra_data=None)
        msgs = _service_request_to_cs_messages(row)
        assert len(msgs) == 1

    def test_extra_data_none_type_error_branch(self):
        # extra_data truthy but json.loads gets a type error path is covered by
        # invalid-json test; here ensure empty/falsey extra_data skips the block.
        row = _Row(id=11, description="d", response="r", extra_data="")
        msgs = _service_request_to_cs_messages(row)
        assert len(msgs) == 2
        assert msgs[1]["body"] == "r"
