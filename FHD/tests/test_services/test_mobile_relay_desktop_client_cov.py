from __future__ import annotations

"""Behavior tests for app.services.mobile_relay_desktop_client.

These assert concrete return values / state changes / data-structure contents,
exercising both branches of each function under test. Only external IO (httpx,
super-employee services) is mocked; assertions land on the observable behavior
of the module-under-test, never on the mocks themselves.
"""

import json
import os
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

import app.services.mobile_relay_desktop_client as _module
from app.services.mobile_relay_desktop_client import (
    _api_url,
    _execute_task,
    _poll_once,
    _public_payload_from_config,
    _read_config,
    _relay_base_url,
    _terminal_codex_message,
    _write_config,
    cached_desktop_relay_payload,
    register_desktop_relay,
    start_desktop_relay_poller,
    stop_desktop_relay_poller,
)

# ---------------------------------------------------------------------------
# _relay_base_url
# ---------------------------------------------------------------------------


class TestRelayBaseUrl:
    def test_default_url_is_hardcoded_xiu_ci(self, monkeypatch):
        """No env -> the baked-in production relay URL, normalized with one trailing slash."""
        monkeypatch.delenv("XCAGI_RELAY_BASE_URL", raising=False)
        monkeypatch.delenv("XCAGI_PUBLIC_FHD_BASE_URL", raising=False)
        assert _relay_base_url() == "https://xiu-ci.com/fhd-api/"

    def test_custom_url_keeps_path_and_normalizes_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("XCAGI_RELAY_BASE_URL", "https://my.relay.example.com/api")
        # A single trailing slash is appended; the /api path segment survives.
        assert _relay_base_url() == "https://my.relay.example.com/api/"

    def test_url_with_many_trailing_slashes_collapses_to_one(self, monkeypatch):
        monkeypatch.setenv("XCAGI_RELAY_BASE_URL", "https://my.relay.example.com/api///")
        assert _relay_base_url() == "https://my.relay.example.com/api/"

    def test_url_without_scheme_gets_https_prefix(self, monkeypatch):
        monkeypatch.setenv("XCAGI_RELAY_BASE_URL", "my.relay.example.com")
        assert _relay_base_url() == "https://my.relay.example.com/"

    def test_http_scheme_is_preserved_not_forced_to_https(self, monkeypatch):
        monkeypatch.setenv("XCAGI_RELAY_BASE_URL", "http://insecure.example.com")
        assert _relay_base_url() == "http://insecure.example.com/"

    def test_fallback_to_public_fhd_base_url_when_relay_unset(self, monkeypatch):
        monkeypatch.delenv("XCAGI_RELAY_BASE_URL", raising=False)
        monkeypatch.setenv("XCAGI_PUBLIC_FHD_BASE_URL", "https://fhd.example.com")
        assert _relay_base_url() == "https://fhd.example.com/"

    def test_relay_url_wins_over_public_fhd_fallback(self, monkeypatch):
        """When both env vars are set, XCAGI_RELAY_BASE_URL takes precedence."""
        monkeypatch.setenv("XCAGI_RELAY_BASE_URL", "https://primary.example.com")
        monkeypatch.setenv("XCAGI_PUBLIC_FHD_BASE_URL", "https://fallback.example.com")
        assert _relay_base_url() == "https://primary.example.com/"


# ---------------------------------------------------------------------------
# _api_url
# ---------------------------------------------------------------------------


class TestApiUrl:
    def test_join_with_explicit_base(self):
        assert (
            _api_url("/api/test", "https://relay.example.com")
            == "https://relay.example.com/api/test"
        )

    def test_strips_duplicate_slashes_at_join(self):
        # base has trailing slash, path has leading slash -> exactly one slash between.
        assert _api_url("/api/x", "https://relay.example.com/") == "https://relay.example.com/api/x"

    def test_path_without_leading_slash_still_joins_cleanly(self):
        assert _api_url("api/x", "https://relay.example.com") == "https://relay.example.com/api/x"

    def test_falls_back_to_relay_base_url_when_base_omitted(self, monkeypatch):
        monkeypatch.setenv("XCAGI_RELAY_BASE_URL", "https://default.example.com")
        assert _api_url("/api/test") == "https://default.example.com/api/test"


# ---------------------------------------------------------------------------
# _read_config
# ---------------------------------------------------------------------------


class TestReadConfig:
    def test_file_not_exists_returns_empty_dict(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_module, "_CONFIG_FILE", tmp_path / "nope.json")
        assert _read_config() == {}

    def test_valid_config_returns_full_dict(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text('{"relay_id": "abc", "desktop_token": "tok"}', encoding="utf-8")
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        assert _read_config() == {"relay_id": "abc", "desktop_token": "tok"}

    def test_invalid_json_returns_empty_dict(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("not-json", encoding="utf-8")
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        assert _read_config() == {}

    def test_json_list_is_rejected_as_non_dict(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("[1, 2, 3]", encoding="utf-8")
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        assert _read_config() == {}


# ---------------------------------------------------------------------------
# _write_config (round-trip with _read_config)
# ---------------------------------------------------------------------------


class TestWriteConfig:
    def test_round_trip_preserves_data(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "out.json"
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        data = {"relay_id": "r9", "desktop_token": "t9", "exp": 123}
        _write_config(data)
        assert _read_config() == data

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "nested" / "deeper" / "relay.json"
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        _write_config({"relay_id": "r1"})
        assert cfg_file.is_file()
        assert json.loads(cfg_file.read_text(encoding="utf-8")) == {"relay_id": "r1"}

    def test_writes_unicode_unescaped_with_trailing_newline(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "uni.json"
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        _write_config({"label": "桌面执行端"})
        raw = cfg_file.read_text(encoding="utf-8")
        # ensure_ascii=False -> CJK chars stored verbatim, not as \uXXXX escapes.
        assert "桌面执行端" in raw
        assert "\\u" not in raw
        assert raw.endswith("\n")


# ---------------------------------------------------------------------------
# _public_payload_from_config
# ---------------------------------------------------------------------------


class TestPublicPayloadFromConfig:
    def test_empty_config(self):
        assert _public_payload_from_config({}) is None

    def test_missing_relay_id(self):
        assert _public_payload_from_config({"pairing_code": "abc"}) is None

    def test_missing_pairing_code(self):
        assert _public_payload_from_config({"relay_id": "r1"}) is None

    def test_expired_exp_in_past_returns_none(self):
        config = {"relay_id": "r1", "pairing_code": "p1", "exp": 1}
        assert _public_payload_from_config(config) is None

    def test_no_exp_derives_from_registered_at_plus_ttl(self, monkeypatch):
        monkeypatch.setenv("XCAGI_RELAY_PAIRING_TTL_SEC", "86400")
        registered_at = int(time.time())
        config = {
            "relay_id": "r1",
            "pairing_code": "p1",
            "registered_at": registered_at,
            "exp": 0,
        }
        result = _public_payload_from_config(config)
        assert result is not None
        # exp is derived as registered_at + TTL and surfaced in the payload.
        assert result["exp"] == registered_at + 86400
        assert result["relay_id"] == "r1"

    def test_registered_at_plus_ttl_already_expired_returns_none(self, monkeypatch):
        """Derived exp in the past (old registration + short TTL) -> None."""
        monkeypatch.setenv("XCAGI_RELAY_PAIRING_TTL_SEC", "10")
        config = {
            "relay_id": "r1",
            "pairing_code": "p1",
            "registered_at": int(time.time()) - 1000,
            "exp": 0,
        }
        assert _public_payload_from_config(config) is None

    def test_valid_payload_full_qr_json_structure(self, monkeypatch):
        monkeypatch.delenv("XCAGI_RELAY_BASE_URL", raising=False)
        monkeypatch.delenv("XCAGI_PUBLIC_FHD_BASE_URL", raising=False)
        future_exp = int(time.time()) + 9999
        config = {"relay_id": "r1", "pairing_code": "p1", "exp": future_exp}
        result = _public_payload_from_config(config)
        assert result is not None
        assert result["relay_id"] == "r1"
        assert result["pairing_code"] == "p1"
        assert result["exp"] == future_exp
        # base_url falls back to the default relay URL when config has none.
        assert result["relay_base_url"] == "https://xiu-ci.com/fhd-api/"
        # qr_json carries the full v3 pairing envelope; both code keys mirror the pairing code.
        assert result["qr_json"] == {
            "v": 3,
            "kind": "xcagi_relay_pairing",
            "relay_id": "r1",
            "code": "p1",
            "t": "p1",
            "relay_base_url": "https://xiu-ci.com/fhd-api/",
        }

    def test_config_relay_base_url_overrides_default(self):
        future_exp = int(time.time()) + 9999
        config = {
            "relay_id": "r1",
            "pairing_code": "p1",
            "exp": future_exp,
            "relay_base_url": "https://custom.relay.example.com/",
        }
        result = _public_payload_from_config(config)
        assert result is not None
        assert result["relay_base_url"] == "https://custom.relay.example.com/"
        assert result["qr_json"]["relay_base_url"] == "https://custom.relay.example.com/"

    def test_payload_includes_expires_at_when_present(self):
        future_exp = int(time.time()) + 9999
        config = {
            "relay_id": "r1",
            "pairing_code": "p1",
            "exp": future_exp,
            "expires_at": "2099-01-01T00:00:00",
        }
        result = _public_payload_from_config(config)
        assert result is not None
        assert result["expires_at"] == "2099-01-01T00:00:00"

    def test_empty_expires_at_is_omitted_from_payload(self):
        future_exp = int(time.time()) + 9999
        config = {
            "relay_id": "r1",
            "pairing_code": "p1",
            "exp": future_exp,
            "expires_at": "",
        }
        result = _public_payload_from_config(config)
        assert result is not None
        assert "expires_at" not in result


# ---------------------------------------------------------------------------
# cached_desktop_relay_payload
# ---------------------------------------------------------------------------


class TestCachedDesktopRelayPayload:
    def test_no_config_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_module, "_CONFIG_FILE", tmp_path / "missing.json")
        assert cached_desktop_relay_payload() is None

    def test_reads_config_and_returns_public_payload(self, tmp_path, monkeypatch):
        future_exp = int(time.time()) + 9999
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "relay_id": "r1",
                    "pairing_code": "p1",
                    "exp": future_exp,
                    # private token must NOT leak into the public payload.
                    "desktop_token": "secret-token",
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        result = cached_desktop_relay_payload()
        assert result is not None
        assert result["relay_id"] == "r1"
        assert result["pairing_code"] == "p1"
        # The private desktop_token is never exposed in the cached public payload.
        assert "desktop_token" not in result
        assert "desktop_token" not in result["qr_json"]


# ---------------------------------------------------------------------------
# start_desktop_relay_poller
# ---------------------------------------------------------------------------


class TestStartPoller:
    def test_no_config_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_module, "_CONFIG_FILE", tmp_path / "missing.json")
        assert start_desktop_relay_poller() is False

    def test_config_without_desktop_token_returns_false(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(json.dumps({"relay_id": "r1"}), encoding="utf-8")
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        monkeypatch.setattr(_module, "_WORKER_THREAD", None)
        assert start_desktop_relay_poller() is False

    def test_starts_daemon_thread_and_clears_stop_event(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps({"relay_id": "r1", "desktop_token": "tok123"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        monkeypatch.setattr(_module, "_WORKER_THREAD", None)
        # Pre-set the stop event; start() must clear it.
        _module._STOP_EVENT.set()
        started = []

        def fake_loop():
            started.append(True)

        try:
            with patch.object(_module, "_poll_loop", side_effect=fake_loop):
                result = start_desktop_relay_poller()
                thread = _module._WORKER_THREAD
                # Behavior: a real daemon worker thread is created and registered.
                assert result is True
                assert thread is not None
                assert thread.daemon is True
                assert thread.name == "xcagi-mobile-relay-desktop"
                # start() cleared the stop event before launching the loop.
                assert _module._STOP_EVENT.is_set() is False
                thread.join(timeout=2)
            assert started == [True]
        finally:
            _module._STOP_EVENT.set()
            monkeypatch.setattr(_module, "_WORKER_THREAD", None)

    def test_already_running_does_not_spawn_second_thread(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps({"relay_id": "r1", "desktop_token": "tok123"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        monkeypatch.setattr(_module, "_WORKER_THREAD", mock_thread)

        with patch.object(_module.threading, "Thread") as mk_thread:
            result = start_desktop_relay_poller()

        assert result is True
        # No new thread was constructed; the existing live worker is reused.
        mk_thread.assert_not_called()
        assert _module._WORKER_THREAD is mock_thread


# ---------------------------------------------------------------------------
# stop_desktop_relay_poller
# ---------------------------------------------------------------------------


class TestStopPoller:
    def test_sets_stop_event(self):
        _module._STOP_EVENT.clear()
        assert _module._STOP_EVENT.is_set() is False
        stop_desktop_relay_poller()
        assert _module._STOP_EVENT.is_set() is True


# ---------------------------------------------------------------------------
# _terminal_codex_message
# ---------------------------------------------------------------------------


class TestTerminalCodexMessage:
    def test_no_messages_returns_none(self):
        assert _terminal_codex_message([], request_id="", task_id="") is None

    def test_non_assistant_role_skipped(self):
        msg = {"role": "user", "kind": "codex_result", "body": "hi"}
        assert _terminal_codex_message([msg], request_id="", task_id="") is None

    def test_wrong_kind_skipped(self):
        msg = {"role": "assistant", "kind": "chat", "body": "hi"}
        assert _terminal_codex_message([msg], request_id="", task_id="") is None

    def test_request_id_mismatch_skipped(self):
        msg = {
            "role": "assistant",
            "kind": "codex_result",
            "body": "hi",
            "dispatch_request_id": "req-other",
        }
        assert _terminal_codex_message([msg], request_id="req-1", task_id="") is None

    def test_task_id_mismatch_skipped(self):
        msg = {
            "role": "assistant",
            "kind": "codex_direct",
            "body": "hi",
            "task_id": "task-other",
        }
        assert _terminal_codex_message([msg], request_id="", task_id="task-1") is None

    def test_empty_body_skipped(self):
        msg = {"role": "assistant", "kind": "codex_result", "body": ""}
        assert _terminal_codex_message([msg], request_id="", task_id="") is None

    def test_matching_message_returned_identity(self):
        msg = {
            "role": "assistant",
            "kind": "codex_result",
            "body": "result!",
            "dispatch_request_id": "req-1",
            "task_id": "task-1",
        }
        result = _terminal_codex_message([msg], request_id="req-1", task_id="task-1")
        assert result is msg

    def test_claude_result_kind_also_matches(self):
        """Generalization: claude_result is a terminal kind just like codex_result."""
        msg = {
            "role": "assistant",
            "kind": "claude_result",
            "body": "done",
            "request_id": "req-1",
            "task_id": "task-1",
        }
        result = _terminal_codex_message([msg], request_id="req-1", task_id="task-1")
        assert result is msg

    def test_returns_latest_matching_via_reverse_scan(self):
        """Multiple matches -> the most recent (last in list) is returned."""
        older = {
            "role": "assistant",
            "kind": "codex_result",
            "body": "old",
            "task_id": "t1",
        }
        newer = {
            "role": "assistant",
            "kind": "codex_result",
            "body": "new",
            "task_id": "t1",
        }
        result = _terminal_codex_message([older, newer], request_id="", task_id="t1")
        assert result is newer
        assert result["body"] == "new"

    def test_empty_filters_match_first_eligible_assistant_message(self):
        msg = {
            "role": "assistant",
            "kind": "codex_direct",
            "body": "ok",
            "dispatch_request_id": "",
            "task_id": "",
        }
        result = _terminal_codex_message([msg], request_id="", task_id="")
        assert result is msg


# ---------------------------------------------------------------------------
# _execute_task
# ---------------------------------------------------------------------------


class TestExecuteTask:
    def test_no_message_returns_specific_error(self):
        task = {"kind": "codex.invoke", "payload": {}}
        result = _execute_task(task)
        assert result == {"error": "任务缺少 message"}

    def test_unsupported_kind_returns_specific_error(self):
        task = {"kind": "sms.send", "payload": {"message": "hello"}}
        result = _execute_task(task)
        assert result == {"error": "暂不支持的任务类型：sms.send"}

    def test_message_falls_back_through_aliases(self):
        """message/body/prompt/task aliases are tried in order; first non-empty wins."""
        task = {"kind": "codex.invoke", "payload": {"prompt": "  from prompt  "}}
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {"dispatch": {"status": "completed"}}
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            _execute_task(task)
        # the aliased prompt value is stripped and forwarded as the message.
        assert mock_svc.invoke.call_args.kwargs["message"] == "from prompt"

    def test_git_op_kind_delegates_to_handle_git_op(self):
        """kind in GIT_OP_KINDS short-circuits to handle_git_op with the payload."""
        task = {"kind": "git.diff", "payload": {"branch": "feature/x"}}
        with patch(
            "app.services.mobile_relay_desktop_client.handle_git_op",
            return_value={"ok": True, "reply": "diff text"},
        ) as mk:
            result = _execute_task(task)
        assert result == {"ok": True, "reply": "diff text"}
        mk.assert_called_once_with("git.diff", {"branch": "feature/x"})

    def test_codex_invoke_completed_passes_relay_context(self):
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "do something"},
            "created_by_user_id": 7,
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {"dispatch": {"status": "completed"}}
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result["ok"] is True
        assert result["_relay_status"] == "completed"
        assert result["codex"] == {"dispatch": {"status": "completed"}}
        # created_by_user_id propagates as the invoking user.
        kwargs = mock_svc.invoke.call_args.kwargs
        assert kwargs["user_id"] == 7
        ctx = kwargs["context"]
        assert ctx["source"] == "mobile_relay"
        assert ctx["client_surface"] == "mobile"
        assert ctx["target_devices"] == ["all"]

    def test_code_mode_is_stripped_before_dispatch(self):
        """mode=code/task/dispatch/dev is dropped so the content classifier decides routing."""
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "你好", "context": {"mode": "code", "keep": "me"}},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {"dispatch": {"status": "completed"}}
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            _execute_task(task)
        ctx = mock_svc.invoke.call_args.kwargs["context"]
        assert "mode" not in ctx
        # other context keys survive the mode stripping.
        assert ctx["keep"] == "me"

    def test_non_dispatch_mode_is_preserved(self):
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "hi", "context": {"mode": "chat"}},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {"dispatch": {"status": "completed"}}
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            _execute_task(task)
        ctx = mock_svc.invoke.call_args.kwargs["context"]
        assert ctx["mode"] == "chat"

    def test_claude_kind_uses_claude_service_and_label(self):
        task = {"kind": "claude.invoke", "payload": {"message": "hi"}}
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {"dispatch": {"accepted": False, "reason": ""}}
        with (
            patch(
                "app.services.mobile_relay_desktop_client.ClaudeSuperEmployeeService",
                return_value=mock_svc,
            ),
            patch(
                "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService"
            ) as codex_cls,
        ):
            result = _execute_task(task)
        # Claude branch chosen: Claude service invoked, Codex service untouched.
        mock_svc.invoke.assert_called_once()
        codex_cls.assert_not_called()
        # empty reason falls back to the Claude-labelled default unavailable message.
        assert result["_relay_status"] == "blocked"
        assert result["error"] == "Claude/MCP 调度器当前不可用"

    def test_not_accepted_uses_provided_reason(self):
        task = {"kind": "codex.invoke", "payload": {"message": "do something"}}
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {"dispatch": {"accepted": False, "reason": "busy"}}
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result["error"] == "busy"
        assert result["_relay_status"] == "blocked"
        assert result["codex"] == {"dispatch": {"accepted": False, "reason": "busy"}}

    def test_accepted_then_terminal_message_completes(self, monkeypatch):
        """Accepted dispatch + a matching terminal assistant message -> completed."""
        monkeypatch.setenv("XCAGI_RELAY_CODEX_WAIT_TIMEOUT_SEC", "5")
        monkeypatch.setenv("XCAGI_RELAY_CODEX_WAIT_INTERVAL_SEC", "0.01")
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "do something"},
            "created_by_user_id": 3,
        }
        terminal_msg = {
            "role": "assistant",
            "kind": "codex_result",
            "body": "all done",
            "dispatch_request_id": "rid",
            "task_id": "tid",
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"accepted": True, "request_id": "rid", "task_id": "tid"}
        }
        mock_svc.list_messages.return_value = [terminal_msg]
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result["ok"] is True
        assert result["_relay_status"] == "completed"
        # the terminal assistant message is stitched into the codex result payload.
        assert result["codex"]["assistant_message"] is terminal_msg

    def test_accepted_but_no_terminal_message_times_out_blocked(self, monkeypatch):
        monkeypatch.setenv("XCAGI_RELAY_CODEX_WAIT_TIMEOUT_SEC", "0")
        monkeypatch.setenv("XCAGI_RELAY_CODEX_WAIT_INTERVAL_SEC", "0.01")
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "do something"},
            "created_by_user_id": 2,
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {
            "dispatch": {"accepted": True, "request_id": "r1", "task_id": "t1"}
        }
        mock_svc.list_messages.return_value = []
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result["_relay_status"] == "blocked"
        # timeout error names the tool and includes the task_id suffix.
        assert "Codex" in result["error"]
        assert "task_id=t1" in result["error"]

    def test_invoke_exception_is_caught_and_stringified(self):
        task = {"kind": "codex.invoke", "payload": {"message": "trigger error"}}
        mock_svc = MagicMock()
        mock_svc.invoke.side_effect = RuntimeError("boom")
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        # The exception message is surfaced verbatim (truncated to 1000 chars), no _relay_status.
        assert result == {"error": "boom"}

    def test_user_id_falls_back_to_payload_then_default(self):
        """created_by_user_id absent -> payload.user_id; both absent -> default 1."""
        task = {"kind": "codex.invoke", "payload": {"message": "hi", "user_id": 55}}
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {"dispatch": {"status": "completed"}}
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            _execute_task(task)
        assert mock_svc.invoke.call_args.kwargs["user_id"] == 55


# ---------------------------------------------------------------------------
# _poll_once
# ---------------------------------------------------------------------------


class TestPollOnce:
    def test_no_relay_id_skips_network_entirely(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_module, "_CONFIG_FILE", tmp_path / "empty.json")
        with patch("httpx.Client") as mock_client_cls:
            _poll_once()
        # No relay_id/token -> early return before any HTTP client is constructed.
        mock_client_cls.assert_not_called()

    def test_404_returns_without_dispatching_tasks(self, tmp_path, monkeypatch):
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
        mock_resp.status_code = 404

        with (
            patch("httpx.Client") as mock_client_cls,
            patch.object(_module.threading, "Thread") as mk_thread,
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client
            _poll_once()

        # 404 -> early return: raise_for_status never called, no task threads spawned.
        mock_resp.raise_for_status.assert_not_called()
        mk_thread.assert_not_called()

    def test_full_slots_skip_poll(self, tmp_path, monkeypatch):
        """When _INFLIGHT already fills max concurrency, no poll request is made."""
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
        monkeypatch.setenv("XCAGI_RELAY_MAX_CONCURRENT", "1")
        with _module._INFLIGHT_LOCK:
            _module._INFLIGHT.clear()
            _module._INFLIGHT.add("busy-task")
        try:
            with patch("httpx.Client") as mock_client_cls:
                _poll_once()
            mock_client_cls.assert_not_called()
        finally:
            with _module._INFLIGHT_LOCK:
                _module._INFLIGHT.clear()

    def test_claims_task_and_spawns_worker_thread(self, tmp_path, monkeypatch):
        """Happy path: a returned task is claimed into _INFLIGHT and handed to a worker thread."""
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
        monkeypatch.setenv("XCAGI_RELAY_MAX_CONCURRENT", "3")
        with _module._INFLIGHT_LOCK:
            _module._INFLIGHT.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {"tasks": [{"task_id": "task-abc", "kind": "codex.invoke"}]}
        }

        fake_thread = MagicMock()
        try:
            with (
                patch("httpx.Client") as mock_client_cls,
                patch.object(_module.threading, "Thread", return_value=fake_thread) as mk_thread,
            ):
                mock_client = MagicMock()
                mock_client.__enter__ = lambda s: mock_client
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_resp
                mock_client_cls.return_value = mock_client
                _poll_once()

            # The task got claimed and a worker thread was started for it.
            assert "task-abc" in _module._INFLIGHT
            fake_thread.start.assert_called_once()
            thread_kwargs = mk_thread.call_args.kwargs
            assert thread_kwargs["target"] is _module._complete_relay_task
            assert thread_kwargs["daemon"] is True
            # the claimed task dict is forwarded as the first worker arg.
            assert thread_kwargs["args"][0]["task_id"] == "task-abc"
            # poll request asks for the number of free slots (3 free, none in flight at request time).
            poll_body = mock_client.post.call_args.kwargs["json"]
            assert poll_body["relay_id"] == "r1"
            assert poll_body["max_tasks"] == 3
        finally:
            with _module._INFLIGHT_LOCK:
                _module._INFLIGHT.clear()

    def test_already_inflight_task_not_reclaimed(self, tmp_path, monkeypatch):
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
        monkeypatch.setenv("XCAGI_RELAY_MAX_CONCURRENT", "5")
        with _module._INFLIGHT_LOCK:
            _module._INFLIGHT.clear()
            _module._INFLIGHT.add("dup-task")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {"tasks": [{"task_id": "dup-task", "kind": "codex.invoke"}]}
        }
        try:
            with (
                patch("httpx.Client") as mock_client_cls,
                patch.object(_module.threading, "Thread") as mk_thread,
            ):
                mock_client = MagicMock()
                mock_client.__enter__ = lambda s: mock_client
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client.post.return_value = mock_resp
                mock_client_cls.return_value = mock_client
                _poll_once()
            # Task already in flight -> no second worker thread.
            mk_thread.assert_not_called()
        finally:
            with _module._INFLIGHT_LOCK:
                _module._INFLIGHT.clear()


# ---------------------------------------------------------------------------
# register_desktop_relay
# ---------------------------------------------------------------------------


class TestRegisterDesktopRelay:
    def test_http_error_with_cached_payload_returns_cache_and_starts_poller(
        self, tmp_path, monkeypatch
    ):
        """httpx raises, but a valid cached config exists -> return cached payload + start poller."""
        future_exp = int(time.time()) + 9999
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "relay_id": "r1",
                    "pairing_code": "p1",
                    "exp": future_exp,
                    "desktop_token": "tok",
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)

        with patch("httpx.Client") as mock_cls:
            mock_c = MagicMock()
            mock_c.__enter__ = lambda s: mock_c
            mock_c.__exit__ = MagicMock(return_value=False)
            mock_c.post.side_effect = httpx.HTTPError("timeout")
            mock_cls.return_value = mock_c
            with patch.object(_module, "start_desktop_relay_poller") as mk_start:
                result = register_desktop_relay(host="127.0.0.1", port=8000)

        assert result is not None
        # returns the cached public payload, not the (failed) server response.
        assert result["relay_id"] == "r1"
        assert result["pairing_code"] == "p1"
        # poller is (re)started so polling continues despite the failed re-register.
        mk_start.assert_called_once()

    def test_http_error_no_cache_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_module, "_CONFIG_FILE", tmp_path / "missing.json")

        with patch("httpx.Client") as mock_cls:
            mock_c = MagicMock()
            mock_c.__enter__ = lambda s: mock_c
            mock_c.__exit__ = MagicMock(return_value=False)
            mock_c.post.side_effect = httpx.HTTPError("timeout")
            mock_cls.return_value = mock_c
            with patch.object(_module, "start_desktop_relay_poller") as mk_start:
                result = register_desktop_relay(host="127.0.0.1", port=8000)

        assert result is None
        # no cache -> poller is not started.
        mk_start.assert_not_called()

    def test_invalid_payload_missing_token_returns_none_without_writing(
        self, tmp_path, monkeypatch
    ):
        cfg_file = tmp_path / "relay.json"
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"data": {"relay_id": "r1"}}  # no desktop_token

        with patch("httpx.Client") as mock_cls:
            mock_c = MagicMock()
            mock_c.__enter__ = lambda s: mock_c
            mock_c.__exit__ = MagicMock(return_value=False)
            mock_c.post.return_value = mock_resp
            mock_cls.return_value = mock_c
            with patch.object(_module, "start_desktop_relay_poller") as mk_start:
                result = register_desktop_relay(host="127.0.0.1", port=8000)

        assert result is None
        # invalid payload -> no config persisted, poller not started.
        assert not cfg_file.exists()
        mk_start.assert_not_called()

    def test_success_persists_config_and_returns_server_data(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "relay.json"
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)

        server_data = {
            "relay_id": "srv-relay",
            "desktop_token": "srv-token",
            "relay_base_url": "https://srv.example.com/",
            "pairing_code": "pc",
            "expires_at": "2099-01-01T00:00:00",
            "exp": int(time.time()) + 9999,
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"data": server_data}

        with patch("httpx.Client") as mock_cls:
            mock_c = MagicMock()
            mock_c.__enter__ = lambda s: mock_c
            mock_c.__exit__ = MagicMock(return_value=False)
            mock_c.post.return_value = mock_resp
            mock_cls.return_value = mock_c
            with patch.object(_module, "start_desktop_relay_poller") as mk_start:
                result = register_desktop_relay(host="127.0.0.1", port=8000, label="my desk")

        # returns the raw server data dict.
        assert result == server_data
        # poller started on success.
        mk_start.assert_called_once()
        # config persisted to disk with private token + a registered_at stamp + the label.
        persisted = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert persisted["relay_id"] == "srv-relay"
        assert persisted["desktop_token"] == "srv-token"
        assert persisted["label"] == "my desk"
        assert isinstance(persisted["registered_at"], int)
        assert persisted["registered_at"] > 0

    def test_register_posts_capabilities_to_register_endpoint(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "relay.json"
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        monkeypatch.setenv("XCAGI_RELAY_BASE_URL", "https://reg.example.com")
        # device_id is now a stable identity (get_stable_device_id), not host:port.
        # XCAGI_DEVICE_ID is the explicit override so the value is deterministic here.
        monkeypatch.setenv("XCAGI_DEVICE_ID", "stable-device-xyz")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"data": {"relay_id": "r1", "desktop_token": "t1"}}

        with patch("httpx.Client") as mock_cls:
            mock_c = MagicMock()
            mock_c.__enter__ = lambda s: mock_c
            mock_c.__exit__ = MagicMock(return_value=False)
            mock_c.post.return_value = mock_resp
            mock_cls.return_value = mock_c
            with patch.object(_module, "start_desktop_relay_poller"):
                register_desktop_relay(host="10.0.0.5", port=9999)

        url = mock_c.post.call_args.args[0]
        assert url == "https://reg.example.com/api/mobile/v1/relay/desktop/register"
        body = mock_c.post.call_args.kwargs["json"]
        caps = body["capabilities"]
        assert caps["host"] == "10.0.0.5"
        assert caps["port"] == 9999
        assert caps["codex"] is True
        assert caps["claude"] is True
        assert caps["cursor"] is True
        assert caps["desktop"] is True
        # host/port now live only in capabilities; the device_id is a stable
        # identity that survives port changes (here pinned via the override env).
        assert body["device_id"] == "stable-device-xyz"
