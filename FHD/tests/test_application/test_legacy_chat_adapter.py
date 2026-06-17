"""Tests for app.application.workflow.legacy_chat_adapter — coverage ramp."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.workflow.legacy_chat_adapter import (
    _LAST_TOOL_RESULT,
    _record_tool_result,
    _should_replace_tool_result,
    reset_last_tool_result,
)

# ========================= _should_replace_tool_result ===================


class TestShouldReplaceToolResult:
    def test_prev_none(self):
        assert _should_replace_tool_result(None, {"success": True}) is True

    def test_prev_empty(self):
        assert _should_replace_tool_result({}, {"success": True}) is True

    def test_new_success_replaces_prev_failure(self):
        assert _should_replace_tool_result({"success": False}, {"success": True}) is True

    def test_new_failure_does_not_replace_prev_success(self):
        assert _should_replace_tool_result({"success": True}, {"success": False}) is False

    def test_new_download_url_replaces_prev_without(self):
        assert (
            _should_replace_tool_result(
                {"success": True}, {"success": True, "download_url": "http://example.com"}
            )
            is True
        )

    def test_both_success_no_download(self):
        assert (
            _should_replace_tool_result(
                {"success": True, "data": "a"}, {"success": True, "data": "b"}
            )
            is False
        )


# ========================= _record_tool_result ===========================


class TestRecordToolResult:
    def test_records_success(self):
        reset_last_tool_result()
        _record_tool_result("test_tool", {"success": True, "data": "test"})
        result = _LAST_TOOL_RESULT.get()
        assert result is not None
        assert result["tool_key"] == "test_tool"
        assert result["success"] is True

    def test_skips_empty_payload(self):
        reset_last_tool_result()
        _record_tool_result("test_tool", {})
        assert _LAST_TOOL_RESULT.get() is None

    def test_skips_none_payload(self):
        reset_last_tool_result()
        _record_tool_result("test_tool", None)
        assert _LAST_TOOL_RESULT.get() is None

    def test_skips_requires_token(self):
        reset_last_tool_result()
        _record_tool_result("test_tool", {"requires_token": True})
        assert _LAST_TOOL_RESULT.get() is None

    def test_replaces_on_better_result(self):
        reset_last_tool_result()
        _record_tool_result("tool1", {"success": False})
        _record_tool_result("tool2", {"success": True})
        result = _LAST_TOOL_RESULT.get()
        assert result["tool_key"] == "tool2"

    def test_does_not_replace_on_worse_result(self):
        reset_last_tool_result()
        _record_tool_result("tool1", {"success": True, "data": "good"})
        _record_tool_result("tool2", {"success": False})
        result = _LAST_TOOL_RESULT.get()
        assert result["tool_key"] == "tool1"


# ========================= reset_last_tool_result ========================


class TestResetLastToolResult:
    def test_resets_to_none(self):
        _record_tool_result("tool", {"success": True})
        reset_last_tool_result()
        assert _LAST_TOOL_RESULT.get() is None
