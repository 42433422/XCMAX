from __future__ import annotations

"""Branch-coverage tests for app.services.mobile_relay_desktop_client."""

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    def test_default_url(self, monkeypatch):
        monkeypatch.delenv("XCAGI_RELAY_BASE_URL", raising=False)
        monkeypatch.delenv("XCAGI_PUBLIC_FHD_BASE_URL", raising=False)
        url = _relay_base_url()
        assert url.startswith("https://")
        assert url.endswith("/")

    def test_custom_url_from_env(self, monkeypatch):
        monkeypatch.setenv("XCAGI_RELAY_BASE_URL", "https://my.relay.example.com/api")
        url = _relay_base_url()
        assert url.startswith("https://my.relay.example.com")

    def test_url_without_scheme_gets_https(self, monkeypatch):
        monkeypatch.setenv("XCAGI_RELAY_BASE_URL", "my.relay.example.com")
        url = _relay_base_url()
        assert url.startswith("https://my.relay.example.com")

    def test_fallback_to_public_fhd_base_url(self, monkeypatch):
        monkeypatch.delenv("XCAGI_RELAY_BASE_URL", raising=False)
        monkeypatch.setenv("XCAGI_PUBLIC_FHD_BASE_URL", "https://fhd.example.com")
        url = _relay_base_url()
        assert "fhd.example.com" in url


# ---------------------------------------------------------------------------
# _api_url
# ---------------------------------------------------------------------------


class TestApiUrl:
    def test_with_base_url(self):
        url = _api_url("/api/test", "https://relay.example.com")
        assert url == "https://relay.example.com/api/test"

    def test_without_base_url(self, monkeypatch):
        monkeypatch.setenv("XCAGI_RELAY_BASE_URL", "https://default.example.com")
        url = _api_url("/api/test")
        assert "default.example.com" in url


# ---------------------------------------------------------------------------
# _read_config
# ---------------------------------------------------------------------------


class TestReadConfig:
    def test_file_not_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_module, "_CONFIG_FILE", tmp_path / "nope.json")
        assert _read_config() == {}

    def test_valid_config(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text('{"relay_id": "abc", "desktop_token": "tok"}', encoding="utf-8")
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        result = _read_config()
        assert result["relay_id"] == "abc"

    def test_invalid_json(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("not-json", encoding="utf-8")
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        assert _read_config() == {}

    def test_json_non_dict(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("[1, 2, 3]", encoding="utf-8")
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        assert _read_config() == {}


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

    def test_expired_exp(self):
        config = {"relay_id": "r1", "pairing_code": "p1", "exp": 1}
        assert _public_payload_from_config(config) is None

    def test_no_exp_with_registered_at(self, monkeypatch):
        monkeypatch.setenv("XCAGI_RELAY_PAIRING_TTL_SEC", "86400")
        config = {
            "relay_id": "r1",
            "pairing_code": "p1",
            "registered_at": int(time.time()) + 9999,
            "exp": 0,
        }
        result = _public_payload_from_config(config)
        assert result is not None
        assert result["relay_id"] == "r1"

    def test_valid_payload_with_exp(self, monkeypatch):
        future_exp = int(time.time()) + 9999
        config = {"relay_id": "r1", "pairing_code": "p1", "exp": future_exp}
        result = _public_payload_from_config(config)
        assert result is not None
        assert "qr_json" in result

    def test_payload_includes_expires_at(self):
        future_exp = int(time.time()) + 9999
        config = {
            "relay_id": "r1",
            "pairing_code": "p1",
            "exp": future_exp,
            "expires_at": "2099-01-01T00:00:00",
        }
        result = _public_payload_from_config(config)
        assert result is not None
        assert result.get("expires_at") == "2099-01-01T00:00:00"

    def test_payload_no_expires_at_omitted(self):
        future_exp = int(time.time()) + 9999
        config = {"relay_id": "r1", "pairing_code": "p1", "exp": future_exp, "expires_at": ""}
        result = _public_payload_from_config(config)
        assert result is not None
        assert "expires_at" not in result


# ---------------------------------------------------------------------------
# cached_desktop_relay_payload
# ---------------------------------------------------------------------------


class TestCachedDesktopRelayPayload:
    def test_no_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_module, "_CONFIG_FILE", tmp_path / "missing.json")
        assert cached_desktop_relay_payload() is None

    def test_returns_payload(self, tmp_path, monkeypatch):
        future_exp = int(time.time()) + 9999
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps({"relay_id": "r1", "pairing_code": "p1", "exp": future_exp}),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        result = cached_desktop_relay_payload()
        assert result is not None


# ---------------------------------------------------------------------------
# start_desktop_relay_poller
# ---------------------------------------------------------------------------


class TestStartPoller:
    def test_no_config_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_module, "_CONFIG_FILE", tmp_path / "missing.json")
        assert start_desktop_relay_poller() is False

    def test_starts_thread(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps({"relay_id": "r1", "desktop_token": "tok123"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        monkeypatch.setattr(_module, "_WORKER_THREAD", None)
        _module._STOP_EVENT.set()  # pre-stop so poll_loop exits immediately

        with patch.object(_module, "_poll_loop", return_value=None):
            result = start_desktop_relay_poller()
        assert result is True

    def test_already_running_returns_true(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps({"relay_id": "r1", "desktop_token": "tok123"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        monkeypatch.setattr(_module, "_WORKER_THREAD", mock_thread)
        result = start_desktop_relay_poller()
        assert result is True


# ---------------------------------------------------------------------------
# stop_desktop_relay_poller
# ---------------------------------------------------------------------------


class TestStopPoller:
    def test_sets_stop_event(self):
        _module._STOP_EVENT.clear()
        stop_desktop_relay_poller()
        assert _module._STOP_EVENT.is_set()


# ---------------------------------------------------------------------------
# _terminal_codex_message
# ---------------------------------------------------------------------------


class TestTerminalCodexMessage:
    def test_no_messages(self):
        assert _terminal_codex_message([], request_id="", task_id="") is None

    def test_non_assistant_role_skipped(self):
        msg = {"role": "user", "kind": "codex_result", "body": "hi"}
        assert _terminal_codex_message([msg], request_id="", task_id="") is None

    def test_wrong_kind_skipped(self):
        msg = {"role": "assistant", "kind": "chat", "body": "hi"}
        assert _terminal_codex_message([msg], request_id="", task_id="") is None

    def test_request_id_mismatch(self):
        msg = {
            "role": "assistant",
            "kind": "codex_result",
            "body": "hi",
            "dispatch_request_id": "req-other",
        }
        assert _terminal_codex_message([msg], request_id="req-1", task_id="") is None

    def test_task_id_mismatch(self):
        msg = {"role": "assistant", "kind": "codex_direct", "body": "hi", "task_id": "task-other"}
        assert _terminal_codex_message([msg], request_id="", task_id="task-1") is None

    def test_no_body_skipped(self):
        msg = {"role": "assistant", "kind": "codex_result", "body": ""}
        assert _terminal_codex_message([msg], request_id="", task_id="") is None

    def test_matching_message_returned(self):
        msg = {
            "role": "assistant",
            "kind": "codex_result",
            "body": "result!",
            "dispatch_request_id": "req-1",
            "task_id": "task-1",
        }
        result = _terminal_codex_message([msg], request_id="req-1", task_id="task-1")
        assert result is msg

    def test_empty_request_and_task_id(self):
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
    def test_no_message_returns_error(self):
        task = {"kind": "codex.invoke", "payload": {}}
        result = _execute_task(task)
        assert "error" in result

    def test_unsupported_kind(self):
        task = {"kind": "sms.send", "payload": {"message": "hello"}}
        result = _execute_task(task)
        assert "error" in result
        assert "暂不支持" in result["error"]

    def test_codex_invoke_completed(self):
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "do something"},
            "created_by_user_id": 1,
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {"dispatch": {"status": "completed"}}
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert result.get("ok") is True
        assert result.get("_relay_status") == "completed"

    def test_codex_invoke_not_accepted(self):
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "do something"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.return_value = {"dispatch": {"accepted": False, "reason": "busy"}}
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert "error" in result
        assert result.get("_relay_status") == "blocked"

    def test_codex_invoke_timeout(self):
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

    def test_codex_invoke_exception(self):
        task = {
            "kind": "codex.invoke",
            "payload": {"message": "trigger error"},
        }
        mock_svc = MagicMock()
        mock_svc.invoke.side_effect = RuntimeError("boom")
        with patch(
            "app.services.mobile_relay_desktop_client.CodexSuperEmployeeService",
            return_value=mock_svc,
        ):
            result = _execute_task(task)
        assert "error" in result


# ---------------------------------------------------------------------------
# _poll_once
# ---------------------------------------------------------------------------


class TestPollOnce:
    def test_no_relay_id_returns_early(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_module, "_CONFIG_FILE", tmp_path / "empty.json")
        # should not raise
        _poll_once()

    def test_404_returns_early(self, tmp_path, monkeypatch):
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

        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client
            _poll_once()  # should return without error


# ---------------------------------------------------------------------------
# register_desktop_relay
# ---------------------------------------------------------------------------


class TestRegisterDesktopRelay:
    def test_http_error_with_cached_payload(self, tmp_path, monkeypatch):
        """Branch: httpx raises, but cached config exists -> returns cached + starts poller."""
        future_exp = int(time.time()) + 9999
        cfg_file = tmp_path / "relay.json"
        cfg_file.write_text(
            json.dumps(
                {"relay_id": "r1", "pairing_code": "p1", "exp": future_exp, "desktop_token": "tok"}
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(_module, "_CONFIG_FILE", cfg_file)

        import httpx

        with patch("httpx.Client") as mock_cls:
            mock_c = MagicMock()
            mock_c.__enter__ = lambda s: mock_c
            mock_c.__exit__ = MagicMock(return_value=False)
            mock_c.post.side_effect = httpx.HTTPError("timeout")
            mock_cls.return_value = mock_c
            with patch.object(_module, "start_desktop_relay_poller"):
                result = register_desktop_relay(host="127.0.0.1", port=8000)
        assert result is not None

    def test_http_error_no_cached(self, tmp_path, monkeypatch):
        """Branch: httpx raises and no cached config -> returns None."""
        monkeypatch.setattr(_module, "_CONFIG_FILE", tmp_path / "missing.json")

        import httpx

        with patch("httpx.Client") as mock_cls:
            mock_c = MagicMock()
            mock_c.__enter__ = lambda s: mock_c
            mock_c.__exit__ = MagicMock(return_value=False)
            mock_c.post.side_effect = httpx.HTTPError("timeout")
            mock_cls.return_value = mock_c
            result = register_desktop_relay(host="127.0.0.1", port=8000)
        assert result is None

    def test_invalid_payload_returns_none(self, tmp_path, monkeypatch):
        """Branch: HTTP success but invalid payload (missing desktop_token)."""
        monkeypatch.setattr(_module, "_CONFIG_FILE", tmp_path / "relay.json")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"data": {"relay_id": "r1"}}  # no desktop_token

        import httpx

        with patch("httpx.Client") as mock_cls:
            mock_c = MagicMock()
            mock_c.__enter__ = lambda s: mock_c
            mock_c.__exit__ = MagicMock(return_value=False)
            mock_c.post.return_value = mock_resp
            mock_cls.return_value = mock_c
            result = register_desktop_relay(host="127.0.0.1", port=8000)
        assert result is None
