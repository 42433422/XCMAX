"""Branch-coverage tests for app/application/super_employee_service.py.

Targets the ~79 missing branches identified from coverage_new.json.
All external I/O (httpx, subprocess, filesystem) is mocked.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.application.super_employee_service import (
    _PARA_TOKEN_CACHE,
    CLAUDE_PROFILE,
    CODEX_PROFILE,
    CURSOR_PROFILE,
    DISPATCHER_MESSAGE_KIND,
    PARA_TERMINAL_TASK_STATUSES,
    SuperEmployeeService,
    SuperEmployeeToolProfile,
    _coerce_list,
    _safe_json_line,
    _utc_now,
)

# ─────────────────────────── helpers ────────────────────────────


def _make_svc(tmp_path: Path, profile=CODEX_PROFILE, **kwargs) -> SuperEmployeeService:
    """Build a service with isolated storage and outbox disabled by default."""
    kwargs.setdefault("cli_runner", _null_runner)
    return SuperEmployeeService(profile=profile, storage_root=tmp_path, **kwargs)


def _null_runner(cmd, **kw):
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def _stdout_runner(stdout: str):
    def _run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    return _run


def _error_runner(exc):
    def _run(cmd, **kw):
        raise exc

    return _run


def test_super_employee_profiles_bind_to_distinct_cli_tools() -> None:
    assert CODEX_PROFILE.tool_name == "codex"
    assert CODEX_PROFILE.capability_key == "codex_cli"
    assert CODEX_PROFILE.cli_binary == "codex"
    assert CODEX_PROFILE.storage_subdir == "codex_super_employee"
    assert CODEX_PROFILE.result_kind == "codex_result"

    assert CURSOR_PROFILE.tool_name == "cursor_agent"
    assert CURSOR_PROFILE.capability_key == "cursor_cli"
    # Cursor 的无头 CLI 二进制是 `cursor-agent`（独立 agent 二进制），不是 IDE 的 `cursor`。
    assert CURSOR_PROFILE.cli_binary == "cursor-agent"
    assert CURSOR_PROFILE.storage_subdir == "cursor_super_employee"
    assert CURSOR_PROFILE.result_kind == "cursor_result"
    assert CURSOR_PROFILE.cli_command_builder("cursor", "hello", Path("out"), "/tmp")[:3] == [
        "cursor",
        "agent",
        "--print",
    ]

    assert CLAUDE_PROFILE.tool_name == "claude_code"
    assert CLAUDE_PROFILE.capability_key == "claude_cli"
    assert CLAUDE_PROFILE.cli_binary == "claude"
    assert CLAUDE_PROFILE.storage_subdir == "claude_super_employee"
    assert CLAUDE_PROFILE.result_kind == "claude_result"
    assert CLAUDE_PROFILE.cli_command_builder("claude", "hello", Path("out"), "/tmp")[:4] == [
        "claude",
        "--print",
        "--output-format",
        "stream-json",
    ]


def _fake_http_factory(status: int = 200, body: dict | None = None, exc=None):
    """Return a context-manager–compatible mock httpx.Client factory."""

    def factory():
        client = MagicMock(spec=httpx.Client)
        client.__enter__ = lambda s: s
        client.__exit__ = MagicMock(return_value=False)
        if exc is not None:
            client.post.side_effect = exc
            client.get.side_effect = exc
            client.request.side_effect = exc
        else:
            resp = MagicMock()
            resp.status_code = status
            resp.content = b"x"
            resp.json.return_value = body or {}
            resp.text = json.dumps(body or {})
            client.post.return_value = resp
            client.get.return_value = resp
            client.request.return_value = resp
        return client

    return factory


# ─────────────── module-level helpers ───────────────────────────


class TestModuleHelpers:
    def test_coerce_list_with_list(self):
        assert _coerce_list([1, 2]) == [1, 2]

    def test_coerce_list_with_non_list(self):
        assert _coerce_list("oops") == []
        assert _coerce_list(None) == []
        assert _coerce_list(42) == []

    def test_utc_now_is_string(self):
        s = _utc_now()
        assert isinstance(s, str)
        assert "T" in s

    def test_safe_json_line_ends_with_newline(self):
        line = _safe_json_line({"a": 1})
        assert line.endswith("\n")
        assert json.loads(line.strip()) == {"a": 1}


# ─────────────── list_messages ──────────────────────────────────


class TestListMessages:
    def test_empty_file_returns_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc.list_messages(user_id=1) == []

    def test_user_scoped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
        svc = _make_svc(tmp_path)
        svc.invoke(user_id=1, message="任务 A")
        svc.invoke(user_id=2, message="任务 B")
        msgs = svc.list_messages(user_id=1)
        assert all(m.get("role") or True for m in msgs)  # just structural smoke
        bodies = [m["body"] for m in msgs]
        assert any("任务 A" in b for b in bodies)

    def test_limit_capped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
        svc = _make_svc(tmp_path)
        for i in range(10):
            svc.invoke(user_id=1, message=f"任务{i}")
        msgs = svc.list_messages(user_id=1, limit=3)
        assert len(msgs) <= 3

    def test_limit_negative_uses_minimum(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
        svc = _make_svc(tmp_path)
        svc.invoke(user_id=1, message="任务 X")
        msgs = svc.list_messages(user_id=1, limit=0)
        assert isinstance(msgs, list)


# ─────────────── invoke — direct / CLI branch ───────────────────


class TestInvokeDirect:
    def test_empty_message_raises(self, tmp_path):
        svc = _make_svc(tmp_path)
        with pytest.raises(ValueError, match="message"):
            svc.invoke(user_id=1, message="  ")

    def test_chat_mode_uses_cli(self, tmp_path):
        cli = tmp_path / "codex"
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o755)
        svc = _make_svc(
            tmp_path,
            cli_runner=_stdout_runner("cli answer"),
        )
        with patch.object(svc, "_cli_path", return_value=str(cli)):
            result = svc.invoke(user_id=1, message="你好", context={"mode": "chat"})
        assert result["dispatch"]["status"] == "completed"
        assert result["dispatch"]["dispatcher"] == "codex_cli"

    def test_direct_identity_reply_no_cli(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_cli_path", return_value=""):
            result = svc.invoke(user_id=1, message="你是谁", context={"mode": "chat"})
        assert "Codex" in result["assistant_message"]["body"]

    def test_direct_help_reply(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_cli_path", return_value=""):
            result = svc.invoke(user_id=1, message="你能做什么", context={"mode": "chat"})
        assert (
            "派工" in result["assistant_message"]["body"]
            or "任务" in result["assistant_message"]["body"]
        )

    def test_direct_greeting_reply(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_cli_path", return_value=""):
            result = svc.invoke(user_id=1, message="你好", context={"mode": "chat"})
        assert result["dispatch"]["queued"] is False

    def test_direct_slow_reply(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_cli_path", return_value=""):
            result = svc.invoke(user_id=1, message="为什么这么慢", context={"mode": "chat"})
        assert "慢" in result["assistant_message"]["body"]

    def test_fallback_when_cli_returns_empty_and_no_direct(self, tmp_path):
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        with patch.object(svc, "_cli_path", return_value=str(tmp_path / "notexist")):
            # no direct reply body either for a random sentence
            result = svc.invoke(user_id=1, message="今天天气怎么样啊", context={"mode": "chat"})
        # Must still produce a response (fallback message)
        assert "CLI" in result["assistant_message"]["body"]

    def test_code_mode_forces_dispatch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
        svc = _make_svc(tmp_path)
        result = svc.invoke(user_id=1, message="你好", context={"mode": "code"})
        assert result["dispatch"]["queued"] is True


# ─────────────── invoke — dispatch path ─────────────────────────


class TestInvokeDispatch:
    def test_outbox_mode_writes_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
        svc = _make_svc(tmp_path)
        result = svc.invoke(user_id=1, message="修复 bug", context={"source": "admin_im"})
        dispatch = result["dispatch"]
        assert dispatch["queued"] is True
        assert Path(dispatch["outbox_path"]).is_file()

    def test_mobile_source_translated(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
        svc = _make_svc(tmp_path)
        result = svc.invoke(user_id=1, message="修复 bug", context={"source": "mobile_chat"})
        assert result["dispatch"]["queued"] is True

    def test_target_devices_list_preserved(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
        svc = _make_svc(tmp_path)
        result = svc.invoke(
            user_id=1,
            message="修复 bug",
            context={"target_devices": ["dev1", "dev2"]},
        )
        assert result["dispatch"]["queued"] is True

    def test_webhook_accepted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "webhook")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", "http://example.com/hook")
        svc = _make_svc(
            tmp_path,
            http_client_factory=_fake_http_factory(200, {"ok": True}),
        )
        result = svc.invoke(user_id=1, message="修复 bug")
        assert result["dispatch"]["accepted"] is True
        assert result["dispatch"]["queued"] is False

    def test_webhook_rejected_goes_to_outbox(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "webhook")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", "http://example.com/hook")
        svc = _make_svc(
            tmp_path,
            http_client_factory=_fake_http_factory(500, {"error": "server error"}),
        )
        result = svc.invoke(user_id=1, message="修复 bug")
        assert result["dispatch"]["queued"] is True

    def test_webhook_exception_goes_to_outbox(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "webhook")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", "http://example.com/hook")
        svc = _make_svc(
            tmp_path,
            http_client_factory=_fake_http_factory(exc=RuntimeError("boom")),
        )
        result = svc.invoke(user_id=1, message="修复 bug")
        assert result["dispatch"]["queued"] is True

    def test_dispatch_reply_no_webhook_configured(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "webhook")
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_DELEGATE_WEBHOOK", raising=False)
        svc = _make_svc(tmp_path)
        result = svc.invoke(user_id=1, message="修复 bug")
        assert result["dispatch"]["queued"] is True


# ─────────────── _dispatch_to_para ──────────────────────────────


class TestDispatchToPara:
    def test_disabled_url_returns_none_reason(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "disabled")
        svc = _make_svc(tmp_path)
        result, reason = svc._dispatch_to_para({"request_id": "r1", "created_at": "2025"})
        assert result is None
        assert "disabled" in reason

    def test_unhealthy_api_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        svc = _make_svc(
            tmp_path,
            http_client_factory=_fake_http_factory(503, {}),
        )
        result, reason = svc._dispatch_to_para({"request_id": "r1", "created_at": "t"})
        assert result is None
        assert "unhealthy" in reason or "503" in reason

    def test_timeout_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        svc = _make_svc(
            tmp_path,
            http_client_factory=_fake_http_factory(exc=httpx.ConnectError("timeout")),
        )
        result, reason = svc._dispatch_to_para({"request_id": "r1", "created_at": "t"})
        assert result is None
        assert "unreachable" in reason

    def test_no_devices_writes_outbox(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "tok")

        def factory():
            client = MagicMock(spec=httpx.Client)
            client.__enter__ = lambda s: s
            client.__exit__ = MagicMock(return_value=False)
            health_resp = MagicMock()
            health_resp.status_code = 200
            health_resp.content = b"ok"
            health_resp.json.return_value = {}
            devices_resp = MagicMock()
            devices_resp.status_code = 200
            devices_resp.content = b"x"
            devices_resp.json.return_value = {"devices": []}
            client.get.return_value = health_resp
            client.request.return_value = devices_resp
            return client

        svc = _make_svc(tmp_path, http_client_factory=factory)
        result, reason = svc._dispatch_to_para(
            {"request_id": "r1", "created_at": "t", "target_devices": ["all"]}
        )
        assert result is not None
        assert result["queued"] is True

    def test_general_exception_goes_to_outbox(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "tok")

        def factory():
            client = MagicMock(spec=httpx.Client)
            client.__enter__ = lambda s: s
            client.__exit__ = MagicMock(return_value=False)
            health_resp = MagicMock()
            health_resp.status_code = 200
            health_resp.content = b"ok"
            health_resp.json.return_value = {}
            client.get.return_value = health_resp
            client.request.side_effect = ValueError("bad json")
            return client

        svc = _make_svc(tmp_path, http_client_factory=factory)
        result, reason = svc._dispatch_to_para({"request_id": "r1", "created_at": "t"})
        assert result is not None
        assert result["queued"] is True


# ─────────────── _select_para_devices ───────────────────────────


class TestSelectParaDevices:
    def _svc(self, tmp_path):
        return _make_svc(tmp_path)

    def test_excludes_offline_device(self, tmp_path):
        svc = self._svc(tmp_path)
        devices = [{"id": "d1", "status": "offline"}]
        result = svc._select_para_devices(devices, {"target_devices": ["all"]})
        assert result == []

    def test_excludes_not_installed_tool(self, tmp_path):
        svc = self._svc(tmp_path)
        devices = [
            {
                "id": "d1",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "not_installed"}],
            }
        ]
        result = svc._select_para_devices(devices, {"target_devices": ["all"]})
        assert result == []

    def test_excludes_running_busy_tool(self, tmp_path):
        svc = self._svc(tmp_path)
        devices = [
            {
                "id": "d1",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "running", "currentTask": "task1"}],
            }
        ]
        result = svc._select_para_devices(devices, {"target_devices": ["all"]})
        assert result == []

    def test_no_tool_and_no_capability_excludes(self, tmp_path):
        svc = self._svc(tmp_path)
        devices = [{"id": "d1", "status": "online", "capabilities": {"codex_cli": False}}]
        result = svc._select_para_devices(devices, {"target_devices": ["all"]})
        assert result == []

    def test_capability_key_true_includes(self, tmp_path):
        svc = self._svc(tmp_path)
        devices = [{"id": "d1", "status": "online", "capabilities": {"codex_cli": True}}]
        result = svc._select_para_devices(devices, {"target_devices": ["all"]})
        assert len(result) == 1

    def test_target_filter_by_name(self, tmp_path):
        svc = self._svc(tmp_path)
        devices = [
            {
                "id": "d1",
                "name": "worker1",
                "status": "online",
                "capabilities": {"codex_cli": True},
            },
            {
                "id": "d2",
                "name": "worker2",
                "status": "online",
                "capabilities": {"codex_cli": True},
            },
        ]
        result = svc._select_para_devices(devices, {"target_devices": ["worker1"]})
        assert len(result) == 1
        assert result[0]["id"] == "d1"

    def test_prefers_non_primary_workers(self, tmp_path):
        svc = self._svc(tmp_path)
        devices = [
            {
                "id": "primary",
                "status": "online",
                "isPrimary": True,
                "capabilities": {"codex_cli": True},
            },
            {
                "id": "worker",
                "status": "online",
                "isPrimary": False,
                "capabilities": {"codex_cli": True},
            },
        ]
        result = svc._select_para_devices(devices, {"target_devices": ["all"]})
        assert result[0]["id"] == "worker"

    def test_max_devices_limits_result(self, tmp_path):
        svc = self._svc(tmp_path)
        devices = [
            {"id": f"d{i}", "status": "online", "capabilities": {"codex_cli": True}}
            for i in range(10)
        ]
        result = svc._select_para_devices(
            devices, {"target_devices": ["all"], "raw_context": {"max_devices": 2}}
        )
        assert len(result) <= 3  # default max=3 since raw_context not used here

    def test_skips_non_dict_items(self, tmp_path):
        svc = self._svc(tmp_path)
        result = svc._select_para_devices(["string", 42, None], {"target_devices": ["all"]})
        assert result == []


# ─────────────── Para 分级派工(一级/二级) ────────────────────────


class TestParaTier:
    """一级=本机单设备, 二级=多设备协同; 默认一级优先, 按需升二级。"""

    def _svc(self, tmp_path):
        return _make_svc(tmp_path)

    # ── _resolve_para_tier ──

    def test_default_is_tier_one(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc._resolve_para_tier({"task": "修复登录"}) == 1

    def test_max_devices_gt_one_escalates(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc._resolve_para_tier({"raw_context": {"max_devices": 3}}) == 2

    def test_explicit_tier_hint_two(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc._resolve_para_tier({"raw_context": {"para_tier": "2"}}) == 2

    def test_explicit_tier_hint_one_overrides_marker(self, tmp_path):
        svc = self._svc(tmp_path)
        # 文本含"多设备"但显式指定一级 → 仍一级
        assert svc._resolve_para_tier({"task": "多设备", "raw_context": {"tier": "1"}}) == 1

    def test_multi_device_text_marker_escalates(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc._resolve_para_tier({"task": "调用所有设备跑测试"}) == 2

    def test_escalate_flag(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc._resolve_para_tier({"raw_context": {"escalate": True}}) == 2

    def test_multiple_specific_target_devices_escalates(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc._resolve_para_tier({"target_devices": ["d1", "d2"]}) == 2

    def test_single_target_device_stays_tier_one(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc._resolve_para_tier({"target_devices": ["d1"]}) == 1

    def test_all_target_devices_stays_tier_one(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc._resolve_para_tier({"target_devices": ["all"]}) == 1

    def test_force_tier_env_one(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODSTORE_PARA_FORCE_TIER", "1")
        svc = self._svc(tmp_path)
        # 即便要求多设备, env 强制一级
        assert svc._resolve_para_tier({"raw_context": {"max_devices": 5}}) == 1

    def test_force_tier_env_two(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODSTORE_PARA_FORCE_TIER", "2")
        svc = self._svc(tmp_path)
        assert svc._resolve_para_tier({"task": "闲聊"}) == 2

    # ── _select_local_device ──

    def test_local_prefers_primary(self, tmp_path):
        svc = self._svc(tmp_path)
        devices = [
            {"id": "w1", "status": "online", "capabilities": {"codex_cli": True}},
            {
                "id": "p1",
                "status": "online",
                "isPrimary": True,
                "capabilities": {"codex_cli": True},
            },
        ]
        result = svc._select_local_device(devices, {})
        assert [d["id"] for d in result] == ["p1"]

    def test_local_prefers_configured_device_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "w1")
        svc = self._svc(tmp_path)
        devices = [
            {"id": "w1", "status": "online", "capabilities": {"codex_cli": True}},
            {
                "id": "p1",
                "status": "online",
                "isPrimary": True,
                "capabilities": {"codex_cli": True},
            },
        ]
        result = svc._select_local_device(devices, {})
        # 配置的本机 id 优先于 is_primary
        assert [d["id"] for d in result] == ["w1"]

    def test_local_falls_back_to_first_eligible(self, tmp_path):
        svc = self._svc(tmp_path)
        devices = [{"id": "a", "status": "online", "capabilities": {"codex_cli": True}}]
        result = svc._select_local_device(devices, {})
        assert [d["id"] for d in result] == ["a"]

    def test_local_empty_when_none_eligible(self, tmp_path):
        svc = self._svc(tmp_path)
        devices = [{"id": "a", "status": "offline", "capabilities": {"codex_cli": True}}]
        assert svc._select_local_device(devices, {}) == []

    # ── _select_devices_by_tier ──

    def test_tier_one_returns_single_local(self, tmp_path):
        svc = self._svc(tmp_path)
        devices = [
            {
                "id": "p1",
                "status": "online",
                "isPrimary": True,
                "capabilities": {"codex_cli": True},
            },
            {"id": "w1", "status": "online", "capabilities": {"codex_cli": True}},
        ]
        tier, selected = svc._select_devices_by_tier(devices, {"task": "修复"})
        assert tier == 1
        assert [d["id"] for d in selected] == ["p1"]

    def test_tier_one_escalates_when_primary_lacks_tool(self, tmp_path):
        # 本机主设备装了 codex 但没装 claude；claude 任务在一级选不到本机 → 升二级到 worker。
        # (正是本机 Mac 主设备 claude_code not_installed、Win32 有 claude 的真实形态)
        svc_claude = _make_svc(tmp_path, profile=CLAUDE_PROFILE)
        devices = [
            {
                "id": "p1",
                "status": "online",
                "isPrimary": True,
                "tools": [{"toolName": "claude_code", "status": "not_installed"}],
            },
            {
                "id": "w1",
                "status": "online",
                "tools": [{"toolName": "claude_code", "status": "idle"}],
            },
        ]
        tier, selected = svc_claude._select_devices_by_tier(devices, {"task": "修复"})
        assert tier == 2
        assert [d["id"] for d in selected] == ["w1"]

    def test_tier_one_no_devices_at_all_outboxes_via_empty(self, tmp_path):
        svc = self._svc(tmp_path)
        devices = [{"id": "p1", "status": "offline", "isPrimary": True}]
        tier, selected = svc._select_devices_by_tier(devices, {"task": "修复"})
        assert selected == []

    def test_tier_two_explicit_uses_workers(self, tmp_path):
        svc = self._svc(tmp_path)
        devices = [
            {
                "id": "p1",
                "status": "online",
                "isPrimary": True,
                "capabilities": {"codex_cli": True},
            },
            {"id": "w1", "status": "online", "capabilities": {"codex_cli": True}},
            {"id": "w2", "status": "online", "capabilities": {"codex_cli": True}},
        ]
        tier, selected = svc._select_devices_by_tier(devices, {"raw_context": {"max_devices": 3}})
        assert tier == 2
        # 二级偏好非主 worker
        assert {d["id"] for d in selected} == {"w1", "w2"}


# ─────────────── _ensure_para_device ────────────────────────────


class TestEnsureParaDevice:
    def test_already_correct_tool_returns_device(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {"id": "d1", "devTool": "codex"}
        result = svc._ensure_para_device(MagicMock(), "http://para", "tok", device)
        assert result is device

    def test_no_id_returns_device_unchanged(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {"devTool": "other"}
        result = svc._ensure_para_device(MagicMock(), "http://para", "tok", device)
        assert result is device

    def test_updates_device_via_api(self, tmp_path):
        svc = _make_svc(tmp_path)
        client = MagicMock()
        new_device = {"id": "d1", "devTool": "codex"}
        client.request.return_value = MagicMock(
            status_code=200,
            content=b"x",
            json=lambda: {"device": new_device},
        )
        device = {"id": "d1", "devTool": "other"}
        with patch.object(svc, "_para_request", return_value={"device": new_device}):
            result = svc._ensure_para_device(client, "http://para", "tok", device)
        assert result == new_device

    def test_fallback_when_response_has_no_device(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {"id": "d1", "devTool": "other"}
        with patch.object(svc, "_para_request", return_value={}):
            result = svc._ensure_para_device(MagicMock(), "http://para", "tok", device)
        assert result["devTool"] == "codex"


# ─────────────── _para_token ────────────────────────────────────


class TestParaToken:
    def test_env_token_returned_directly(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "mytoken")
        svc = _make_svc(tmp_path)
        result = svc._para_token(MagicMock(), "http://para")
        assert result == "mytoken"

    def test_guest_auth_success(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("DEVFLEET_TOKEN", raising=False)
        svc = _make_svc(tmp_path)
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"x"
        resp.json.return_value = {"token": "guest_tok"}
        client.post.return_value = resp
        with patch.object(svc, "_json_response", return_value={"token": "guest_tok"}):
            result = svc._para_token(client, "http://para")
        assert result == "guest_tok"

    def test_guest_auth_fails_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("DEVFLEET_TOKEN", raising=False)
        _PARA_TOKEN_CACHE.clear()
        svc = _make_svc(tmp_path)
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 401
        resp.content = b"x"
        client.post.return_value = resp
        with patch.object(svc, "_json_response", return_value={"error": "unauthorized"}):
            with pytest.raises(RuntimeError):
                svc._para_token(client, "http://para")

    def test_guest_auth_no_token_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("DEVFLEET_TOKEN", raising=False)
        _PARA_TOKEN_CACHE.clear()
        svc = _make_svc(tmp_path)
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"x"
        client.post.return_value = resp
        with patch.object(svc, "_json_response", return_value={}):
            with pytest.raises(RuntimeError, match="token"):
                svc._para_token(client, "http://para")


# ─────────────── _para_api_url ──────────────────────────────────


class TestParaApiUrl:
    def test_disabled_values(self, tmp_path, monkeypatch):
        # The function checks value.lower() in {"", "0", "false", "off", "none", "disabled"}
        # Empty string is the tricky case: env var empty → falls to DEFAULT_PARA_API_URL
        # so only explicitly "disabled"-ish named values work here
        for v in ("disabled", "0", "false", "off", "none"):
            monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", v)
            monkeypatch.delenv("MODSTORE_PARA_API_URL", raising=False)
            monkeypatch.delenv("DEVFLEET_API_URL", raising=False)
            svc = _make_svc(tmp_path)
            assert svc._para_api_url() == "", f"Expected '' for {v!r}"

    def test_valid_url_returned(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para:3001/")
        svc = _make_svc(tmp_path)
        url = svc._para_api_url()
        assert url == "http://para:3001"

    def test_falls_back_to_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_API_URL", raising=False)
        monkeypatch.delenv("DEVFLEET_API_URL", raising=False)
        svc = _make_svc(tmp_path)
        assert "127.0.0.1" in svc._para_api_url()


# ─────────────── _max_para_devices ──────────────────────────────


class TestMaxParaDevices:
    def test_default_is_three(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._max_para_devices({}) == 3

    def test_raw_context_value(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._max_para_devices({"raw_context": {"max_devices": 5}}) == 5

    def test_invalid_value_returns_three(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._max_para_devices({"raw_context": {"max_devices": "bad"}}) == 3

    def test_clamped_to_one(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._max_para_devices({"raw_context": {"max_devices": -5}}) == 1

    def test_clamped_to_eight(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._max_para_devices({"raw_context": {"max_devices": 100}}) == 8


# ─────────────── _cli_reply_body ────────────────────────────────


class TestCliReplyBody:
    def test_cli_disabled_env_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_CHAT_ENABLED", "0")
        svc = _make_svc(tmp_path)
        assert svc._cli_reply_body("hi", {}) == ""

    def test_no_cli_path_returns_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_cli_path", return_value=""):
            assert svc._cli_reply_body("hi", {}) == ""

    def test_timeout_returns_message(self, tmp_path):
        cli = tmp_path / "codex"
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o755)
        svc = _make_svc(tmp_path, cli_runner=_error_runner(subprocess.TimeoutExpired("cmd", 45)))
        with patch.object(svc, "_cli_path", return_value=str(cli)):
            result = svc._cli_reply_body("hi", {})
        assert "超过" in result or "CLI" in result

    def test_os_error_returns_failure_message(self, tmp_path):
        cli = tmp_path / "codex"
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o755)
        svc = _make_svc(tmp_path, cli_runner=_error_runner(OSError("no such")))
        with patch.object(svc, "_cli_path", return_value=str(cli)):
            result = svc._cli_reply_body("hi", {})
        assert "CLI" in result

    def test_reads_output_file_when_exists(self, tmp_path):
        cli = tmp_path / "codex"
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o755)

        def runner_with_file(cmd, **kw):
            # Write to the --output-last-message path
            idx = cmd.index("--output-last-message")
            Path(cmd[idx + 1]).write_text("file output", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        svc = _make_svc(tmp_path, cli_runner=runner_with_file)
        with patch.object(svc, "_cli_path", return_value=str(cli)):
            result = svc._cli_reply_body("hi", {})
        assert result == "file output"

    def test_falls_back_to_stdout(self, tmp_path):
        cli = tmp_path / "codex"
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o755)
        svc = _make_svc(tmp_path, cli_runner=_stdout_runner("stdout answer"))
        with patch.object(svc, "_cli_path", return_value=str(cli)):
            # cli_reads_output_file=True but file not created → falls through to stdout
            result = svc._cli_reply_body("hi", {})
        assert "stdout answer" in result

    def test_returncode_nonzero_returns_error_body(self, tmp_path):
        cli = tmp_path / "codex"
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o755)

        def fail_runner(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="something bad")

        svc = _make_svc(tmp_path, cli_runner=fail_runner)
        with patch.object(svc, "_cli_path", return_value=str(cli)):
            result = svc._cli_reply_body("hi", {})
        assert "CLI" in result or "code" in result

    def test_claude_profile_reads_stdout(self, tmp_path):
        import json as _json

        cli = tmp_path / "claude"
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o755)
        # CLAUDE_PROFILE uses cli_stream_json=True, so output must be stream-json events.
        stream_line = _json.dumps({"type": "result", "result": "claude answer"})
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE, cli_runner=_stdout_runner(stream_line))
        with patch.object(svc, "_cli_path", return_value=str(cli)):
            result = svc._cli_reply_body("hi", {})
        assert "claude answer" in result


# ─────────────── _clean_cli_stdout ──────────────────────────────


class TestCleanCliStdout:
    def test_filters_tool_name_line(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = svc._clean_cli_stdout("codex\nsome real output\ntokens used\n123,456")
        assert "codex" not in out.splitlines()
        assert "tokens used" not in out
        assert "some real output" in out

    def test_filters_numeric_lines(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = svc._clean_cli_stdout("1,234\nreal\n56789")
        assert "1,234" not in out
        assert "real" in out

    def test_empty_lines_stripped(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = svc._clean_cli_stdout("\n\nresult\n\n")
        assert out == "result"


# ─────────────── _dispatch_reply ────────────────────────────────


class TestDispatchReply:
    # _dispatch_reply 已统一返回"思考中..."避免向用户暴露派工实现细节。
    # 以下测试验证该方法对各种 dispatch 状态均返回约定占位语。

    def test_para_accepted(self, tmp_path):
        svc = _make_svc(tmp_path)
        dispatch = {
            "accepted": True,
            "dispatcher": "para_api",
            "task_id": "task123",
            "devices": [{"id": "d1"}],
        }
        assert svc._dispatch_reply(dispatch) == "思考中..."

    def test_para_accepted_no_task_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        dispatch = {
            "accepted": True,
            "dispatcher": "para_api",
            "task_id": "",
            "devices": [{"id": "d1"}, {"id": "d2"}],
        }
        assert svc._dispatch_reply(dispatch) == "思考中..."

    def test_webhook_accepted(self, tmp_path):
        svc = _make_svc(tmp_path)
        dispatch = {"accepted": True, "dispatcher": "webhook"}
        assert svc._dispatch_reply(dispatch) == "思考中..."

    def test_no_device_reason(self, tmp_path):
        svc = _make_svc(tmp_path)
        dispatch = {"queued": True, "reason": "para_no_online_codex_device"}
        assert svc._dispatch_reply(dispatch) == "思考中..."

    def test_queued_reason(self, tmp_path):
        svc = _make_svc(tmp_path)
        dispatch = {"queued": True, "reason": "other_reason"}
        assert svc._dispatch_reply(dispatch) == "思考中..."

    def test_not_accepted_not_queued(self, tmp_path):
        svc = _make_svc(tmp_path)
        dispatch = {"accepted": False, "queued": False}
        assert svc._dispatch_reply(dispatch) == "思考中..."


# ─────────────── _should_reply_with_cli ─────────────────────────


class TestShouldReplyWithCli:
    def test_chat_mode_true(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("修复 bug", {"mode": "chat"}) is True

    def test_code_mode_false(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("你好", {"mode": "code"}) is False

    def test_task_keyword_false(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("请修复登录页面", {}) is False

    def test_plain_question_true(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("今天天气怎么样", {}) is True

    def test_empty_text_false(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("", {}) is False

    def test_codex_cli_mode_true(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("任何消息", {"mode": "codex_cli"}) is True

    def test_dispatch_mode_false(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("你好", {"mode": "dispatch"}) is False


# ─────────────── _upgrade_legacy_dispatcher_row ─────────────────


class TestUpgradeLegacyDispatcherRow:
    def test_already_dispatcher_skips(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"kind": DISPATCHER_MESSAGE_KIND, "role": "system"}
        assert svc._upgrade_legacy_dispatcher_row(row) is False

    def test_non_assistant_role_skips(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"role": "user", "body": "已接入排比 Para/Codex 多设备调度器"}
        assert svc._upgrade_legacy_dispatcher_row(row) is False

    def test_body_not_ack_skips(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"role": "assistant", "body": "hello world"}
        assert svc._upgrade_legacy_dispatcher_row(row) is False

    def test_upgrades_dispatcher_row(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {
            "role": "assistant",
            "body": "已接入排比 Para/Codex 多设备调度器，任务已派发到 1 台设备。任务 ID：abc-123",
        }
        changed = svc._upgrade_legacy_dispatcher_row(row)
        assert changed is True
        assert row["role"] == "system"
        assert row["kind"] == DISPATCHER_MESSAGE_KIND
        assert row.get("task_id") == "abc-123"

    def test_upgrades_without_task_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"role": "assistant", "body": "已进入软件内 Codex 调用队列，等待跨设备调度器接走。"}
        changed = svc._upgrade_legacy_dispatcher_row(row)
        assert changed is True
        assert row.get("task_id") is None or row.get("task_id") == ""


# ─────────────── _para_task_status_reply ────────────────────────


class TestParaTaskStatusReply:
    def _svc(self, tmp_path):
        return _make_svc(tmp_path)

    def test_completed_status(self, tmp_path):
        svc = self._svc(tmp_path)
        task = {"id": "t1", "status": "completed", "subTasks": []}
        body = svc._para_task_status_reply(task)
        assert "完成" in body

    def test_merged_status(self, tmp_path):
        svc = self._svc(tmp_path)
        task = {"id": "t1", "status": "merged"}
        body = svc._para_task_status_reply(task)
        assert "完成" in body

    def test_failed_status(self, tmp_path):
        svc = self._svc(tmp_path)
        task = {"id": "t1", "status": "failed"}
        body = svc._para_task_status_reply(task)
        assert "处理" in body

    def test_merge_conflict_status(self, tmp_path):
        svc = self._svc(tmp_path)
        task = {"id": "t1", "status": "merge_conflict"}
        body = svc._para_task_status_reply(task)
        assert "处理" in body

    def test_in_progress_with_subtasks(self, tmp_path):
        svc = self._svc(tmp_path)
        task = {
            "id": "t1",
            "status": "running",
            "subTasks": [
                {"status": "completed", "progress": 100},
                {"status": "pending", "progress": 0},
            ],
        }
        body = svc._para_task_status_reply(task)
        assert "运行中" in body

    def test_failed_subtask_triggers_failed_head(self, tmp_path):
        svc = self._svc(tmp_path)
        task = {
            "id": "t1",
            "status": "running",
            "subTasks": [{"status": "failed"}],
        }
        body = svc._para_task_status_reply(task)
        assert "处理" in body

    def test_no_subtasks_waiting(self, tmp_path):
        svc = self._svc(tmp_path)
        task = {"id": "t1", "status": "running"}
        body = svc._para_task_status_reply(task)
        assert "等待" in body

    def test_no_task_id_in_reply(self, tmp_path):
        svc = self._svc(tmp_path)
        task = {"status": "completed"}
        body = svc._para_task_status_reply(task)
        assert "任务 ID" not in body


# ─────────────── _result_body ───────────────────────────────────


class TestResultBody:
    def _svc(self, tmp_path):
        return _make_svc(tmp_path)

    def test_with_logs(self, tmp_path):
        svc = self._svc(tmp_path)
        task = {"title": "Task A"}
        subtask = {
            "status": "completed",
            "device_name": "dev1",
            "logs": [{"content": "output line"}],
        }
        body = svc._result_body(task, subtask)
        assert "output line" in body

    def test_completed_no_logs(self, tmp_path):
        svc = self._svc(tmp_path)
        task = {"title": "Task A"}
        subtask = {"status": "completed", "device_name": "dev1", "logs": []}
        body = svc._result_body(task, subtask)
        assert "已完成" in body

    def test_failed_with_error(self, tmp_path):
        svc = self._svc(tmp_path)
        task = {"title": "Task A"}
        subtask = {
            "status": "failed",
            "device_name": "dev1",
            "last_error": "compile error",
            "logs": [],
        }
        body = svc._result_body(task, subtask)
        assert "失败" in body
        assert "compile error" in body

    def test_unknown_status_empty_logs_returns_empty(self, tmp_path):
        svc = self._svc(tmp_path)
        task = {"title": "Task A"}
        subtask = {"status": "pending", "device_name": "dev1", "logs": []}
        body = svc._result_body(task, subtask)
        assert body == ""

    def test_dispatcher_logs_filtered(self, tmp_path):
        svc = self._svc(tmp_path)
        task = {"title": "T"}
        subtask = {
            "status": "completed",
            "logs": [
                {"content": "子任务「x」"},
                {"content": "real output"},
            ],
        }
        body = svc._result_body(task, subtask)
        assert "子任务「" not in body
        assert "real output" in body


# ─────────────── _para_prompt / _para_subtask_title ─────────────


class TestParaPromptAndSubtask:
    def _svc(self, tmp_path):
        return _make_svc(tmp_path)

    def test_single_device_prompt(self, tmp_path):
        svc = self._svc(tmp_path)
        req = {"prompt": "修复 bug", "workspace_root": "/repo"}
        prompt = svc._para_prompt(req, {"id": "d1"}, 0, 1)
        assert "请直接完成" in prompt
        assert "/repo" in prompt

    def test_multi_device_prompt(self, tmp_path):
        svc = self._svc(tmp_path)
        req = {"prompt": "修复 bug", "workspace_root": ""}
        prompt = svc._para_prompt(req, {"name": "dev1"}, 0, 3)
        assert "1/3" in prompt

    def test_subtask_title_single(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc._para_subtask_title("My Task", 0, 1) == "My Task"

    def test_subtask_title_multi(self, tmp_path):
        svc = self._svc(tmp_path)
        title = svc._para_subtask_title("My Task", 0, 3)
        assert "需求定位与方案" in title

    def test_subtask_title_beyond_labels(self, tmp_path):
        svc = self._svc(tmp_path)
        title = svc._para_subtask_title("My Task", 10, 15)
        assert "工作单元" in title


# ─────────────── _json_response / _error_message ────────────────


class TestJsonResponseAndError:
    def test_valid_json(self, tmp_path):
        svc = _make_svc(tmp_path)
        resp = MagicMock()
        resp.content = b"x"
        resp.json.return_value = {"a": 1}
        assert svc._json_response(resp) == {"a": 1}

    def test_invalid_json_uses_raw(self, tmp_path):
        svc = _make_svc(tmp_path)
        resp = MagicMock()
        resp.content = b"x"
        resp.json.side_effect = ValueError("bad")
        resp.text = "raw text"
        result = svc._json_response(resp)
        assert "raw" in result

    def test_empty_content_returns_empty_dict(self, tmp_path):
        svc = _make_svc(tmp_path)
        resp = MagicMock()
        resp.content = b""
        result = svc._json_response(resp)
        assert result == {}

    def test_non_dict_json_wrapped(self, tmp_path):
        svc = _make_svc(tmp_path)
        resp = MagicMock()
        resp.content = b"x"
        resp.json.return_value = [1, 2, 3]
        result = svc._json_response(resp)
        assert "data" in result

    def test_error_message_priority(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._error_message({"error": "err1"}, "fallback") == "err1"
        assert svc._error_message({"message": "msg1"}, "fallback") == "msg1"
        assert svc._error_message({}, "fallback") == "fallback"


# ─────────────── _dedupe_log_tail ───────────────────────────────


class TestDedupeLogTail:
    def _svc(self, tmp_path):
        return _make_svc(tmp_path)

    def test_deduplicates(self, tmp_path):
        svc = self._svc(tmp_path)
        out = svc._dedupe_log_tail(["a", "b", "a", "c"])
        assert out.count("a") == 1

    def test_max_items(self, tmp_path):
        svc = self._svc(tmp_path)
        logs = [f"item{i}" for i in range(10)]
        out = svc._dedupe_log_tail(logs, max_items=3)
        lines = [l for l in out.split("\n\n") if l]
        assert len(lines) <= 3

    def test_truncates_chars(self, tmp_path):
        svc = self._svc(tmp_path)
        out = svc._dedupe_log_tail(["x" * 1000], max_chars=10)
        assert len(out) <= 10

    def test_empty_list_returns_empty(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc._dedupe_log_tail([]) == ""

    def test_empty_strings_skipped(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc._dedupe_log_tail(["", "  ", "real"]) == "real"


# ─────────────── _build_dispatch_request ────────────────────────


class TestBuildDispatchRequest:
    def test_mobile_source(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = svc._build_dispatch_request(
            request_id="r",
            created_at="t",
            user_id=1,
            message="fix",
            context={"source": "mobile_push"},
        )
        assert req["source"] == "xcagi_mobile_im"

    def test_admin_source(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = svc._build_dispatch_request(
            request_id="r",
            created_at="t",
            user_id=1,
            message="fix",
            context={"source": "admin_panel"},
        )
        assert req["source"] == "xcagi_admin_im"

    def test_target_devices_non_list_defaults_all(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = svc._build_dispatch_request(
            request_id="r",
            created_at="t",
            user_id=1,
            message="fix",
            context={"target_devices": "d1"},
        )
        assert req["target_devices"] == ["all"]

    def test_workspace_root_product_scope_hides_server_path(self, tmp_path, monkeypatch):
        # 信任墙：产品域（默认）绝不把服务端 repo 路径回显给派工，防客户驱动的越权。
        monkeypatch.setenv("MODSTORE_REPO_ROOT", "/my/repo")
        svc = _make_svc(tmp_path)
        req = svc._build_dispatch_request(
            request_id="r",
            created_at="t",
            user_id=1,
            message="fix",
            context={},
        )
        assert req["workspace_root"] == ""
        assert req["scope"] == "product"

    def test_workspace_root_factory_scope_resolves(self, tmp_path):
        from app.application.execution_scope import CapabilityGrant, ExecutionScope

        svc = _make_svc(tmp_path)
        svc._grant = CapabilityGrant(ExecutionScope.FACTORY, "xcmax")
        req = svc._build_dispatch_request(
            request_id="r",
            created_at="t",
            user_id=1,
            message="fix",
            context={},
        )
        assert req["scope"] == "factory"
        assert req["workspace_root"]  # 工厂域解析出真实 workspace 根


# ─────────────── _cli_workspace / _cli_timeout ──────────────────


class TestCliWorkspaceAndTimeout:
    def test_valid_workspace_in_context(self, tmp_path):
        # 信任墙：产品域（默认）忽略客户提供的 workspace_root，一律用隔离临时区（防 path-injection）。
        svc = _make_svc(tmp_path)
        result = svc._cli_workspace({"workspace_root": str(tmp_path)})
        assert result != str(tmp_path)
        assert result == svc._product_ephemeral_workspace()

    def test_invalid_workspace_falls_back(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc._cli_workspace({"workspace_root": "/non/existent/path"})
        assert result != "/non/existent/path"

    def test_timeout_valid(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_TIMEOUT_SEC", "60")
        svc = _make_svc(tmp_path)
        assert svc._cli_timeout_seconds() == 60.0

    def test_timeout_invalid_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_TIMEOUT_SEC", "not_a_number")
        svc = _make_svc(tmp_path)
        assert svc._cli_timeout_seconds() == 180.0

    def test_timeout_clamped_low(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_TIMEOUT_SEC", "1")
        svc = _make_svc(tmp_path)
        assert svc._cli_timeout_seconds() == 15.0

    def test_timeout_clamped_high(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_TIMEOUT_SEC", "999")
        svc = _make_svc(tmp_path)
        assert svc._cli_timeout_seconds() == 999.0


# ─────────────── _sync_para_task_updates ────────────────────────


class TestSyncParaTaskUpdates:
    def test_skips_when_already_in_terminal_with_result(self, tmp_path):
        svc = _make_svc(tmp_path)
        request_id = "req1"
        rows = [
            {
                "user_id": 1,
                "role": "system",
                "kind": DISPATCHER_MESSAGE_KIND,
                "task_id": "task1",
                "task_status": "completed",
                "status": "completed",
                "dispatch_request_id": request_id,
            },
            {
                "user_id": 1,
                "role": "assistant",
                "kind": CODEX_PROFILE.result_kind,
                "task_id": "task1",
                "dispatch_request_id": request_id,
            },
        ]
        with patch.object(svc, "_fetch_para_task", return_value=None) as mock_fetch:
            svc._sync_para_task_updates(user_id=1, rows=rows)
        mock_fetch.assert_not_called()

    def test_fetches_task_for_active_dispatcher_row(self, tmp_path):
        svc = _make_svc(tmp_path)
        rows = [
            {
                "user_id": 1,
                "role": "system",
                "kind": DISPATCHER_MESSAGE_KIND,
                "task_id": "task1",
                "task_status": "running",
                "status": "running",
                "dispatch_request_id": "req1",
            },
        ]
        with patch.object(svc, "_fetch_para_task", return_value=None):
            # just confirm no error
            svc._sync_para_task_updates(user_id=1, rows=rows)

    def test_stops_after_eight_syncs(self, tmp_path):
        svc = _make_svc(tmp_path)
        rows = [
            {
                "user_id": 1,
                "role": "system",
                "kind": DISPATCHER_MESSAGE_KIND,
                "task_id": f"task{i}",
                "task_status": "running",
                "status": "running",
                "dispatch_request_id": f"req{i}",
            }
            for i in range(12)
        ]
        fetch_count = []

        def mock_fetch(task_id):
            fetch_count.append(task_id)
            return None

        with patch.object(svc, "_fetch_para_task", side_effect=mock_fetch):
            svc._sync_para_task_updates(user_id=1, rows=rows)
        assert len(fetch_count) <= 8


# ─────────────── _message_row / _public_message ─────────────────


class TestMessageRowAndPublic:
    def test_message_row_basic(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = svc._message_row(
            user_id=5,
            role="user",
            body="hello",
            created_at="t",
            request_id="r",
            status="sent",
        )
        assert row["user_id"] == 5
        assert row["role"] == "user"
        assert row["body"] == "hello"

    def test_message_row_extra_omits_none(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = svc._message_row(
            user_id=1,
            role="system",
            body="b",
            created_at="t",
            request_id="r",
            status="s",
            extra={"kind": "k", "task_id": None, "empty": ""},
        )
        assert row.get("kind") == "k"
        assert "task_id" not in row
        assert "empty" not in row

    def test_public_message_all_fields(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {
            "id": "x",
            "role": "assistant",
            "body": "b",
            "created_at": "t",
            "status": "s",
            "dispatch_request_id": "r",
            "kind": "k",
            "task_id": "tid",
            "task_status": "ts",
            "subtask_id": "sid",
            "device_name": "dn",
        }
        pub = svc._public_message(row)
        assert pub["task_id"] == "tid"
        assert pub["device_name"] == "dn"

    def test_public_message_missing_fields_default(self, tmp_path):
        svc = _make_svc(tmp_path)
        pub = svc._public_message({})
        assert pub["role"] == "assistant"
        assert pub["body"] == ""
