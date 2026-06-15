"""Tests for app.fastapi_routes.domains.wechat.routes — pure helper functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes.domains.wechat.routes import (
    _secret_key,
    _wechat_message_text,
    _wechat_message_timestamp_seconds,
)


# ========================= _secret_key ===================================


class TestSecretKey:
    def test_with_env(self):
        with patch.dict("os.environ", {"SECRET_KEY": "mysecret"}):
            assert _secret_key() == "mysecret"

    def test_without_env(self):
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("SECRET_KEY", None)
            assert _secret_key() == ""


# ========================= _wechat_message_timestamp_seconds ==============


class TestWechatMessageTimestampSeconds:
    def test_int_timestamp_seconds(self):
        result = _wechat_message_timestamp_seconds({"timestamp": 1700000000})
        assert result == 1700000000.0

    def test_int_timestamp_milliseconds(self):
        result = _wechat_message_timestamp_seconds({"timestamp": 1700000000000})
        assert result == 1700000000.0

    def test_float_timestamp(self):
        result = _wechat_message_timestamp_seconds({"timestamp": 1700000000.5})
        assert result == 1700000000.5

    def test_iso_string(self):
        result = _wechat_message_timestamp_seconds({"timestamp": "2024-01-01T00:00:00+08:00"})
        assert result > 0

    def test_iso_string_with_z(self):
        result = _wechat_message_timestamp_seconds({"timestamp": "2024-01-01T00:00:00Z"})
        assert result > 0

    def test_msg_timestamp_key(self):
        result = _wechat_message_timestamp_seconds({"msg_timestamp": 1700000000})
        assert result == 1700000000.0

    def test_time_key(self):
        result = _wechat_message_timestamp_seconds({"time": 1700000000})
        assert result == 1700000000.0

    def test_no_timestamp(self):
        result = _wechat_message_timestamp_seconds({})
        assert result == 0.0

    def test_invalid_string(self):
        result = _wechat_message_timestamp_seconds({"timestamp": "not-a-date"})
        assert result == 0.0

    def test_empty_string(self):
        result = _wechat_message_timestamp_seconds({"timestamp": ""})
        assert result == 0.0


# ========================= _wechat_message_text ==========================


class TestWechatMessageText:
    def test_content_key(self):
        result = _wechat_message_text({"content": "hello"})
        assert result == "hello"

    def test_message_key(self):
        result = _wechat_message_text({"message": "world"})
        assert result == "world"

    def test_text_key(self):
        result = _wechat_message_text({"text": "test"})
        assert result == "test"

    def test_raw_text_key(self):
        result = _wechat_message_text({"raw_text": "raw"})
        assert result == "raw"

    def test_body_key(self):
        result = _wechat_message_text({"body": "body text"})
        assert result == "body text"

    def test_empty_value(self):
        result = _wechat_message_text({"content": ""})
        assert result == ""

    def test_whitespace_only(self):
        result = _wechat_message_text({"content": "   "})
        assert result == ""

    def test_none_value(self):
        result = _wechat_message_text({"content": None, "message": None})
        assert result == ""

    def test_no_keys(self):
        result = _wechat_message_text({})
        assert result == ""

    def test_stripped(self):
        result = _wechat_message_text({"content": "  hello  "})
        assert result == "hello"
