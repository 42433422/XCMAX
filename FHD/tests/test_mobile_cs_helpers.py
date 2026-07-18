"""Tests for app.fastapi_routes.mobile_extensions.cs_helpers — branch coverage ramp.

覆盖所有纯函数的关键分支：
- _safe_user_id: getattr None / 异常 / __dict__ 有值 / sqlalchemy inspect / 异常返回 0
- _safe_user_text: 正常 / AttributeError / 默认
- _mobile_cs_source_id: uid=0 / uid>0
- _mobile_cs_source_name: display_name / username / 默认
- _coerce_user_cs_reply: 复杂分支（data dict / error / items list / first dict / first str / summary / 顶层 error）
- _strip_markdown_json_fence: 无 fence / 仅开头 / 开头+结尾 / 中间
- _coerce_cs_reply_body: 空 / 无 fence / json dict / json 非 dict / 非 json
- _service_request_to_cs_messages: 各分支（extra_data dict / 非法 json / response / ai_reply / timestamps）
"""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes.mobile_extensions.cs_helpers import (
    _coerce_cs_reply_body,
    _coerce_user_cs_reply,
    _mobile_cs_source_id,
    _mobile_cs_source_name,
    _safe_user_id,
    _safe_user_text,
    _service_request_to_cs_messages,
    _strip_markdown_json_fence,
)

# ---------------------------------------------------------------------------
# _safe_user_id
# ---------------------------------------------------------------------------


class TestSafeUserId:
    def test_returns_int_when_id_is_int(self):
        user = SimpleNamespace(id=42)
        assert _safe_user_id(user) == 42

    def test_returns_zero_when_id_is_none(self):
        user = SimpleNamespace(id=None)
        assert _safe_user_id(user) == 0

    def test_returns_zero_when_id_is_zero(self):
        user = SimpleNamespace(id=0)
        assert _safe_user_id(user) == 0

    def test_converts_string_id_to_int(self):
        user = SimpleNamespace(id="123")
        assert _safe_user_id(user) == 123

    def test_returns_zero_when_id_is_non_numeric_string(self):
        # int("abc") raises ValueError → 回退到 __dict__.id
        # __dict__.id 也是 "abc" → int("abc") 抛 ValueError → 回退到 sqlalchemy inspect
        # sqlalchemy inspect 抛异常（SimpleNamespace 不是 ORM 对象）→ 返回 0
        user = SimpleNamespace(id="abc")
        assert _safe_user_id(user) == 0

    def test_returns_zero_when_no_id_attr(self):
        # 没有 id 属性 → getattr 返回 None → int(None or 0) = 0
        user = SimpleNamespace()
        assert _safe_user_id(user) == 0

    def test_falls_back_to_dict_id_when_int_raises(self):
        # 让 getattr 返回 int 不能处理的对象 → TypeError → 回退到 __dict__.id
        bad_obj = object()  # int(object()) raises TypeError

        class CustomUser:
            @property
            def id(self):  # data descriptor 优先于 instance __dict__
                return bad_obj

        user = CustomUser()
        user.__dict__["id"] = 99  # instance __dict__，与 property 分离
        # getattr(user, "id", None) → property getter → bad_obj
        # int(bad_obj or 0) → int(bad_obj) → TypeError → except
        # getattr(user, "__dict__", {}).get("id") → 99 → int(99) = 99
        assert _safe_user_id(user) == 99

    def test_uses_sqlalchemy_identity_when_dict_empty(self):
        # 没有 __dict__.id，但 sqlalchemy inspect 返回 identity
        user = SimpleNamespace(id=None)
        # SimpleNamespace 没有 __dict__.id，回退到 sqlalchemy inspect
        # sqlalchemy inspect 对非 ORM 对象抛异常 → 返回 0
        assert _safe_user_id(user) == 0

    def test_sqlalchemy_identity_with_valid_identity(self):
        # 模拟 sqlalchemy inspect 返回有 identity 的对象
        user = SimpleNamespace(id="not_numeric")  # 让 int() 失败
        mock_inspect_result = MagicMock()
        mock_inspect_result.identity = (55,)
        with patch("sqlalchemy.inspect", return_value=mock_inspect_result):
            # __dict__.id 也是 "not_numeric" → int 失败
            # 回退到 sqlalchemy inspect → identity=(55,) → int(55) = 55
            result = _safe_user_id(user)
        # 注意：SimpleNamespace(id="not_numeric") 的 __dict__ = {"id": "not_numeric"}
        # int("not_numeric") 抛 ValueError → 回退到 sqlalchemy
        assert result == 55

    def test_sqlalchemy_identity_empty_returns_zero(self):
        user = SimpleNamespace(id="not_numeric")
        mock_inspect_result = MagicMock()
        mock_inspect_result.identity = ()
        with patch("sqlalchemy.inspect", return_value=mock_inspect_result):
            result = _safe_user_id(user)
        assert result == 0


# ---------------------------------------------------------------------------
# _safe_user_text
# ---------------------------------------------------------------------------


class TestSafeUserText:
    def test_returns_value_when_present(self):
        user = SimpleNamespace(display_name="Alice")
        assert _safe_user_text(user, "display_name") == "Alice"

    def test_returns_empty_when_attr_is_none(self):
        user = SimpleNamespace(display_name=None)
        assert _safe_user_text(user, "display_name") == ""

    def test_returns_empty_when_attr_is_empty_string(self):
        user = SimpleNamespace(display_name="")
        assert _safe_user_text(user, "display_name") == ""

    def test_strips_whitespace(self):
        user = SimpleNamespace(display_name="  Alice  ")
        assert _safe_user_text(user, "display_name") == "Alice"

    def test_returns_empty_when_attr_missing(self):
        user = SimpleNamespace()
        # getattr(user, "missing", "") 返回 "" → str("" or "").strip() = ""
        assert _safe_user_text(user, "missing") == ""

    def test_falls_back_to_dict_on_attribute_error(self):
        class BadAttr:
            def __getattr__(self, name):
                raise AttributeError("no attr")

            def __init__(self):
                self.__dict__["display_name"] = "FromDict"

        user = BadAttr()
        # getattr 抛 AttributeError → 回退到 __dict__.get("display_name")
        assert _safe_user_text(user, "display_name") == "FromDict"


# ---------------------------------------------------------------------------
# _mobile_cs_source_id
# ---------------------------------------------------------------------------


class TestMobileCsSourceId:
    def test_returns_mobile_prefix_with_uid(self):
        user = SimpleNamespace(id=42)
        assert _mobile_cs_source_id(user) == "mobile:42"

    def test_returns_anonymous_when_uid_zero(self):
        user = SimpleNamespace(id=0)
        assert _mobile_cs_source_id(user) == "mobile:anonymous"

    def test_returns_anonymous_when_uid_none(self):
        user = SimpleNamespace(id=None)
        assert _mobile_cs_source_id(user) == "mobile:anonymous"


# ---------------------------------------------------------------------------
# _mobile_cs_source_name
# ---------------------------------------------------------------------------


class TestMobileCsSourceName:
    def test_uses_display_name_when_present(self):
        user = SimpleNamespace(id=1, display_name="Alice", username="alice")
        assert _mobile_cs_source_name(user) == "手机端 Alice"

    def test_falls_back_to_username_when_display_empty(self):
        user = SimpleNamespace(id=1, display_name="", username="bob")
        assert _mobile_cs_source_name(user) == "手机端 bob"

    def test_falls_back_to_username_when_display_none(self):
        user = SimpleNamespace(id=1, display_name=None, username="bob")
        assert _mobile_cs_source_name(user) == "手机端 bob"

    def test_uses_default_when_both_empty(self):
        user = SimpleNamespace(id=1, display_name="", username="")
        assert _mobile_cs_source_name(user) == "手机端 移动端用户"

    def test_uses_default_when_both_none(self):
        user = SimpleNamespace(id=1, display_name=None, username=None)
        assert _mobile_cs_source_name(user) == "手机端 移动端用户"


# ---------------------------------------------------------------------------
# _coerce_user_cs_reply
# ---------------------------------------------------------------------------


class TestCoerceUserCsReply:
    def test_returns_fallback_when_result_is_none(self):
        assert _coerce_user_cs_reply(None, "fallback") == "fallback"

    def test_returns_fallback_when_result_not_dict(self):
        assert _coerce_user_cs_reply("string", "fallback") == "fallback"

    def test_returns_fallback_when_data_not_dict(self):
        result = {"data": "not a dict"}
        assert _coerce_user_cs_reply(result, "fallback") == "fallback"

    def test_returns_fallback_when_data_ok_is_false(self):
        result = {"data": {"ok": False, "error": "some error"}}
        assert _coerce_user_cs_reply(result, "fallback") == "fallback"

    def test_returns_fallback_when_data_has_error(self):
        result = {"data": {"error": "some error"}}
        assert _coerce_user_cs_reply(result, "fallback") == "fallback"

    def test_returns_fallback_when_data_empty(self):
        result = {"data": {}}
        assert _coerce_user_cs_reply(result, "fallback") == "fallback"

    def test_extracts_message_text_from_items_dict(self):
        result = {"data": {"items": [{"message_text": "hello"}]}}
        assert _coerce_user_cs_reply(result, "fallback") == "hello"

    def test_extracts_reply_from_items_dict(self):
        result = {"data": {"items": [{"reply": "world"}]}}
        assert _coerce_user_cs_reply(result, "fallback") == "world"

    def test_extracts_answer_from_items_dict(self):
        result = {"data": {"items": [{"answer": "ans"}]}}
        assert _coerce_user_cs_reply(result, "fallback") == "ans"

    def test_extracts_summary_from_items_dict(self):
        result = {"data": {"items": [{"summary": "sum"}]}}
        assert _coerce_user_cs_reply(result, "fallback") == "sum"

    def test_extracts_first_string_from_items(self):
        result = {"data": {"items": ["direct string"]}}
        assert _coerce_user_cs_reply(result, "fallback") == "direct string"

    def test_skips_empty_string_in_items(self):
        result = {"data": {"items": [{"message_text": "", "reply": "real reply"}]}}
        assert _coerce_user_cs_reply(result, "fallback") == "real reply"

    def test_skips_whitespace_only_string_in_items(self):
        result = {"data": {"items": [{"message_text": "   ", "reply": "real"}]}}
        assert _coerce_user_cs_reply(result, "fallback") == "real"

    def test_skips_empty_string_in_items_first(self):
        result = {"data": {"items": ["  ", "second string"]}}
        # 第一个 str 是 whitespace → 不 return，但循环结束没找到
        # 然后检查 summary → 无 → 返回 fallback
        assert _coerce_user_cs_reply(result, "fallback") == "fallback"

    def test_returns_summary_when_no_items(self):
        result = {"data": {"summary": "data summary"}}
        assert _coerce_user_cs_reply(result, "fallback") == "data summary"

    def test_returns_summary_when_items_empty(self):
        result = {"data": {"items": [], "summary": "data summary"}}
        assert _coerce_user_cs_reply(result, "fallback") == "data summary"

    def test_returns_fallback_when_items_not_list(self):
        result = {"data": {"items": "not a list"}}
        assert _coerce_user_cs_reply(result, "fallback") == "fallback"

    def test_returns_fallback_when_top_level_error(self):
        result = {"error": "top level error"}
        assert _coerce_user_cs_reply(result, "fallback") == "fallback"

    def test_returns_fallback_when_no_data_no_error(self):
        result = {"other": "value"}
        assert _coerce_user_cs_reply(result, "fallback") == "fallback"

    def test_skips_non_dict_non_str_first_item(self):
        result = {"data": {"items": [123]}}
        assert _coerce_user_cs_reply(result, "fallback") == "fallback"

    def test_returns_message_text_priority_over_reply(self):
        result = {"data": {"items": [{"message_text": "msg", "reply": "rep"}]}}
        assert _coerce_user_cs_reply(result, "fallback") == "msg"


# ---------------------------------------------------------------------------
# _strip_markdown_json_fence
# ---------------------------------------------------------------------------


class TestStripMarkdownJsonFence:
    def test_returns_text_when_no_fence(self):
        assert _strip_markdown_json_fence("plain text") == "plain text"

    def test_strips_single_line_starting_with_fence(self):
        # 单行以 ``` 开头 → 第一行被剥离 → 剩空 → 返回 ""
        assert _strip_markdown_json_fence("```not starting") == ""

    def test_strips_opening_fence_only(self):
        text = '```json\n{"key": "value"}'
        result = _strip_markdown_json_fence(text)
        assert result == '{"key": "value"}'

    def test_strips_opening_and_closing_fence(self):
        text = '```json\n{"key": "value"}\n```'
        result = _strip_markdown_json_fence(text)
        assert result == '{"key": "value"}'

    def test_strips_plain_codefence(self):
        text = "```\ncode here\n```"
        result = _strip_markdown_json_fence(text)
        assert result == "code here"

    def test_handles_empty_text(self):
        assert _strip_markdown_json_fence("") == ""

    def test_preserves_inner_codefence_markers(self):
        # text 以 ``` 开头 → 处理
        # 第一行 ```python 被剥离
        # 最后一行不是 ``` → 保留
        text = "```python\n```\n```"
        result = _strip_markdown_json_fence(text)
        # lines = ["```python", "```", "```"]
        # 第一行 starts with ``` → lines = ["```", "```"]
        # 最后一行 == ``` → lines = ["```"]
        # join → "```"
        assert result == "```"


# ---------------------------------------------------------------------------
# _coerce_cs_reply_body
# ---------------------------------------------------------------------------


class TestCoerceCsReplyBody:
    def test_returns_empty_when_value_is_none(self):
        assert _coerce_cs_reply_body(None) == ""

    def test_returns_empty_when_value_is_empty_string(self):
        assert _coerce_cs_reply_body("") == ""

    def test_returns_empty_when_value_is_whitespace(self):
        assert _coerce_cs_reply_body("   ") == ""

    def test_returns_text_when_not_json(self):
        assert _coerce_cs_reply_body("plain text") == "plain text"

    def test_returns_text_when_json_invalid(self):
        assert _coerce_cs_reply_body("{not valid json}") == "{not valid json}"

    def test_extracts_message_text_from_json_dict(self):
        assert _coerce_cs_reply_body('{"message_text": "hello"}') == "hello"

    def test_extracts_reply_from_json_dict(self):
        assert _coerce_cs_reply_body('{"reply": "world"}') == "world"

    def test_extracts_answer_from_json_dict(self):
        assert _coerce_cs_reply_body('{"answer": "ans"}') == "ans"

    def test_extracts_summary_from_json_dict(self):
        assert _coerce_cs_reply_body('{"summary": "sum"}') == "sum"

    def test_extracts_body_from_json_dict(self):
        assert _coerce_cs_reply_body('{"body": "body text"}') == "body text"

    def test_returns_text_when_json_not_dict(self):
        # json 是 list → 不是 dict → 返回原 text
        assert _coerce_cs_reply_body("[1, 2, 3]") == "[1, 2, 3]"

    def test_returns_text_when_json_dict_no_known_keys(self):
        assert _coerce_cs_reply_body('{"other": "value"}') == '{"other": "value"}'

    def test_returns_text_when_known_keys_empty(self):
        assert _coerce_cs_reply_body('{"message_text": ""}') == '{"message_text": ""}'

    def test_strips_markdown_fence_then_parses_json(self):
        text = '```json\n{"message_text": "fenced"}\n```'
        assert _coerce_cs_reply_body(text) == "fenced"

    def test_message_text_priority_over_reply(self):
        assert _coerce_cs_reply_body('{"message_text": "msg", "reply": "rep"}') == "msg"

    def test_converts_non_string_to_string(self):
        # 0 是 falsy → 0 or "" = "" → str("") → "" → 返回 ""
        assert _coerce_cs_reply_body(0) == ""

    def test_converts_int_to_string(self):
        assert _coerce_cs_reply_body(123) == "123"


# ---------------------------------------------------------------------------
# _service_request_to_cs_messages
# ---------------------------------------------------------------------------


class TestServiceRequestToCsMessages:
    def test_prefers_manual_response_over_ai_reply(self):
        row = SimpleNamespace(
            id=7,
            title="客户原话",
            description="客户原话",
            response="人工回复",
            extra_data=json.dumps({"ai_reply": "AI 自动回复"}, ensure_ascii=False),
            created_at=None,
            updated_at=None,
        )
        messages = _service_request_to_cs_messages(row)
        assert messages == [
            {
                "message_id": "sr_7_user",
                "sender": "user",
                "body": "客户原话",
                "timestamp": "",
                "msg_type": "text",
            },
            {
                "message_id": "sr_7_cs",
                "sender": "cs",
                "body": "人工回复",
                "timestamp": "",
                "msg_type": "text",
            },
        ]

    def test_extracts_message_text_from_ai_json(self):
        row = SimpleNamespace(
            id=8,
            title="客户原话",
            description="客户原话",
            response="",
            extra_data=json.dumps(
                {"ai_reply": '```json\n{"message_text":"清洗后的回复"}\n```'},
                ensure_ascii=False,
            ),
            created_at=None,
            updated_at=None,
        )
        messages = _service_request_to_cs_messages(row)
        assert messages[1]["body"] == "清洗后的回复"

    def test_returns_only_user_message_when_no_response(self):
        row = SimpleNamespace(
            id=9,
            title="title",
            description="desc",
            response="",
            extra_data=None,
            created_at=None,
            updated_at=None,
        )
        messages = _service_request_to_cs_messages(row)
        assert len(messages) == 1
        assert messages[0]["sender"] == "user"

    def test_returns_only_user_message_when_response_whitespace(self):
        row = SimpleNamespace(
            id=10,
            title="title",
            description="desc",
            response="   ",
            extra_data=None,
            created_at=None,
            updated_at=None,
        )
        messages = _service_request_to_cs_messages(row)
        assert len(messages) == 1

    def test_falls_back_to_title_when_description_empty(self):
        row = SimpleNamespace(
            id=11,
            title="仅标题",
            description="",
            response="",
            extra_data=None,
            created_at=None,
            updated_at=None,
        )
        messages = _service_request_to_cs_messages(row)
        assert messages[0]["body"] == "仅标题"

    def test_falls_back_to_empty_when_both_title_and_description_empty(self):
        row = SimpleNamespace(
            id=12,
            title="",
            description="",
            response="",
            extra_data=None,
            created_at=None,
            updated_at=None,
        )
        messages = _service_request_to_cs_messages(row)
        assert messages[0]["body"] == ""

    def test_includes_iso_timestamps_when_present(self):
        ts_created = datetime(2026, 1, 1, 12, 0, 0)
        ts_updated = datetime(2026, 1, 2, 12, 0, 0)
        row = SimpleNamespace(
            id=13,
            title="t",
            description="d",
            response="回复",
            extra_data=None,
            created_at=ts_created,
            updated_at=ts_updated,
        )
        messages = _service_request_to_cs_messages(row)
        assert messages[0]["timestamp"] == ts_created.isoformat()
        assert messages[1]["timestamp"] == ts_updated.isoformat()

    def test_uses_created_when_updated_none(self):
        ts_created = datetime(2026, 1, 1, 12, 0, 0)
        row = SimpleNamespace(
            id=14,
            title="t",
            description="d",
            response="回复",
            extra_data=None,
            created_at=ts_created,
            updated_at=None,
        )
        messages = _service_request_to_cs_messages(row)
        # updated = created.isoformat() when updated_at is None
        assert messages[1]["timestamp"] == ts_created.isoformat()

    def test_extra_data_invalid_json_falls_back_to_empty(self):
        row = SimpleNamespace(
            id=15,
            title="t",
            description="d",
            response="回复",
            extra_data="not valid json",
            created_at=None,
            updated_at=None,
        )
        messages = _service_request_to_cs_messages(row)
        # extra_data 非法 json → extra={} → ai_reply=None → _coerce_cs_reply_body(None)=""
        # response="回复" → reply="回复"
        assert messages[1]["body"] == "回复"

    def test_extra_data_not_dict_falls_back_to_empty(self):
        row = SimpleNamespace(
            id=16,
            title="t",
            description="d",
            response="回复",
            extra_data="[1, 2, 3]",  # json list, not dict
            created_at=None,
            updated_at=None,
        )
        messages = _service_request_to_cs_messages(row)
        # extra_data 是 list → 不是 dict → extra={} → ai_reply=None
        # response="回复" → reply="回复"
        assert messages[1]["body"] == "回复"

    def test_uses_ai_reply_when_response_empty(self):
        row = SimpleNamespace(
            id=17,
            title="t",
            description="d",
            response="",
            extra_data=json.dumps({"ai_reply": "AI 回复"}, ensure_ascii=False),
            created_at=None,
            updated_at=None,
        )
        messages = _service_request_to_cs_messages(row)
        assert messages[1]["body"] == "AI 回复"

    def test_ai_reply_as_dict_with_message_text(self):
        row = SimpleNamespace(
            id=18,
            title="t",
            description="d",
            response="",
            extra_data=json.dumps(
                {"ai_reply": '{"message_text": "from dict"}'}, ensure_ascii=False
            ),
            created_at=None,
            updated_at=None,
        )
        messages = _service_request_to_cs_messages(row)
        assert messages[1]["body"] == "from dict"

    def test_extra_data_empty_string(self):
        row = SimpleNamespace(
            id=19,
            title="t",
            description="d",
            response="回复",
            extra_data="",
            created_at=None,
            updated_at=None,
        )
        messages = _service_request_to_cs_messages(row)
        # extra_data="" → falsy → extra={} → ai_reply=None → response="回复"
        assert messages[1]["body"] == "回复"

    def test_extra_data_none_with_no_response_returns_only_user(self):
        row = SimpleNamespace(
            id=20,
            title="t",
            description="d",
            response="",
            extra_data=None,
            created_at=None,
            updated_at=None,
        )
        messages = _service_request_to_cs_messages(row)
        assert len(messages) == 1
