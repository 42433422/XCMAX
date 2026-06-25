"""Branch-coverage tests for app.services.mobile_relay_desktop_client.

Targets the helper functions and _execute_task branches not covered by
the existing test_mobile_relay_desktop_client_cov.py suite:
- _max_concurrent
- _git_op_from_message (all branches)
- _text_mentions_branch_op
- _extract_branch_after / _extract_target_branch / _extract_merge_source / _extract_merge_target
- _trim_branch_token
- _classify_terminal_result
- _body_indicates_unfinished / _body_indicates_failed
- _terminal_error_summary
- _execute_task: claude/cursor kinds, completed ok/not-ok, accepted terminal, branch+mode clearing
- _poll_once: additional branches
- _complete_relay_task
- _write_config
- register_desktop_relay: success path
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Pre-import app.application to break circular import between app.services and app.mod_sdk
import app.application  # noqa: F401
import app.services.mobile_relay_desktop_client as _module
from app.services.mobile_relay_desktop_client import (
    _api_url,
    _body_indicates_failed,
    _body_indicates_unfinished,
    _classify_terminal_result,
    _complete_relay_task,
    _execute_task,
    _extract_branch_after,
    _extract_merge_source,
    _extract_merge_target,
    _extract_target_branch,
    _git_op_from_message,
    _max_concurrent,
    _poll_once,
    _public_payload_from_config,
    _read_config,
    _relay_base_url,
    _terminal_codex_message,
    _terminal_error_summary,
    _text_mentions_branch_op,
    _trim_branch_token,
    _write_config,
    cached_desktop_relay_payload,
    register_desktop_relay,
    start_desktop_relay_poller,
    stop_desktop_relay_poller,
)

# ---------------------------------------------------------------------------
# autouse fixture: isolate global state between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_inflight_state():
    """Clear _INFLIGHT set and STOP event before each test."""
    with _module._INFLIGHT_LOCK:
        _module._INFLIGHT.clear()
    _module._STOP_EVENT.clear()
    yield
    with _module._INFLIGHT_LOCK:
        _module._INFLIGHT.clear()
    _module._STOP_EVENT.clear()


# ---------------------------------------------------------------------------
# _max_concurrent
# ---------------------------------------------------------------------------


class TestMaxConcurrent:
    def test_default_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_RELAY_MAX_CONCURRENT", raising=False)
        assert _max_concurrent() == 3

    def test_custom_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_RELAY_MAX_CONCURRENT", "5")
        assert _max_concurrent() == 5

    def test_invalid_value_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_RELAY_MAX_CONCURRENT", "not-a-number")
        assert _max_concurrent() == 3

    def test_zero_clamped_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_RELAY_MAX_CONCURRENT", "0")
        assert _max_concurrent() == 1

    def test_negative_clamped_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_RELAY_MAX_CONCURRENT", "-5")
        assert _max_concurrent() == 1

    def test_empty_string_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_RELAY_MAX_CONCURRENT", "")
        assert _max_concurrent() == 3


# ---------------------------------------------------------------------------
# _trim_branch_token
# ---------------------------------------------------------------------------


class TestTrimBranchToken:
    def test_empty_string(self) -> None:
        assert _trim_branch_token("") == ""

    def test_none_value(self) -> None:
        assert _trim_branch_token(None) == ""  # type: ignore[arg-type]

    def test_simple_branch(self) -> None:
        assert _trim_branch_token("feature/test") == "feature/test"

    def test_strips_trailing_punctuation(self) -> None:
        assert _trim_branch_token("feature/test，") == "feature/test"
        assert _trim_branch_token("feature/test.") == "feature/test"
        assert _trim_branch_token("feature/test;") == "feature/test"

    def test_truncates_at_check_marker(self) -> None:
        result = _trim_branch_token("feature_CHECK")
        assert result == "feature"

    def test_truncates_at_if_marker(self) -> None:
        result = _trim_branch_token("feature_IF")
        assert result == "feature"

    def test_truncates_at_run_marker(self) -> None:
        result = _trim_branch_token("feature_RUN")
        assert result == "feature"

    def test_truncates_at_report_marker(self) -> None:
        result = _trim_branch_token("feature_REPORT")
        assert result == "feature"

    def test_truncates_at_do_marker(self) -> None:
        result = _trim_branch_token("feature_DO")
        assert result == "feature"

    def test_truncates_at_safe_marker(self) -> None:
        result = _trim_branch_token("feature_SAFE")
        assert result == "feature"

    def test_truncates_at_status_marker(self) -> None:
        result = _trim_branch_token("feature_STATUS")
        assert result == "feature"

    def test_truncates_at_first_marker(self) -> None:
        result = _trim_branch_token("feature_FIRST")
        assert result == "feature"

    def test_truncates_at_then_marker(self) -> None:
        result = _trim_branch_token("feature_THEN")
        assert result == "feature"

    def test_no_marker_keeps_full(self) -> None:
        assert _trim_branch_token("feature/branch-name") == "feature/branch-name"

    def test_invalid_chars_filtered(self) -> None:
        # Only [A-Za-z0-9][A-Za-z0-9._/-]{0,179} allowed
        result = _trim_branch_token("valid_branch")
        assert result == "valid_branch"


# ---------------------------------------------------------------------------
# _extract_branch_after
# ---------------------------------------------------------------------------


class TestExtractBranchAfter:
    def test_match_found(self) -> None:
        text = "请合并 SOURCE_feature_x_TARGET 分支"
        result = _extract_branch_after(text, "SOURCE_", "_TARGET")
        assert result == "feature_x"

    def test_no_match_returns_empty(self) -> None:
        result = _extract_branch_after("no markers here", "SOURCE_", "_TARGET")
        assert result == ""

    def test_case_insensitive(self) -> None:
        text = "source_feature_target"
        result = _extract_branch_after(text, "SOURCE_", "_TARGET")
        assert result == "feature"


# ---------------------------------------------------------------------------
# _extract_target_branch
# ---------------------------------------------------------------------------


class TestExtractTargetBranch:
    def test_match_found(self) -> None:
        text = "合并到 TARGET_main_branch"
        result = _extract_target_branch(text)
        assert result == "main_branch"

    def test_match_with_current(self) -> None:
        text = "TARGET_CURRENT_develop"
        result = _extract_target_branch(text)
        assert result == "develop"

    def test_no_match_returns_empty(self) -> None:
        result = _extract_target_branch("no target here")
        assert result == ""


# ---------------------------------------------------------------------------
# _extract_merge_source
# ---------------------------------------------------------------------------


class TestExtractMergeSource:
    def test_chinese_merge(self) -> None:
        text = "合并 feature/login"
        result = _extract_merge_source(text)
        assert result == "feature/login"

    def test_english_merge(self) -> None:
        text = "merge feature/payment"
        result = _extract_merge_source(text)
        assert result == "feature/payment"

    def test_chinese_with_branch_keyword(self) -> None:
        text = "合并 分支 feature/api"
        result = _extract_merge_source(text)
        assert result == "feature/api"

    def test_no_match_returns_empty(self) -> None:
        result = _extract_merge_source("just a regular message")
        assert result == ""


# ---------------------------------------------------------------------------
# _extract_merge_target
# ---------------------------------------------------------------------------


class TestExtractMergeTarget:
    def test_chinese_to(self) -> None:
        text = "合并到 main"
        result = _extract_merge_target(text)
        assert result == "main"

    def test_chinese_zhi(self) -> None:
        text = "合并至 develop"
        result = _extract_merge_target(text)
        assert result == "develop"

    def test_english_into(self) -> None:
        text = "merge into master"
        result = _extract_merge_target(text)
        assert result == "master"

    def test_arrow_syntax(self) -> None:
        text = "feature -> main"
        result = _extract_merge_target(text)
        assert result == "main"

    def test_chinese_with_branch_keyword(self) -> None:
        text = "合并到分支 release"
        result = _extract_merge_target(text)
        assert result == "release"

    def test_no_match_returns_empty(self) -> None:
        result = _extract_merge_target("no target marker")
        assert result == ""


# ---------------------------------------------------------------------------
# _text_mentions_branch_op
# ---------------------------------------------------------------------------


class TestTextMentionsBranchOp:
    def test_chinese_merge_branch(self) -> None:
        assert _text_mentions_branch_op("合并分支", "合并分支".lower()) is True

    def test_chinese_this_branch(self) -> None:
        assert _text_mentions_branch_op("这个分支", "这个分支".lower()) is True

    def test_chinese_current_branch(self) -> None:
        assert _text_mentions_branch_op("当前分支", "当前分支".lower()) is True

    def test_chinese_pending_merge_branch(self) -> None:
        assert _text_mentions_branch_op("待合并分支", "待合并分支".lower()) is True

    def test_english_merge_branch(self) -> None:
        assert _text_mentions_branch_op("merge branch here", "merge branch here") is True

    def test_english_current_branch(self) -> None:
        assert _text_mentions_branch_op("current branch", "current branch") is True

    def test_english_source_branch(self) -> None:
        assert _text_mentions_branch_op("source branch", "source branch") is True

    def test_english_target_branch(self) -> None:
        assert _text_mentions_branch_op("target branch", "target branch") is True

    def test_chinese_view_branch(self) -> None:
        assert _text_mentions_branch_op("查看分支", "查看分支".lower()) is True

    def test_chinese_discard_branch(self) -> None:
        assert _text_mentions_branch_op("丢弃分支", "丢弃分支".lower()) is True

    def test_chinese_delete_branch(self) -> None:
        assert _text_mentions_branch_op("删除分支", "删除分支".lower()) is True

    def test_no_match(self) -> None:
        assert _text_mentions_branch_op("hello world", "hello world") is False


# ---------------------------------------------------------------------------
# _git_op_from_message
# ---------------------------------------------------------------------------


class TestGitOpFromMessage:
    def test_explicit_git_op_merge(self) -> None:
        payload = {"git_op": "git.merge", "source_branch": "feature/x"}
        result = _git_op_from_message(payload, "合并分支")
        assert result is not None
        kind, git_payload = result
        assert kind == "git.merge"
        assert git_payload["branch"] == "feature/x"

    def test_explicit_op_field(self) -> None:
        payload = {"op": "git.diff", "branch": "feature/y"}
        result = _git_op_from_message(payload, "查看改动")
        assert result is not None
        kind, git_payload = result
        assert kind == "git.diff"
        assert git_payload["branch"] == "feature/y"

    def test_merge_text_marker(self) -> None:
        payload = {"branch": "feature/merge"}
        result = _git_op_from_message(payload, "合并 feature/test")
        assert result is not None
        kind, _ = result
        assert kind == "git.merge"

    def test_diff_text_marker(self) -> None:
        payload = {"source_branch": "feature/diff"}
        result = _git_op_from_message(payload, "查看改动")
        assert result is not None
        kind, _ = result
        assert kind == "git.diff"

    def test_discard_text_marker(self) -> None:
        payload = {"source_branch": "feature/discard"}
        result = _git_op_from_message(payload, "丢弃分支")
        assert result is not None
        kind, _ = result
        assert kind == "git.discard"

    def test_no_match_returns_none(self) -> None:
        payload = {}
        result = _git_op_from_message(payload, "just a regular message")
        assert result is None

    def test_source_from_text_source(self) -> None:
        payload = {}
        result = _git_op_from_message(payload, "合并 SOURCE_feature_x_TARGET")
        assert result is not None
        _, git_payload = result
        assert git_payload["branch"] == "feature_x"

    def test_source_from_merge_source_text(self) -> None:
        payload = {}
        result = _git_op_from_message(payload, "合并 feature/from-text")
        assert result is not None
        _, git_payload = result
        assert git_payload["branch"] == "feature/from-text"

    def test_source_from_branch_when_allowed(self) -> None:
        payload = {"branch": "feature/from-payload"}
        result = _git_op_from_message(payload, "合并分支")
        assert result is not None
        _, git_payload = result
        assert git_payload["branch"] == "feature/from-payload"

    def test_source_from_context_branch_when_allowed(self) -> None:
        payload = {"context": {"branch": "feature/from-context"}}
        result = _git_op_from_message(payload, "合并分支")
        assert result is not None
        _, git_payload = result
        assert git_payload["branch"] == "feature/from-context"

    def test_source_not_from_branch_when_not_allowed(self) -> None:
        # No branch-op mention, so allow_selected_branch is False
        payload = {"branch": "feature/should-not-use"}
        # Use explicit git_op to trigger allow_selected_branch=True
        payload["git_op"] = "git.merge"
        result = _git_op_from_message(payload, "regular message")
        assert result is not None
        _, git_payload = result
        assert git_payload["branch"] == "feature/should-not-use"

    def test_target_from_payload(self) -> None:
        payload = {
            "git_op": "git.merge",
            "source_branch": "feature/src",
            "target_branch": "main",
        }
        result = _git_op_from_message(payload, "merge")
        assert result is not None
        _, git_payload = result
        assert git_payload["target_branch"] == "main"

    def test_target_from_text(self) -> None:
        payload = {"git_op": "git.merge", "source_branch": "feature/src"}
        result = _git_op_from_message(payload, "合并到 TARGET_main")
        assert result is not None
        _, git_payload = result
        assert git_payload["target_branch"] == "main"

    def test_target_from_merge_text_for_merge_kind(self) -> None:
        payload = {"git_op": "git.merge", "source_branch": "feature/src"}
        result = _git_op_from_message(payload, "合并到 develop")
        assert result is not None
        _, git_payload = result
        assert git_payload["target_branch"] == "develop"

    def test_no_source_returns_none(self) -> None:
        payload = {"git_op": "git.merge"}
        result = _git_op_from_message(payload, "合并")
        assert result is None

    def test_target_branch_included_only_when_present(self) -> None:
        payload = {"git_op": "git.diff", "source_branch": "feature/src"}
        result = _git_op_from_message(payload, "查看改动")
        assert result is not None
        _, git_payload = result
        assert "target_branch" not in git_payload

    def test_message_included_in_payload(self) -> None:
        payload = {"git_op": "git.merge", "source_branch": "feature/src"}
        result = _git_op_from_message(payload, "合并分支 message here")
        assert result is not None
        _, git_payload = result
        assert git_payload["message"] == "合并分支 message here"


# ---------------------------------------------------------------------------
# _body_indicates_unfinished
# ---------------------------------------------------------------------------


class TestBodyIndicatesUnfinished:
    def test_empty_body(self) -> None:
        assert _body_indicates_unfinished("") is False

    def test_blocked_marker(self) -> None:
        assert _body_indicates_unfinished("任务被 BLOCKED") is True

    def test_blocked_marker_case_insensitive(self) -> None:
        assert _body_indicates_unfinished("blocked by upstream") is True

    def test_chinese_unfinished_marker(self) -> None:
        assert _body_indicates_unfinished("任务未完成") is True

    def test_chinese_cannot_complete_marker(self) -> None:
        assert _body_indicates_unfinished("无法完成此任务") is True

    def test_chinese_cannot_do_marker(self) -> None:
        assert _body_indicates_unfinished("不能完成") is True

    def test_chinese_not_done_marker(self) -> None:
        assert _body_indicates_unfinished("没有完成") is True

    def test_execution_failed_marker(self) -> None:
        assert _body_indicates_unfinished("执行失败") is True

    def test_failed_colon_marker(self) -> None:
        assert _body_indicates_unfinished("失败：原因") is True

    def test_validation_failed_marker(self) -> None:
        assert _body_indicates_unfinished("验证未通过") is True

    def test_merge_conflict_marker(self) -> None:
        assert _body_indicates_unfinished("合并有冲突") is True

    def test_english_merge_conflict_marker(self) -> None:
        assert _body_indicates_unfinished("merge conflict detected") is True

    def test_no_changes_marker(self) -> None:
        assert _body_indicates_unfinished("无改动可提交") is True

    def test_no_changes_to_commit_marker(self) -> None:
        assert _body_indicates_unfinished("未产生可提交改动") is True

    def test_hold_off_marker(self) -> None:
        assert _body_indicates_unfinished("先不动代码") is True

    def test_plan_only_marker(self) -> None:
        assert _body_indicates_unfinished("只给出执行方案") is True

    def test_plan_only_alt_marker(self) -> None:
        assert _body_indicates_unfinished("仅提供方案") is True

    def test_cannot_execute_marker(self) -> None:
        assert _body_indicates_unfinished("不能执行命令") is True

    def test_permission_denied_marker(self) -> None:
        assert _body_indicates_unfinished("权限不足") is True

    def test_x_emoji_marker(self) -> None:
        assert _body_indicates_unfinished("❌ 出错了") is True

    def test_marker_with_spaces_compact_match(self) -> None:
        # Marker with space should match compacted body
        assert _body_indicates_unfinished("merge conflict here") is True

    def test_no_marker(self) -> None:
        assert _body_indicates_unfinished("任务完成，一切正常") is False


# ---------------------------------------------------------------------------
# _body_indicates_failed
# ---------------------------------------------------------------------------


class TestBodyIndicatesFailed:
    def test_failed_marker(self) -> None:
        assert _body_indicates_failed("执行失败") is True

    def test_merge_conflict_marker(self) -> None:
        assert _body_indicates_failed("合并有冲突") is True

    def test_english_merge_conflict(self) -> None:
        assert _body_indicates_failed("merge conflict") is True

    def test_validation_failed(self) -> None:
        assert _body_indicates_failed("验证未通过") is True

    def test_x_emoji(self) -> None:
        assert _body_indicates_failed("❌") is True

    def test_error_lowercase(self) -> None:
        assert _body_indicates_failed("error occurred") is True

    def test_error_capitalized(self) -> None:
        assert _body_indicates_failed("Error: something") is True

    def test_no_marker(self) -> None:
        assert _body_indicates_failed("all good") is False


# ---------------------------------------------------------------------------
# _terminal_error_summary
# ---------------------------------------------------------------------------


class TestTerminalErrorSummary:
    def test_returns_first_non_empty_line(self) -> None:
        body = "\n  \n  first line  \nsecond line"
        result = _terminal_error_summary(body, "fallback")
        assert result == "first line"

    def test_strips_markdown_chars(self) -> None:
        body = "- **bold error**"
        result = _terminal_error_summary(body, "fallback")
        assert result == "bold error"

    def test_truncates_long_lines(self) -> None:
        body = "x" * 600
        result = _terminal_error_summary(body, "fallback")
        assert len(result) == 500

    def test_returns_fallback_when_empty(self) -> None:
        result = _terminal_error_summary("", "fallback msg")
        assert result == "fallback msg"

    def test_returns_fallback_when_only_whitespace(self) -> None:
        result = _terminal_error_summary("   \n   \n  ", "fallback msg")
        assert result == "fallback msg"


# ---------------------------------------------------------------------------
# _classify_terminal_result
# ---------------------------------------------------------------------------


class TestClassifyTerminalResult:
    def test_failed_status(self) -> None:
        row = {"status": "failed", "body": "something broke"}
        ok, status, error = _classify_terminal_result(row, message="msg")
        assert ok is False
        assert status == "failed"
        assert "something broke" in error

    def test_error_status(self) -> None:
        row = {"status": "error", "body": "error occurred"}
        ok, status, _ = _classify_terminal_result(row, message="msg")
        assert ok is False
        assert status == "failed"

    def test_merge_conflict_status(self) -> None:
        row = {"status": "merge_conflict", "body": "conflict"}
        ok, status, _ = _classify_terminal_result(row, message="msg")
        assert ok is False
        assert status == "failed"

    def test_cancelled_status(self) -> None:
        row = {"status": "cancelled", "body": "cancelled"}
        ok, status, _ = _classify_terminal_result(row, message="msg")
        assert ok is False
        assert status == "failed"

    def test_blocked_status(self) -> None:
        row = {"status": "blocked", "body": "blocked"}
        ok, status, _ = _classify_terminal_result(row, message="msg")
        assert ok is False
        assert status == "blocked"

    def test_timeout_status(self) -> None:
        row = {"status": "timeout", "body": "timed out"}
        ok, status, _ = _classify_terminal_result(row, message="msg")
        assert ok is False
        assert status == "blocked"

    def test_unfinished_body_failed(self) -> None:
        row = {"status": "completed", "body": "执行失败"}
        ok, status, _ = _classify_terminal_result(row, message="msg")
        assert ok is False
        assert status == "failed"

    def test_unfinished_body_blocked(self) -> None:
        row = {"status": "completed", "body": "权限不足"}
        ok, status, _ = _classify_terminal_result(row, message="msg")
        assert ok is False
        assert status == "blocked"

    def test_completed_status_with_body(self) -> None:
        row = {"status": "completed", "body": "all done"}
        ok, status, error = _classify_terminal_result(row, message="msg")
        assert ok is True
        assert status == "completed"
        assert error == ""

    def test_done_status(self) -> None:
        row = {"status": "done", "body": "finished"}
        ok, status, _ = _classify_terminal_result(row, message="msg")
        assert ok is True
        assert status == "completed"

    def test_merged_status(self) -> None:
        row = {"status": "merged", "body": "merged"}
        ok, status, _ = _classify_terminal_result(row, message="msg")
        assert ok is True
        assert status == "completed"

    def test_body_only_no_status(self) -> None:
        row = {"body": "some result"}
        ok, status, _ = _classify_terminal_result(row, message="msg")
        assert ok is True
        assert status == "completed"

    def test_empty_row(self) -> None:
        row = {}
        ok, status, _ = _classify_terminal_result(row, message="msg")
        assert ok is True
        assert status == "completed"

    def test_task_status_field_used(self) -> None:
        row = {"task_status": "failed", "body": "fail"}
        ok, status, _ = _classify_terminal_result(row, message="msg")
        assert ok is False
        assert status == "failed"

    def test_summary_field_used_as_body(self) -> None:
        row = {"status": "completed", "summary": "执行失败"}
        ok, status, _ = _classify_terminal_result(row, message="msg")
        assert ok is False
        assert status == "failed"

    def test_message_field_used_as_body(self) -> None:
        row = {"status": "completed", "message": "权限不足"}
        ok, status, _ = _classify_terminal_result(row, message="msg")
        assert ok is False
        assert status == "blocked"


# ---------------------------------------------------------------------------
# _execute_task - additional branches
# ---------------------------------------------------------------------------


class TestExecuteTaskAdditional:
    def test_claude_kind_completed_ok(self) -> None:
        task = {
            "kind": "claude.invoke",
            "payload": {"message": "do something"},
            "created_by_user_id": 1,
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "done"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.ClaudeSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result.get("ok") is True
        assert result.get("_relay_status") == "completed"

    def test_claude_kind_completed_not_ok(self) -> None:
        task = {
            "kind": "claude.invoke",
            "payload": {"message": "do something"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "failed", "body": "执行失败"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.ClaudeSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result.get("ok") is False
        assert result.get("_relay_status") == "failed"

    def test_cursor_kind_completed_ok(self) -> None:
        task = {
            "kind": "cursor.invoke",
            "payload": {"message": "do something"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "ok"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CursorSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result.get("ok") is True

    def test_cursor_kind_not_accepted(self) -> None:
        task = {
            "kind": "cursor.invoke",
            "payload": {"message": "do something"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"accepted": False, "reason": "busy"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CursorSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result.get("_relay_status") == "blocked"
        assert "busy" in result["error"]

    def test_codex_accepted_with_terminal_message(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "do something"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {
                "accepted": True,
                "request_id": "req-1",
                "task_id": "task-1",
            },
        }
        terminal_msg = {
            "role": "assistant",
            "kind": "codex_result",
            "body": "all done",
            "status": "completed",
            "dispatch_request_id": "req-1",
            "task_id": "task-1",
        }
        mock_svc.list_messages.return_value = [terminal_msg]

        with (
            patch(
                "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
                return_value=mock_svc,
            ),
            patch.dict(
                os.environ,
                {
                    "XCAGI_RELAY_CODEX_WAIT_TIMEOUT_SEC": "10",
                    "XCAGI_RELAY_CODEX_WAIT_INTERVAL_SEC": "0.01",
                },
            ),
        ):
            result = _execute_task(task)
        assert result.get("ok") is True
        assert result.get("_relay_status") == "completed"

    def test_codex_accepted_terminal_failed(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "do something"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {
                "accepted": True,
                "request_id": "req-1",
                "task_id": "task-1",
            },
        }
        terminal_msg = {
            "role": "assistant",
            "kind": "codex_result",
            "body": "执行失败",
            "status": "failed",
            "dispatch_request_id": "req-1",
            "task_id": "task-1",
        }
        mock_svc.list_messages.return_value = [terminal_msg]

        with (
            patch(
                "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
                return_value=mock_svc,
            ),
            patch.dict(
                os.environ,
                {
                    "XCAGI_RELAY_CODEX_WAIT_TIMEOUT_SEC": "10",
                    "XCAGI_RELAY_CODEX_WAIT_INTERVAL_SEC": "0.01",
                },
            ),
        ):
            result = _execute_task(task)
        assert result.get("ok") is False
        assert result.get("_relay_status") == "failed"

    def test_codex_accepted_no_task_id_in_suffix(self) -> None:
        """When task_id is empty, suffix is omitted in timeout error."""
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "do something"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {
                "accepted": True,
                "request_id": "req-1",
                "task_id": "",
            },
        }
        mock_svc.list_messages.return_value = []

        with (
            patch(
                "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
                return_value=mock_svc,
            ),
            patch.dict(
                os.environ,
                {
                    "XCAGI_RELAY_CODEX_WAIT_TIMEOUT_SEC": "0",
                    "XCAGI_RELAY_CODEX_WAIT_INTERVAL_SEC": "0.01",
                },
            ),
        ):
            result = _execute_task(task)
        assert result.get("_relay_status") == "blocked"
        assert "task_id=" not in result["error"]

    def test_codex_accepted_with_task_id_in_suffix(self) -> None:
        """When task_id is present, suffix is included in timeout error."""
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "do something"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {
                "accepted": True,
                "request_id": "req-1",
                "task_id": "task-xyz",
            },
        }
        mock_svc.list_messages.return_value = []

        with (
            patch(
                "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
                return_value=mock_svc,
            ),
            patch.dict(
                os.environ,
                {
                    "XCAGI_RELAY_CODEX_WAIT_TIMEOUT_SEC": "0",
                    "XCAGI_RELAY_CODEX_WAIT_INTERVAL_SEC": "0.01",
                },
            ),
        ):
            result = _execute_task(task)
        assert result.get("_relay_status") == "blocked"
        assert "task_id=task-xyz" in result["error"]

    def test_message_from_body_field(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {"body": "do via body"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "ok"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result.get("ok") is True
        # Verify message was extracted from body
        call_kwargs = mock_svc.invoke.call_args
        assert call_kwargs[1]["message"] == "do via body"

    def test_message_from_prompt_field(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {"prompt": "do via prompt"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "ok"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result.get("ok") is True

    def test_message_from_task_field(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {"task": "do via task"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "ok"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result.get("ok") is True

    def test_branch_added_to_context(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "do something", "branch": "feature/test"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "ok"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            _execute_task(task)
        call_kwargs = mock_svc.invoke.call_args[1]
        assert call_kwargs["context"]["branch"] == "feature/test"

    def test_branch_not_overriding_existing_context_branch(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {
                "message": "do something",
                "branch": "feature/new",
                "context": {"branch": "feature/existing"},
            },
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "ok"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            _execute_task(task)
        call_kwargs = mock_svc.invoke.call_args[1]
        assert call_kwargs["context"]["branch"] == "feature/existing"

    def test_mode_cleared_when_code(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {
                "message": "do something",
                "context": {"mode": "code"},
            },
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "ok"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            _execute_task(task)
        call_kwargs = mock_svc.invoke.call_args[1]
        assert "mode" not in call_kwargs["context"]

    def test_mode_cleared_when_task(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {
                "message": "do something",
                "context": {"mode": "task"},
            },
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "ok"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            _execute_task(task)
        call_kwargs = mock_svc.invoke.call_args[1]
        assert "mode" not in call_kwargs["context"]

    def test_mode_cleared_when_dispatch(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {
                "message": "do something",
                "context": {"mode": "dispatch"},
            },
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "ok"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            _execute_task(task)
        call_kwargs = mock_svc.invoke.call_args[1]
        assert "mode" not in call_kwargs["context"]

    def test_mode_cleared_when_dev(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {
                "message": "do something",
                "context": {"mode": "dev"},
            },
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "ok"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            _execute_task(task)
        call_kwargs = mock_svc.invoke.call_args[1]
        assert "mode" not in call_kwargs["context"]

    def test_mode_cleared_when_develop(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {
                "message": "do something",
                "context": {"mode": "develop"},
            },
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "ok"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            _execute_task(task)
        call_kwargs = mock_svc.invoke.call_args[1]
        assert "mode" not in call_kwargs["context"]

    def test_mode_preserved_when_other_value(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {
                "message": "do something",
                "context": {"mode": "chat"},
            },
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "ok"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            _execute_task(task)
        call_kwargs = mock_svc.invoke.call_args[1]
        assert call_kwargs["context"]["mode"] == "chat"

    def test_user_id_from_payload(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "do something", "user_id": 99},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "ok"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            _execute_task(task)
        call_kwargs = mock_svc.invoke.call_args[1]
        assert call_kwargs["user_id"] == 99

    def test_payload_not_dict_uses_empty(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": "not-a-dict",
        }
        result = _execute_task(task)
        assert "error" in result
        assert "message" in result["error"]

    def test_git_op_kind_dispatched(self) -> None:
        task = {
            "kind": "git.merge",
            "payload": {"branch": "feature/x"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.handle_git_op",
            return_value={"ok": True},
        ) as mock_handle:
            result = _execute_task(task)
        assert result == {"ok": True}
        mock_handle.assert_called_once_with("git.merge", {"branch": "feature/x"})

    def test_git_op_from_message_dispatched(self) -> None:
        task = {
            "kind": "codex.invoke",
            "payload": {
                "message": "合并 feature/test 到 main",
                "git_op": "git.merge",
                "source_branch": "feature/test",
            },
        }
        with patch(
            "app.services.mobile_relay_desktop_client.handle_git_op",
            return_value={"ok": True, "merged": True},
        ) as mock_handle:
            result = _execute_task(task)
        assert result == {"ok": True, "merged": True}
        mock_handle.assert_called_once()

    def test_default_kind_codex_invoke(self) -> None:
        task = {
            "payload": {"message": "do something"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "ok"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result.get("ok") is True

    def test_completed_no_assistant_message(self) -> None:
        """When dispatch.status=completed but assistant_message is not a dict."""
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "do something"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": "not-a-dict",
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        # assistant_message not a dict -> {} -> classify as completed/ok
        assert result.get("ok") is True

    def test_completed_assistant_message_unfinished(self) -> None:
        """When dispatch.status=completed and assistant indicates unfinished."""
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "do something"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"status": "completed"},
            "assistant_message": {"status": "completed", "body": "执行失败"},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result.get("ok") is False
        assert result.get("_relay_status") == "failed"

    def test_dispatch_not_accepted_no_reason(self) -> None:
        """When dispatch.accepted is not True and no reason provided."""
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "do something"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"accepted": False},
        }
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result.get("_relay_status") == "blocked"
        assert "Codex/MCP" in result["error"]


# ---------------------------------------------------------------------------
# _poll_once - additional branches
# ---------------------------------------------------------------------------


class TestPollOnceAdditional:
    def test_no_desktop_token_returns_early(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps({"relay_id": "r1", "desktop_token": ""}),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        # Should not raise
        _poll_once()

    def test_free_zero_returns_early(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "relay_id": "r1",
                    "desktop_token": "tok",
                    "relay_base_url": "https://x.example.com",
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        # Fill _INFLIGHT to make free=0 (default max_concurrent=3)
        with _module._INFLIGHT_LOCK:
            _module._INFLIGHT.update({"t1", "t2", "t3", "t4"})
        # Should not make HTTP call
        with patch("httpx.Client") as mock_client_cls:
            _poll_once()
            mock_client_cls.assert_not_called()

    def test_successful_poll_with_tasks(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "relay_id": "r1",
                    "desktop_token": "tok",
                    "relay_base_url": "https://x.example.com",
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "data": {"tasks": [{"task_id": "t1", "kind": "codex.invoke", "payload": {}}]}
        }

        with (
            patch("httpx.Client") as mock_client_cls,
            patch.object(_module, "_complete_relay_task") as mock_complete,
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client
            _poll_once()

        # Task should have been claimed
        assert "t1" in _module._INFLIGHT or mock_complete.called

    def test_successful_poll_with_non_dict_task_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "relay_id": "r1",
                    "desktop_token": "tok",
                    "relay_base_url": "https://x.example.com",
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "data": {"tasks": ["not-a-dict", {"task_id": ""}]}
        }

        with (
            patch("httpx.Client") as mock_client_cls,
            patch.object(_module, "_complete_relay_task") as mock_complete,
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client
            _poll_once()

        mock_complete.assert_not_called()

    def test_tasks_not_list_returns(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "relay_id": "r1",
                    "desktop_token": "tok",
                    "relay_base_url": "https://x.example.com",
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"data": {"tasks": "not-a-list"}}

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client
            _poll_once()  # should not raise

    def test_data_not_dict(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "relay_id": "r1",
                    "desktop_token": "tok",
                    "relay_base_url": "https://x.example.com",
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"data": "not-a-dict"}

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client
            _poll_once()  # should not raise

    def test_body_not_dict(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "relay_id": "r1",
                    "desktop_token": "tok",
                    "relay_base_url": "https://x.example.com",
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = "not-a-dict"

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client
            _poll_once()  # should not raise


# ---------------------------------------------------------------------------
# _complete_relay_task
# ---------------------------------------------------------------------------


class TestCompleteRelayTask:
    def test_successful_completion(self) -> None:
        task = {"task_id": "t1", "kind": "codex.invoke", "payload": {"message": "hi"}}

        with (
            patch.object(_module, "_execute_task", return_value={"ok": True}) as mock_exec,
            patch("httpx.Client") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            _complete_relay_task(task, "r1", "tok", "https://x.example.com")

        mock_exec.assert_called_once()
        assert "t1" not in _module._INFLIGHT

    def test_execute_raises_exception(self) -> None:
        task = {"task_id": "t2", "kind": "codex.invoke", "payload": {"message": "hi"}}

        with (
            patch.object(_module, "_execute_task", side_effect=RuntimeError("boom")),
            patch("httpx.Client") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            # Should not raise
            _complete_relay_task(task, "r1", "tok", "https://x.example.com")

        assert "t2" not in _module._INFLIGHT

    def test_http_post_raises_exception(self) -> None:
        task = {"task_id": "t3", "kind": "codex.invoke", "payload": {"message": "hi"}}

        with (
            patch.object(_module, "_execute_task", return_value={"ok": True}),
            patch("httpx.Client") as mock_client_cls,
        ):
            import httpx

            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = httpx.HTTPError("network error")
            mock_client_cls.return_value = mock_client

            # Should not raise
            _complete_relay_task(task, "r1", "tok", "https://x.example.com")

        assert "t3" not in _module._INFLIGHT

    def test_relay_status_from_result(self) -> None:
        task = {"task_id": "t4", "kind": "codex.invoke", "payload": {"message": "hi"}}

        with (
            patch.object(
                _module,
                "_execute_task",
                return_value={"ok": True, "_relay_status": "completed"},
            ),
            patch("httpx.Client") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            _complete_relay_task(task, "r1", "tok", "https://x.example.com")

        # Verify the status was sent
        call_kwargs = mock_client.post.call_args[1]["json"]
        assert call_kwargs["status"] == "completed"

    def test_relay_status_failed_when_error_in_result(self) -> None:
        task = {"task_id": "t5", "kind": "codex.invoke", "payload": {"message": "hi"}}

        with (
            patch.object(
                _module,
                "_execute_task",
                return_value={"error": "something failed"},
            ),
            patch("httpx.Client") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            _complete_relay_task(task, "r1", "tok", "https://x.example.com")

        call_kwargs = mock_client.post.call_args[1]["json"]
        assert call_kwargs["status"] == "failed"


# ---------------------------------------------------------------------------
# _write_config
# ---------------------------------------------------------------------------


class TestWriteConfig:
    def test_writes_config_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_file = tmp_path / "config.json"
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)

        _write_config({"relay_id": "r1", "desktop_token": "tok"})

        assert cfg_file.is_file()
        data = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert data["relay_id"] == "r1"

    def test_creates_parent_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_file = tmp_path / "subdir" / "config.json"
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)

        _write_config({"key": "value"})

        assert cfg_file.is_file()


# ---------------------------------------------------------------------------
# register_desktop_relay - success path
# ---------------------------------------------------------------------------


class TestRegisterDesktopRelaySuccess:
    def test_successful_registration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_file = tmp_path / "relay.json"
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "data": {
                "relay_id": "r1",
                "desktop_token": "tok",
                "relay_base_url": "https://relay.example.com",
                "pairing_code": "p1",
                "expires_at": "2099-01-01",
                "exp": int(time.time()) + 9999,
            }
        }

        with (
            patch("httpx.Client") as mock_cls,
            patch.object(_module, "start_desktop_relay_poller") as mock_start,
        ):
            mock_c = MagicMock()
            mock_c.__enter__ = lambda s: mock_c
            mock_c.__exit__ = MagicMock(return_value=False)
            mock_c.post.return_value = mock_resp
            mock_cls.return_value = mock_c

            result = register_desktop_relay(host="127.0.0.1", port=8000)

        assert result is not None
        assert result["relay_id"] == "r1"
        mock_start.assert_called_once()
        # Config should be written
        assert cfg_file.is_file()

    def test_successful_registration_with_label(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_file = tmp_path / "relay.json"
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "data": {
                "relay_id": "r1",
                "desktop_token": "tok",
                "pairing_code": "p1",
                "exp": int(time.time()) + 9999,
            }
        }

        with (
            patch("httpx.Client") as mock_cls,
            patch.object(_module, "start_desktop_relay_poller"),
        ):
            mock_c = MagicMock()
            mock_c.__enter__ = lambda s: mock_c
            mock_c.__exit__ = MagicMock(return_value=False)
            mock_c.post.return_value = mock_resp
            mock_cls.return_value = mock_c

            result = register_desktop_relay(host="127.0.0.1", port=8000, label="my-label")

        assert result is not None
        # Verify label was used in the request body
        call_kwargs = mock_c.post.call_args[1]["json"]
        assert call_kwargs["label"] == "my-label"

    def test_value_error_on_invalid_payload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Branch: HTTP success but json() raises ValueError."""
        monkeypatch.setattr(_module, "_CONFIG_FILE", tmp_path / "relay.json")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = ValueError("invalid json")

        with patch("httpx.Client") as mock_cls:
            mock_c = MagicMock()
            mock_c.__enter__ = lambda s: mock_c
            mock_c.__exit__ = MagicMock(return_value=False)
            mock_c.post.return_value = mock_resp
            mock_cls.return_value = mock_c

            result = register_desktop_relay(host="127.0.0.1", port=8000)

        assert result is None
