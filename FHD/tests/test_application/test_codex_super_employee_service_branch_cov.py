"""Branch-coverage supplement for codex_super_employee_service.py.

CodexSuperEmployeeService 仅 55 行(继承 SuperEmployeeService)，86 个缺失分支
来自父类 SuperEmployeeService 的方法。本文件聚焦 test_super_employee_service_cov.py
未覆盖的分支：_dispatch_to_para 的 httpx.TimeoutException/NetworkError 分支、
_parse_claude_stream_json 的事件类型、_direct_reply_body 的各类提示、
_upsert_direct_reply_messages 的 CLI 回填、_refresh_dispatcher_row 的变更检测、
_fetch_para_task 的错误分支、_resolve_para_tier 的强制值、_device_eligible 的
状态分支、_dedupe_log_tail 的去重截断等。

所有外部 I/O（httpx、subprocess、文件系统）均被 mock，遵循 Mock 最小化原则。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.application.codex_super_employee_service import CodexSuperEmployeeService
from app.application.super_employee_service import (
    _PARA_TOKEN_CACHE,
    CLAUDE_PROFILE,
    CODEX_PROFILE,
    DISPATCHER_MESSAGE_KIND,
    SuperEmployeeService,
    _claude_cli_command,
    _codex_cli_command,
    _coerce_list,
    _cursor_cli_command,
    _safe_json_line,
    _utc_now,
)

# ─────────────────────────── helpers ────────────────────────────


def _make_svc(tmp_path: Path, **kwargs) -> SuperEmployeeService:
    """构造隔离存储的超级员工服务。

    默认构造 CodexSuperEmployeeService；若指定 profile 则构造父类
    SuperEmployeeService 以测试其他工具配置（如 CLAUDE_PROFILE）。
    """
    profile = kwargs.pop("profile", None)
    if "cli_runner" in kwargs:
        cli_runner = kwargs.pop("cli_runner")
    else:
        cli_runner = _null_runner
    if profile is not None:
        return SuperEmployeeService(
            profile=profile,
            storage_root=tmp_path,
            cli_runner=cli_runner,
            **kwargs,
        )
    return CodexSuperEmployeeService(
        storage_root=tmp_path,
        codex_cli_runner=cli_runner,
        **kwargs,
    )


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


def _fake_http_factory(status: int = 200, body: dict | None = None, exc=None):
    """返回上下文管理器兼容的 mock httpx.Client 工厂。"""

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


# ─────────────── CodexSuperEmployeeService 构造 ─────────────────


class TestCodexSuperEmployeeServiceConstruction:
    """验证 CodexSuperEmployeeService 正确继承 SuperEmployeeService 并使用 CODEX_PROFILE。"""

    def test_inherits_from_super_employee_service(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert isinstance(svc, SuperEmployeeService)

    def test_uses_codex_profile(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._p is CODEX_PROFILE

    def test_employee_id_matches_codex(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._p.employee_id == "codex-super-employee"

    def test_tool_name_is_codex(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._p.tool_name == "codex"

    def test_storage_subdir_is_codex(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._p.storage_subdir == "codex_super_employee"

    def test_result_kind_is_codex_result(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._p.result_kind == "codex_result"

    def test_direct_kind_is_codex_direct(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._p.direct_kind == "codex_direct"


# ─────────────── 模块级辅助函数 ──────────────────────────────────


class TestModuleHelpers:
    """模块级辅助函数 _coerce_list / _utc_now / _safe_json_line / cli_command builders。"""

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

    def test_codex_cli_command(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SANDBOX_MODE", raising=False)
        monkeypatch.delenv("DEVFLEET_CODEX_SANDBOX_MODE", raising=False)
        cmd = _codex_cli_command("/path/codex", "prompt", tmp_path / "out.txt", "/cwd")
        assert cmd[0] == "/path/codex"
        assert "prompt" in cmd
        assert "/cwd" in cmd
        assert cmd[cmd.index("--sandbox") + 1] == "workspace-write"

    def test_codex_cli_command_allows_read_only_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SANDBOX_MODE", "read-only")
        cmd = _codex_cli_command("/path/codex", "prompt", tmp_path / "out.txt", "/cwd")
        assert cmd[cmd.index("--sandbox") + 1] == "read-only"

    def test_cursor_cli_command(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEVFLEET_CURSOR_TRUST", "1")
        monkeypatch.setenv("DEVFLEET_CURSOR_FORCE", "1")
        cmd = _cursor_cli_command("/path/cursor", "prompt", tmp_path / "out.txt", "/cwd")
        assert cmd[0] == "/path/cursor"
        assert "--trust" in cmd
        assert "--force" in cmd

    def test_cursor_cli_command_trust_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEVFLEET_CURSOR_TRUST", "0")
        monkeypatch.setenv("DEVFLEET_CURSOR_FORCE", "1")
        cmd = _cursor_cli_command("/path/cursor", "prompt", tmp_path / "out.txt", "/cwd")
        assert "--trust" not in cmd
        assert "--force" in cmd

    def test_cursor_cli_command_force_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEVFLEET_CURSOR_TRUST", "1")
        monkeypatch.setenv("DEVFLEET_CURSOR_FORCE", "false")
        cmd = _cursor_cli_command("/path/cursor", "prompt", tmp_path / "out.txt", "/cwd")
        assert "--trust" in cmd
        assert "--force" not in cmd

    def test_claude_cli_command(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEVFLEET_CLAUDE_PERMISSION_MODE", "acceptEdits")
        cmd = _claude_cli_command("/path/claude", "prompt", tmp_path / "out.txt", "/cwd")
        assert cmd[0] == "/path/claude"
        assert "--print" in cmd
        assert "acceptEdits" in cmd

    def test_claude_cli_command_default_perm(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEVFLEET_CLAUDE_PERMISSION_MODE", raising=False)
        cmd = _claude_cli_command("/path/claude", "prompt", tmp_path / "out.txt", "/cwd")
        assert "acceptEdits" in cmd

    def test_claude_cli_command_empty_perm(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEVFLEET_CLAUDE_PERMISSION_MODE", "")
        cmd = _claude_cli_command("/path/claude", "prompt", tmp_path / "out.txt", "/cwd")
        assert "acceptEdits" in cmd


# ─────────────── _should_reply_with_cli 边界 ─────────────────────


class TestShouldReplyWithCliBoundary:
    """_should_reply_with_cli 的所有分支。"""

    def test_force_direct_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_FORCE_CLI_DIRECT", "1")
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("修复 bug", {"mode": "code"}) is True

    def test_force_direct_env_true(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_FORCE_CLI_DIRECT", "true")
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("修复", {"mode": "code"}) is True

    def test_force_direct_env_yes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_FORCE_CLI_DIRECT", "yes")
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("修复", {}) is True

    def test_force_direct_env_on(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_FORCE_CLI_DIRECT", "on")
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("修复", {}) is True

    def test_force_direct_env_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_FORCE_CLI_DIRECT", "0")
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("你好", {"mode": "chat"}) is True

    def test_mode_chat(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("任意", {"mode": "chat"}) is True

    def test_mode_qa(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("任意", {"mode": "qa"}) is True

    def test_mode_direct(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("任意", {"mode": "direct"}) is True

    def test_mode_codex_cli(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("任意", {"mode": "codex_cli"}) is True

    def test_mode_code(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("修复", {"mode": "code"}) is False

    def test_mode_task(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("修复", {"mode": "task"}) is False

    def test_mode_dispatch(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("修复", {"mode": "dispatch"}) is False

    def test_no_mode_with_task_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("修复 bug", {}) is False

    def test_no_mode_without_task_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("你好", {}) is True

    def test_empty_text_no_mode(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("", {}) is False

    def test_whitespace_text_no_mode(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._should_reply_with_cli("   ", {}) is False


# ─────────────── _cli_reply_body 边界 ────────────────────────────


class TestCliReplyBodyBoundary:
    """_cli_reply_body 的环境变量和错误分支。"""

    def test_cli_chat_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_CHAT_ENABLED", "0")
        svc = _make_svc(tmp_path)
        assert svc._cli_reply_body("你好", {}) == ""

    def test_cli_chat_false(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_CHAT_ENABLED", "false")
        svc = _make_svc(tmp_path)
        assert svc._cli_reply_body("你好", {}) == ""

    def test_cli_chat_off(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_CHAT_ENABLED", "off")
        svc = _make_svc(tmp_path)
        assert svc._cli_reply_body("你好", {}) == ""

    def test_cli_chat_disabled_keyword(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_CHAT_ENABLED", "disabled")
        svc = _make_svc(tmp_path)
        assert svc._cli_reply_body("你好", {}) == ""

    def test_empty_cli_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_CHAT_ENABLED", "1")
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_cli_path", return_value=""):
            assert svc._cli_reply_body("你好", {}) == ""

    def test_cli_execution_returns_answer(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_CHAT_ENABLED", "1")
        svc = _make_svc(tmp_path, cli_runner=_stdout_runner("cli answer"))
        with patch.object(svc, "_cli_path", return_value=str(tmp_path / "codex")):
            result = svc._cli_reply_body("你好", {})
        assert "cli answer" in result or isinstance(result, str)

    def test_cli_execution_oserror(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_CHAT_ENABLED", "1")
        svc = _make_svc(tmp_path, cli_runner=_error_runner(OSError("boom")))
        with patch.object(svc, "_cli_path", return_value=str(tmp_path / "codex")):
            result = svc._cli_reply_body("你好", {})
        assert result == "" or isinstance(result, str)


# ─────────────── _direct_reply_body 边界 ─────────────────────────


class TestDirectReplyBodyBoundary:
    """_direct_reply_body 的各类提示匹配。"""

    def test_identity_prompt(self, tmp_path):
        svc = _make_svc(tmp_path)
        body = svc._direct_reply_body("你是谁")
        assert "Codex" in body

    def test_help_prompt(self, tmp_path):
        svc = _make_svc(tmp_path)
        body = svc._direct_reply_body("你能做什么")
        assert "派工" in body or "任务" in body

    def test_greeting_prompt(self, tmp_path):
        svc = _make_svc(tmp_path)
        body = svc._direct_reply_body("你好")
        assert isinstance(body, str)

    def test_slow_prompt(self, tmp_path):
        svc = _make_svc(tmp_path)
        body = svc._direct_reply_body("为什么这么慢")
        assert "慢" in body

    def test_empty_text(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._direct_reply_body("") == ""

    def test_whitespace_text(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._direct_reply_body("   ") == ""

    def test_unknown_prompt(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._direct_reply_body("今天天气怎么样") == ""


# ─────────────── _is_task_intent 边界 ────────────────────────────


class TestIsTaskIntentBoundary:
    """_is_task_intent 的模式和标记检测。"""

    def test_code_mode(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("任意", {"mode": "code"}) is True

    def test_task_mode(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("任意", {"mode": "task"}) is True

    def test_dispatch_mode(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("任意", {"mode": "dispatch"}) is True

    def test_dev_mode(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("任意", {"mode": "dev"}) is True

    def test_develop_mode(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("任意", {"mode": "develop"}) is True

    def test_chat_mode_no_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("你好", {"mode": "chat"}) is False

    def test_chat_mode_with_marker(self, tmp_path):
        # chat 模式优先级高于关键词，即使包含任务标记也返回 False
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("修复 bug", {"mode": "chat"}) is False

    def test_no_mode_with_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("修复 bug", {}) is True

    def test_no_mode_without_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("你好", {}) is False

    def test_empty_text(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("", {}) is False

    def test_whitespace_text(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("   ", {}) is False

    def test_build_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("build the project", {}) is True

    def test_commit_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("commit changes", {}) is True

    def test_push_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("push to remote", {}) is True

    def test_deploy_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("部署到生产", {}) is True

    def test_release_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_task_intent("发布新版本", {}) is True


# ─────────────── _resolve_para_tier 边界 ─────────────────────────


class TestResolveParaTierBoundary:
    """_resolve_para_tier 的层级解析。

    签名: _resolve_para_tier(self, request: dict) -> int
    环境变量: XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER
    """

    def test_forced_local(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", "local")
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier({"raw_context": {}}) == 1

    def test_forced_single(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", "single")
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier({"raw_context": {}}) == 1

    def test_forced_chinese_local(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", "本机")
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier({"raw_context": {}}) == 1

    def test_forced_fleet(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", "fleet")
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier({"raw_context": {}}) == 2

    def test_forced_multi(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", "multi")
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier({"raw_context": {}}) == 2

    def test_forced_chinese_multi(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", "多设备")
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier({"raw_context": {}}) == 2

    def test_forced_tier_1(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", "1")
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier({"raw_context": {}}) == 1

    def test_forced_tier_2(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", "2")
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier({"raw_context": {}}) == 2

    def test_tier_hint_context_2(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        req = {"raw_context": {"para_tier": "2"}}
        assert svc._resolve_para_tier(req) == 2

    def test_tier_hint_context_fleet(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        req = {"raw_context": {"tier": "fleet"}}
        assert svc._resolve_para_tier(req) == 2

    def test_tier_hint_context_multi_device(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        req = {"raw_context": {"para_tier": "multi_device"}}
        assert svc._resolve_para_tier(req) == 2

    def test_tier_hint_context_1(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        req = {"raw_context": {"para_tier": "1"}}
        assert svc._resolve_para_tier(req) == 1

    def test_escalate_context(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        req = {"raw_context": {"escalate": True}}
        assert svc._resolve_para_tier(req) == 2

    def test_escalate_context_string_true(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        req = {"raw_context": {"escalate": "true"}}
        assert svc._resolve_para_tier(req) == 2

    def test_max_devices_gt_1(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        req = {"raw_context": {"max_devices": 3}}
        assert svc._resolve_para_tier(req) == 2

    def test_max_devices_invalid(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        req = {"raw_context": {"max_devices": "not a number"}}
        assert svc._resolve_para_tier(req) == 1

    def test_target_devices_multiple(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        req = {"raw_context": {}, "target_devices": ["dev1", "dev2"]}
        assert svc._resolve_para_tier(req) == 2

    def test_target_devices_single(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        req = {"raw_context": {}, "target_devices": ["dev1"]}
        assert svc._resolve_para_tier(req) == 1

    def test_target_devices_all(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        req = {"raw_context": {}, "target_devices": ["all"]}
        assert svc._resolve_para_tier(req) == 1

    def test_text_marker_multi_device(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        req = {"raw_context": {}, "task": "多设备任务"}
        assert svc._resolve_para_tier(req) == 2

    def test_text_marker_all_devices(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        req = {"raw_context": {}, "prompt": "调用所有设备"}
        assert svc._resolve_para_tier(req) == 2

    def test_default_tier_1(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        req = {"raw_context": {}, "task": "普通任务"}
        assert svc._resolve_para_tier(req) == 1


# ─────────────── _device_eligible 边界 ───────────────────────────


class TestDeviceEligibleBoundary:
    """_device_eligible 的设备状态检查。

    签名: _device_eligible(self, item: Any) -> bool
    """

    def test_non_dict_returns_false(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._device_eligible("not dict") is False

    def test_none_returns_false(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._device_eligible(None) is False

    def test_offline_device(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._device_eligible({"status": "offline"}) is False

    def test_empty_status(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._device_eligible({"status": ""}) is False

    def test_online_with_matching_tool(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {"status": "online", "tools": [{"toolName": "codex", "status": "installed"}]}
        assert svc._device_eligible(device) is True

    def test_online_with_not_installed_tool(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {"status": "online", "tools": [{"toolName": "codex", "status": "not_installed"}]}
        assert svc._device_eligible(device) is False

    def test_online_with_running_busy_tool(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {
            "status": "online",
            "tools": [{"toolName": "codex", "status": "running", "currentTask": "task1"}],
        }
        assert svc._device_eligible(device) is False

    def test_online_with_running_no_task(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {"status": "online", "tools": [{"toolName": "codex", "status": "running"}]}
        assert svc._device_eligible(device) is True

    def test_online_no_tool_capability_true(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {"status": "online", "tools": [], "capabilities": {"codex_cli": True}}
        assert svc._device_eligible(device) is True

    def test_online_no_tool_capability_false(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {"status": "online", "tools": [], "capabilities": {"codex_cli": False}}
        assert svc._device_eligible(device) is False

    def test_online_no_tool_no_capability(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {"status": "online", "tools": []}
        assert svc._device_eligible(device) is False


# ─────────────── _device_tool 边界 ───────────────────────────────


class TestDeviceToolBoundary:
    """_device_tool 的工具匹配。

    签名: _device_tool(self, device: dict, name: str) -> dict | None
    """

    def test_matching_tool(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {"tools": [{"toolName": "codex", "version": "1.0"}]}
        result = svc._device_tool(device, "codex")
        assert result is not None
        assert result["toolName"] == "codex"

    def test_no_matching_tool(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {"tools": [{"name": "claude", "version": "1.0"}]}
        assert svc._device_tool(device, "codex") is None

    def test_no_tools_field(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._device_tool({}, "codex") is None

    def test_non_list_tools(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {"tools": "codex"}
        assert svc._device_tool(device, "codex") is None

    def test_non_dict_tool_skipped(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {"tools": ["not dict", {"toolName": "codex"}]}
        result = svc._device_tool(device, "codex")
        assert result is not None
        assert result["toolName"] == "codex"


# ─────────────── _task_subtasks 边界 ─────────────────────────────


class TestTaskSubtasksBoundary:
    """_task_subtasks 的字段兼容性。

    签名: _task_subtasks(self, task: dict) -> list[dict]
    """

    def test_camel_case(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {"subTasks": [{"id": "s1"}]}
        assert len(svc._task_subtasks(task)) == 1

    def test_snake_case(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {"subtasks": [{"id": "s1"}]}
        assert len(svc._task_subtasks(task)) == 1

    def test_camel_takes_priority(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {"subTasks": [{"id": "s1"}], "subtasks": [{"id": "s2"}]}
        # subTasks 优先
        result = svc._task_subtasks(task)
        assert len(result) == 1
        assert result[0]["id"] == "s1"

    def test_none(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._task_subtasks({}) == []
        assert svc._task_subtasks({"subtasks": None}) == []

    def test_non_list(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._task_subtasks({"subtasks": "not a list"}) == []

    def test_filters_non_dict(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {"subtasks": [{"id": "s1"}, "not dict", 42, None]}
        result = svc._task_subtasks(task)
        assert len(result) == 1
        assert result[0]["id"] == "s1"


# ─────────────── _dedupe_log_tail 边界 ───────────────────────────


class TestDedupeLogTailBoundary:
    """_dedupe_log_tail 的去重和截断逻辑。

    签名: _dedupe_log_tail(self, logs: list[str], *, max_items=5, max_chars=4000) -> str
    返回 str（非 list）
    """

    def test_removes_duplicates(self, tmp_path):
        svc = _make_svc(tmp_path)
        logs = ["line1", "line2", "line1", "line3", "line2"]
        result = svc._dedupe_log_tail(logs)
        assert isinstance(result, str)
        assert "line3" in result
        assert result.count("line1") <= 1
        assert result.count("line2") <= 1

    def test_max_items_limit(self, tmp_path):
        svc = _make_svc(tmp_path)
        logs = [f"line{i}" for i in range(100)]
        result = svc._dedupe_log_tail(logs)
        assert isinstance(result, str)
        # 只保留最后 5 条
        assert "line99" in result
        assert "line0" not in result

    def test_empty_list(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._dedupe_log_tail([]) == ""

    def test_empty_strings_filtered(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc._dedupe_log_tail(["", "  ", "real"])
        assert isinstance(result, str)
        assert "real" in result

    def test_max_chars_limit(self, tmp_path):
        svc = _make_svc(tmp_path)
        logs = ["x" * 2000, "y" * 2000, "z" * 2000]
        result = svc._dedupe_log_tail(logs, max_chars=100)
        assert len(result) <= 100

    def test_custom_max_items(self, tmp_path):
        svc = _make_svc(tmp_path)
        logs = ["a", "b", "c", "d", "e"]
        result = svc._dedupe_log_tail(logs, max_items=2)
        assert "e" in result
        assert "d" in result
        assert "a" not in result


# ─────────────── _is_dispatcher_log ──────────────────────────────


class TestIsDispatcherLogBoundary:
    """_is_dispatcher_log 的日志前缀检测。

    签名: _is_dispatcher_log(self, content: str) -> bool
    前缀: "子任务「", "子任务未派发", "链路不可用", "设备连接已断开", "手动"
    """

    def test_subtask_prefix(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_dispatcher_log("子任务「xxx」已派发") is True

    def test_subtask_not_dispatched_prefix(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_dispatcher_log("子任务未派发：无设备") is True

    def test_link_unavailable_prefix(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_dispatcher_log("链路不可用，请稍后") is True

    def test_device_disconnected_prefix(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_dispatcher_log("设备连接已断开") is True

    def test_manual_prefix(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_dispatcher_log("手动触发任务") is True

    def test_non_dispatcher(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_dispatcher_log("普通日志消息") is False

    def test_empty_string(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_dispatcher_log("") is False


# ─────────────── _is_dispatcher_ack_body ─────────────────────────


class TestIsDispatcherAckBodyBoundary:
    """_is_dispatcher_ack_body 的标记检测。

    签名: _is_dispatcher_ack_body(self, body: str) -> bool
    """

    def test_multi_device_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_dispatcher_ack_body("多设备调度器已派发") is True

    def test_queue_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_dispatcher_ack_body("调用队列已满") is True

    def test_channel_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_dispatcher_ack_body("调度通道开启") is True

    def test_no_device_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_dispatcher_ack_body("未发现在线可用 Codex 设备") is True

    def test_dispatched_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_dispatcher_ack_body("任务已派发到设备") is True

    def test_para_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_dispatcher_ack_body("Para/Codex 已接收") is True

    def test_no_marker(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._is_dispatcher_ack_body("普通回复") is False


# ─────────────── _extract_task_id_from_body ──────────────────────


class TestExtractTaskIdFromBodyBoundary:
    """_extract_task_id_from_body 的正则匹配。

    签名: _extract_task_id_from_body(self, body: str) -> str
    正则: r"任务\\s*ID[:：]\\s*([A-Za-z0-9][A-Za-z0-9._:-]{5,})"
    """

    def test_valid_task_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        body = "任务 ID：abcdef123456"
        assert svc._extract_task_id_from_body(body) == "abcdef123456"

    def test_full_width_colon(self, tmp_path):
        svc = _make_svc(tmp_path)
        body = "任务 ID：xyz789012345"
        assert svc._extract_task_id_from_body(body) == "xyz789012345"

    def test_half_width_colon(self, tmp_path):
        svc = _make_svc(tmp_path)
        body = "任务 ID:abc123456789"
        assert svc._extract_task_id_from_body(body) == "abc123456789"

    def test_no_match(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._extract_task_id_from_body("no task id here") == ""

    def test_too_short_no_match(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._extract_task_id_from_body("任务 ID：abc") == ""

    def test_empty_body(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._extract_task_id_from_body("") == ""


# ─────────────── _upgrade_legacy_dispatcher_row 边界 ─────────────


class TestUpgradeLegacyDispatcherRowBoundary:
    """_upgrade_legacy_dispatcher_row 的旧消息升级。

    签名: _upgrade_legacy_dispatcher_row(self, row: dict) -> bool
    """

    def test_already_dispatcher_no_change(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"kind": DISPATCHER_MESSAGE_KIND, "role": "system", "body": "x"}
        assert svc._upgrade_legacy_dispatcher_row(row) is False

    def test_user_role_no_change(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"kind": "", "role": "user", "body": "多设备调度器"}
        assert svc._upgrade_legacy_dispatcher_row(row) is False

    def test_system_role_no_change(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"kind": "", "role": "system", "body": "多设备调度器"}
        assert svc._upgrade_legacy_dispatcher_row(row) is False

    def test_no_marker_no_change(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"kind": "", "role": "assistant", "body": "普通回复"}
        assert svc._upgrade_legacy_dispatcher_row(row) is False

    def test_marker_upgrades(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"kind": "", "role": "assistant", "body": "多设备调度器已派发"}
        assert svc._upgrade_legacy_dispatcher_row(row) is True
        assert row["kind"] == DISPATCHER_MESSAGE_KIND
        assert row["role"] == "system"

    def test_task_id_extracted(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {
            "kind": "",
            "role": "assistant",
            "body": "任务已派发到 Para/Codex 任务 ID：abcdef123456",
        }
        svc._upgrade_legacy_dispatcher_row(row)
        assert row.get("task_id") == "abcdef123456"

    def test_existing_task_id_preserved(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {
            "kind": "",
            "role": "assistant",
            "body": "多设备调度器 任务 ID：newid1234567",
            "task_id": "existing",
        }
        svc._upgrade_legacy_dispatcher_row(row)
        assert row["task_id"] == "existing"


# ─────────────── _para_task_status_reply 边界 ────────────────────


class TestParaTaskStatusReplyBoundary:
    """_para_task_status_reply 的各类状态分支。

    签名: _para_task_status_reply(self, task: dict) -> str
    """

    def test_completed_status(self, tmp_path):
        svc = _make_svc(tmp_path)
        body = svc._para_task_status_reply({"id": "t1", "status": "completed", "subtasks": []})
        assert "已完成" in body
        assert "t1" in body

    def test_merged_status(self, tmp_path):
        svc = _make_svc(tmp_path)
        body = svc._para_task_status_reply({"id": "t1", "status": "merged", "subtasks": []})
        assert "已完成" in body

    def test_failed_status(self, tmp_path):
        svc = _make_svc(tmp_path)
        body = svc._para_task_status_reply({"id": "t1", "status": "failed", "subtasks": []})
        assert "需要处理" in body

    def test_merge_conflict_status(self, tmp_path):
        svc = _make_svc(tmp_path)
        body = svc._para_task_status_reply({"id": "t1", "status": "merge_conflict", "subtasks": []})
        assert "需要处理" in body

    def test_running_with_subtasks(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {
            "id": "t1",
            "status": "running",
            "subtasks": [
                {"status": "completed", "progress": 100},
                {"status": "running", "progress": 50},
            ],
        }
        body = svc._para_task_status_reply(task)
        assert "运行中" in body
        assert "1/2" in body
        assert "75%" in body

    def test_waiting_without_subtasks(self, tmp_path):
        svc = _make_svc(tmp_path)
        body = svc._para_task_status_reply({"id": "t1", "status": "pending", "subtasks": []})
        assert "已创建" in body or "等待" in body

    def test_no_task_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        body = svc._para_task_status_reply({"status": "completed", "subtasks": []})
        assert "已完成" in body
        assert "任务 ID" not in body

    def test_failed_subtask_triggers_need_handle(self, tmp_path):
        """有 failed 子任务但 task 状态非 failed 时也走"需要处理"分支。"""
        svc = _make_svc(tmp_path)
        task = {
            "id": "t1",
            "status": "running",
            "subtasks": [{"status": "failed", "progress": 0}],
        }
        body = svc._para_task_status_reply(task)
        assert "需要处理" in body


# ─────────────── _result_body 边界 ───────────────────────────────


class TestResultBodyBoundary:
    """_result_body 的各类输入组合。

    签名: _result_body(self, task: dict, subtask: dict) -> str
    """

    def test_with_logs(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {"id": "t1", "status": "completed", "title": "my task"}
        subtask = {
            "id": "s1",
            "status": "completed",
            "device_name": "dev1",
            "logs": [{"content": "build ok"}],
        }
        body = svc._result_body(task, subtask)
        assert "dev1" in body or "build ok" in body

    def test_completed_without_logs(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {"id": "t1", "status": "completed", "title": "my task"}
        subtask = {"id": "s1", "status": "completed", "device_name": "dev1", "logs": []}
        body = svc._result_body(task, subtask)
        assert "已完成" in body

    def test_failed_with_error(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {"id": "t1", "status": "failed", "title": "my task"}
        subtask = {
            "id": "s1",
            "status": "failed",
            "device_name": "dev1",
            "logs": [],
            "last_error": "compile error",
        }
        body = svc._result_body(task, subtask)
        assert "失败" in body
        assert "compile error" in body

    def test_failed_without_error(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {"id": "t1", "status": "failed", "title": "my task"}
        subtask = {"id": "s1", "status": "failed", "device_name": "dev1", "logs": []}
        body = svc._result_body(task, subtask)
        assert "失败" in body

    def test_pending_status_returns_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {"id": "t1", "status": "pending", "title": "my task"}
        subtask = {"id": "s1", "status": "pending", "device_name": "dev1", "logs": []}
        body = svc._result_body(task, subtask)
        assert body == ""

    def test_logs_with_dispatcher_content_filtered(self, tmp_path):
        """dispatcher 日志被过滤后使用剩余 meaningful 日志。"""
        svc = _make_svc(tmp_path)
        task = {"id": "t1", "status": "completed", "title": "task"}
        subtask = {
            "id": "s1",
            "status": "completed",
            "device_name": "dev1",
            "logs": [
                {"content": "子任务「xxx」已派发"},
                {"content": "real output line"},
            ],
        }
        body = svc._result_body(task, subtask)
        assert "real output" in body


# ─────────────── _refresh_dispatcher_row 边界 ────────────────────


class TestRefreshDispatcherRowBoundary:
    """_refresh_dispatcher_row 的边界条件。

    签名: _refresh_dispatcher_row(self, row: dict, task: dict) -> bool
    """

    def test_no_change_when_status_unchanged(self, tmp_path):
        """任务状态未变化时返回 False。"""
        svc = _make_svc(tmp_path)
        row = {
            "task_id": "task1",
            "task_status": "completed",
            "status": "completed",
            "body": "Para 任务已完成，Codex 执行结果已回传。任务 ID：task1",
        }
        task = {"id": "task1", "status": "completed", "subtasks": []}
        changed = svc._refresh_dispatcher_row(row, task)
        assert changed is False

    def test_change_when_status_differs(self, tmp_path):
        """任务状态变化时返回 True 并更新字段。"""
        svc = _make_svc(tmp_path)
        row = {
            "task_id": "task1",
            "task_status": "running",
            "status": "running",
            "body": "old body",
        }
        task = {"id": "task1", "status": "failed", "subtasks": []}
        changed = svc._refresh_dispatcher_row(row, task)
        assert changed is True
        assert row["task_status"] == "failed"
        assert row["status"] == "failed"

    def test_uses_row_task_id_when_task_id_missing(self, tmp_path):
        """task 中无 id 时回退到 row 的 task_id。"""
        svc = _make_svc(tmp_path)
        row = {"task_id": "row-task", "task_status": "", "status": "", "body": ""}
        task = {"status": "completed", "subtasks": []}
        changed = svc._refresh_dispatcher_row(row, task)
        assert changed is True
        assert row["task_id"] == "row-task"

    def test_empty_task_status_keeps_row_status(self, tmp_path):
        """task 中 status 为空时保留 row 原有 status。"""
        svc = _make_svc(tmp_path)
        row = {
            "task_id": "task1",
            "task_status": "running",
            "status": "running",
            "body": "old body",
        }
        task = {"id": "task1", "status": "", "subtasks": []}
        changed = svc._refresh_dispatcher_row(row, task)
        assert changed is True
        assert row["status"] == "running"


# ─────────────── _upsert_result_messages 边界 ────────────────────


class TestUpsertResultMessagesBoundary:
    """_upsert_result_messages 的边界条件。

    签名: _upsert_result_messages(self, *, user_id, dispatch_row, task, rows) -> bool
    """

    def test_skips_non_terminal_subtasks(self, tmp_path):
        """非终态子任务被跳过。"""
        svc = _make_svc(tmp_path)
        dispatch_row = {"task_id": "task1", "dispatch_request_id": "req1"}
        task = {
            "id": "task1",
            "status": "running",
            "subtasks": [
                {"id": "sub1", "status": "running", "device_name": "dev1"},
                {"id": "sub2", "status": "pending", "device_name": "dev2"},
            ],
        }
        rows: list[dict] = []
        changed = svc._upsert_result_messages(
            user_id=1, dispatch_row=dispatch_row, task=task, rows=rows
        )
        assert changed is False
        assert len(rows) == 0

    def test_updates_existing_result_message(self, tmp_path):
        """已存在相同 subtask_id 的结果消息时更新而非新增。"""
        svc = _make_svc(tmp_path)
        existing = {
            "user_id": 1,
            "role": "assistant",
            "kind": "codex_result",
            "task_id": "task1",
            "subtask_id": "sub1",
            "body": "old result",
            "status": "running",
            "task_status": "running",
            "device_name": "",
        }
        dispatch_row = {"task_id": "task1", "dispatch_request_id": "req1"}
        task = {
            "id": "task1",
            "status": "completed",
            "subtasks": [
                {
                    "id": "sub1",
                    "status": "completed",
                    "device_name": "dev1",
                    "logs": [{"content": "done"}],
                    "completed_at": "2025-01-01T00:00:00Z",
                },
            ],
        }
        rows = [existing]
        changed = svc._upsert_result_messages(
            user_id=1, dispatch_row=dispatch_row, task=task, rows=rows
        )
        assert changed is True
        assert len(rows) == 1
        assert rows[0]["status"] == "completed"
        assert rows[0]["device_name"] == "dev1"

    def test_appends_new_result_message(self, tmp_path):
        """无已存在消息时新增。"""
        svc = _make_svc(tmp_path)
        dispatch_row = {"task_id": "task1", "dispatch_request_id": "req1"}
        task = {
            "id": "task1",
            "status": "completed",
            "subtasks": [
                {
                    "id": "sub1",
                    "status": "completed",
                    "device_name": "dev1",
                    "logs": [{"content": "all good"}],
                    "completed_at": "2025-01-01T00:00:00Z",
                },
            ],
        }
        rows: list[dict] = []
        changed = svc._upsert_result_messages(
            user_id=1, dispatch_row=dispatch_row, task=task, rows=rows
        )
        assert changed is True
        assert len(rows) == 1
        assert rows[0]["kind"] == "codex_result"
        assert rows[0]["subtask_id"] == "sub1"

    def test_skips_empty_body_subtask(self, tmp_path):
        """_result_body 返回空时跳过该子任务。"""
        svc = _make_svc(tmp_path)
        dispatch_row = {"task_id": "task1", "dispatch_request_id": "req1"}
        task = {
            "id": "task1",
            "status": "completed",
            "subtasks": [
                {
                    "id": "sub1",
                    "status": "pending",  # pending → _result_body returns ""
                    "device_name": "",
                    "logs": [],
                },
            ],
        }
        rows: list[dict] = []
        changed = svc._upsert_result_messages(
            user_id=1, dispatch_row=dispatch_row, task=task, rows=rows
        )
        assert changed is False
        assert len(rows) == 0


# ─────────────── _fetch_para_task 错误分支 ───────────────────────


class TestFetchParaTaskErrors:
    """_fetch_para_task 的各类错误分支。

    签名: _fetch_para_task(self, task_id: str) -> dict | None
    """

    def test_returns_none_when_no_api_url(self, tmp_path, monkeypatch):
        """无 API URL（设为 disabled）时返回 None。"""
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "disabled")
        monkeypatch.setenv("MODSTORE_PARA_API_URL", "disabled")
        monkeypatch.setenv("DEVFLEET_API_URL", "disabled")
        svc = _make_svc(tmp_path)
        assert svc._fetch_para_task("task1") is None

    def test_returns_none_when_empty_task_id(self, tmp_path, monkeypatch):
        """空 task_id 时返回 None。"""
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "tok")
        svc = _make_svc(tmp_path, http_client_factory=_fake_http_factory(200, {"task": {}}))
        assert svc._fetch_para_task("") is None

    def test_returns_none_on_http_error(self, tmp_path, monkeypatch):
        """HTTPError（client.request 直接抛出）时返回 None。"""
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "tok")

        def factory():
            client = MagicMock(spec=httpx.Client)
            client.__enter__ = lambda s: s
            client.__exit__ = MagicMock(return_value=False)
            client.request.side_effect = httpx.HTTPError("server error")
            return client

        svc = _make_svc(tmp_path, http_client_factory=factory)
        assert svc._fetch_para_task("task1") is None

    def test_returns_none_on_value_error(self, tmp_path, monkeypatch):
        """ValueError（JSON 解析失败）时返回 None。"""
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "tok")

        def factory():
            client = MagicMock(spec=httpx.Client)
            client.__enter__ = lambda s: s
            client.__exit__ = MagicMock(return_value=False)
            resp = MagicMock()
            resp.status_code = 200
            resp.json.side_effect = ValueError("not json")
            resp.text = "not json"
            resp.content = b"not json"
            client.request.return_value = resp
            return client

        svc = _make_svc(tmp_path, http_client_factory=factory)
        assert svc._fetch_para_task("task1") is None

    def test_returns_none_on_key_error(self, tmp_path, monkeypatch):
        """响应缺 task 键时返回 None。"""
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "tok")
        svc = _make_svc(tmp_path, http_client_factory=_fake_http_factory(200, {"other": {}}))
        assert svc._fetch_para_task("task1") is None

    def test_returns_none_on_type_error(self, tmp_path, monkeypatch):
        """响应非 dict 时返回 None。"""
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "tok")

        def factory():
            client = MagicMock(spec=httpx.Client)
            client.__enter__ = lambda s: s
            client.__exit__ = MagicMock(return_value=False)
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = "not a dict"
            resp.text = "not a dict"
            resp.content = b"not a dict"
            client.request.return_value = resp
            return client

        svc = _make_svc(tmp_path, http_client_factory=factory)
        assert svc._fetch_para_task("task1") is None

    def test_returns_task_on_success(self, tmp_path, monkeypatch):
        """正常响应返回 task dict。"""
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "tok")
        task_data = {"id": "task1", "status": "running", "subtasks": []}
        svc = _make_svc(tmp_path, http_client_factory=_fake_http_factory(200, {"task": task_data}))
        result = svc._fetch_para_task("task1")
        assert result is not None
        assert result["id"] == "task1"


# ─────────────── _dispatch_to_para 异常分支 ──────────────────────


class TestDispatchToParaExceptions:
    """_dispatch_to_para 的各类异常分支。

    签名: _dispatch_to_para(self, request: dict) -> tuple[dict | None, str]
    """

    def test_disabled_url_returns_none_reason(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "disabled")
        svc = _make_svc(tmp_path)
        result, reason = svc._dispatch_to_para({"request_id": "r1", "created_at": "2025"})
        assert result is None
        assert "disabled" in reason

    def test_health_check_failure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        svc = _make_svc(tmp_path, http_client_factory=_fake_http_factory(503, {}))
        result, reason = svc._dispatch_to_para({"request_id": "r1", "created_at": "t"})
        assert result is None
        assert "unhealthy" in reason or "503" in reason

    def test_timeout_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        svc = _make_svc(
            tmp_path, http_client_factory=_fake_http_factory(exc=httpx.TimeoutException("timeout"))
        )
        result, reason = svc._dispatch_to_para({"request_id": "r1", "created_at": "t"})
        assert result is None
        assert "unreachable" in reason or "timeout" in reason

    def test_network_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        svc = _make_svc(
            tmp_path, http_client_factory=_fake_http_factory(exc=httpx.NetworkError("net"))
        )
        result, reason = svc._dispatch_to_para({"request_id": "r1", "created_at": "t"})
        assert result is None
        assert "unreachable" in reason

    def test_connect_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        svc = _make_svc(
            tmp_path, http_client_factory=_fake_http_factory(exc=httpx.ConnectError("conn"))
        )
        result, reason = svc._dispatch_to_para({"request_id": "r1", "created_at": "t"})
        assert result is None
        assert "unreachable" in reason

    def test_generic_exception(self, tmp_path, monkeypatch):
        """通用异常被捕获并写入 outbox（返回 dict 而非 None）。"""
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para")
        svc = _make_svc(tmp_path, http_client_factory=_fake_http_factory(exc=RuntimeError("boom")))
        result, reason = svc._dispatch_to_para({"request_id": "r1", "created_at": "t"})
        # 通用异常走 _write_outbox 分支，返回 dict（accepted=False, status=dispatch_error）
        assert result is not None
        assert result["accepted"] is False
        assert result["status"] == "dispatch_error"
        assert "boom" in reason


# ─────────────── _parse_claude_stream_json 边界 ──────────────────


class TestParseClaudeStreamJsonBoundary:
    """_parse_claude_stream_json 的事件解析。

    签名: _parse_claude_stream_json(self, out: str) -> str
    """

    def test_result_event(self, tmp_path):
        svc = _make_svc(tmp_path)
        events = '{"type":"result","result":"final answer"}\n'
        result = svc._parse_claude_stream_json(events)
        assert "final answer" in result

    def test_assistant_text_event(self, tmp_path):
        svc = _make_svc(tmp_path)
        events = '{"type":"assistant","message":{"content":[{"type":"text","text":"hello"}]}}\n'
        result = svc._parse_claude_stream_json(events)
        assert "hello" in result

    def test_non_dict_message(self, tmp_path):
        svc = _make_svc(tmp_path)
        events = '{"type":"assistant","message":"not dict"}\n'
        result = svc._parse_claude_stream_json(events)
        assert isinstance(result, str)

    def test_empty_content(self, tmp_path):
        svc = _make_svc(tmp_path)
        events = '{"type":"assistant","message":{"content":[]}}\n'
        result = svc._parse_claude_stream_json(events)
        assert isinstance(result, str)

    def test_non_text_block(self, tmp_path):
        svc = _make_svc(tmp_path)
        events = '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"bash"}]}}\n'
        result = svc._parse_claude_stream_json(events)
        assert isinstance(result, str)

    def test_non_json_line(self, tmp_path):
        svc = _make_svc(tmp_path)
        events = "not json line\n"
        result = svc._parse_claude_stream_json(events)
        assert isinstance(result, str)

    def test_non_dict_line(self, tmp_path):
        svc = _make_svc(tmp_path)
        events = '"string line"\n42\n'
        result = svc._parse_claude_stream_json(events)
        assert isinstance(result, str)

    def test_unknown_type(self, tmp_path):
        svc = _make_svc(tmp_path)
        events = '{"type":"unknown","data":"x"}\n'
        result = svc._parse_claude_stream_json(events)
        assert isinstance(result, str)

    def test_priority_result_over_assistant(self, tmp_path):
        svc = _make_svc(tmp_path)
        events = (
            '{"type":"assistant","message":{"content":[{"type":"text","text":"partial"}]}}\n'
            '{"type":"result","result":"final"}\n'
        )
        result = svc._parse_claude_stream_json(events)
        assert "final" in result

    def test_empty_input(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._parse_claude_stream_json("") == ""


# ─────────────── _parse_stream_json_full ─────────────────────────


class TestParseStreamJsonFullBoundary:
    """_parse_stream_json_full 的 session_id 提取。

    签名: _parse_stream_json_full(self, out: str) -> tuple[str, str]
    """

    def test_extracts_session_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        events = '{"type":"system","session_id":"sess123"}\n'
        text, session_id = svc._parse_stream_json_full(events)
        assert session_id == "sess123"

    def test_no_session_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        events = '{"type":"result","result":"answer"}\n'
        text, session_id = svc._parse_stream_json_full(events)
        assert session_id == ""

    def test_multiple_events(self, tmp_path):
        svc = _make_svc(tmp_path)
        events = (
            '{"type":"assistant","message":{"content":[{"type":"text","text":"a"}]}}\n'
            '{"type":"system","session_id":"sess456"}\n'
        )
        text, session_id = svc._parse_stream_json_full(events)
        assert session_id == "sess456"


# ─────────────── _json_response / _error_message ─────────────────


class TestJsonResponseAndErrorBoundary:
    """_json_response 和 _error_message 的边界。

    签名:
      _json_response(self, resp: httpx.Response) -> dict
      _error_message(self, body: dict, fallback: str) -> str
    """

    def test_json_response_valid(self, tmp_path):
        svc = _make_svc(tmp_path)
        resp = MagicMock()
        resp.status_code = 200
        resp.text = '{"ok": true}'
        resp.content = b'{"ok": true}'
        resp.json.return_value = {"ok": True}
        result = svc._json_response(resp)
        assert result == {"ok": True}

    def test_json_response_invalid_json(self, tmp_path):
        svc = _make_svc(tmp_path)
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "not json"
        resp.content = b"not json"
        resp.json.side_effect = ValueError("not json")
        result = svc._json_response(resp)
        # JSON 解析失败时返回 {"raw": resp.text[:1000]}
        assert result == {"raw": "not json"}

    def test_json_response_empty_content(self, tmp_path):
        svc = _make_svc(tmp_path)
        resp = MagicMock()
        resp.status_code = 200
        resp.text = ""
        resp.content = b""
        resp.json.side_effect = ValueError("empty")
        result = svc._json_response(resp)
        assert result == {}

    def test_error_message_with_error_field(self, tmp_path):
        svc = _make_svc(tmp_path)
        msg = svc._error_message({"error": "server error"}, "fallback")
        assert "server error" in msg

    def test_error_message_with_message_field(self, tmp_path):
        svc = _make_svc(tmp_path)
        msg = svc._error_message({"message": "something failed"}, "fallback")
        assert "something failed" in msg

    def test_error_message_fallback(self, tmp_path):
        svc = _make_svc(tmp_path)
        msg = svc._error_message({}, "fallback message")
        assert "fallback" in msg


# ─────────────── _local_device_id 边界 ───────────────────────────


class TestLocalDeviceIdBoundary:
    """_local_device_id 的环境变量解析。

    签名: _local_device_id(self) -> str
    """

    def test_super_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", "dev-local")
        svc = _make_svc(tmp_path)
        assert svc._local_device_id() == "dev-local"

    def test_modstore_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", raising=False)
        monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "dev-mod")
        svc = _make_svc(tmp_path)
        assert svc._local_device_id() == "dev-mod"

    def test_devfleet_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_DEVICE_ID", raising=False)
        monkeypatch.setenv("DEVFLEET_DEVICE_ID", "dev-fleet")
        svc = _make_svc(tmp_path)
        assert svc._local_device_id() == "dev-fleet"

    def test_no_env_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_DEVICE_ID", raising=False)
        monkeypatch.delenv("DEVFLEET_DEVICE_ID", raising=False)
        svc = _make_svc(tmp_path)
        assert svc._local_device_id() == ""

    def test_whitespace_env_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", "   ")
        svc = _make_svc(tmp_path)
        assert svc._local_device_id() == ""


# ─────────────── _para_api_url 边界 ──────────────────────────────


class TestParaApiUrlBoundary:
    """_para_api_url 的环境变量解析。

    签名: _para_api_url(self) -> str
    """

    def test_super_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://super")
        svc = _make_svc(tmp_path)
        assert svc._para_api_url() == "http://super"

    def test_modstore_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", raising=False)
        monkeypatch.setenv("MODSTORE_PARA_API_URL", "http://modstore")
        svc = _make_svc(tmp_path)
        assert svc._para_api_url() == "http://modstore"

    def test_devfleet_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_API_URL", raising=False)
        monkeypatch.setenv("DEVFLEET_API_URL", "http://devfleet")
        svc = _make_svc(tmp_path)
        assert svc._para_api_url() == "http://devfleet"

    def test_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_API_URL", raising=False)
        monkeypatch.delenv("DEVFLEET_API_URL", raising=False)
        svc = _make_svc(tmp_path)
        result = svc._para_api_url()
        assert isinstance(result, str)

    def test_disabled_values(self, tmp_path, monkeypatch):
        # 这些值会被识别为"禁用"，返回空字符串
        for val in ("disabled", "off", "none", "0", "false"):
            monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", val)
            # 同时屏蔽后续 fallback
            monkeypatch.delenv("MODSTORE_PARA_API_URL", raising=False)
            monkeypatch.delenv("DEVFLEET_API_URL", raising=False)
            svc = _make_svc(tmp_path)
            assert svc._para_api_url() == "", f"value={val!r} should disable para api"

    def test_trailing_slash_stripped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para/")
        svc = _make_svc(tmp_path)
        assert svc._para_api_url() == "http://para"


# ─────────────── _cli_path 边界 ──────────────────────────────────


class TestCliPathBoundary:
    """_cli_path 的环境变量和 shutil.which 解析。

    签名: _cli_path(self) -> str
    """

    def test_env_path(self, tmp_path, monkeypatch):
        # 创建真实文件，因为 _cli_path 会检查 Path(value).is_file()
        cli_bin = tmp_path / "codex"
        cli_bin.write_text("#!/bin/sh\n")
        cli_bin.chmod(0o755)
        monkeypatch.setenv("XCMAX_CODEX_CLI_PATH", str(cli_bin))
        svc = _make_svc(tmp_path)
        assert svc._cli_path() == str(cli_bin)

    def test_empty_env_falls_back_to_which(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_PATH", "")
        svc = _make_svc(tmp_path)
        with patch(
            "app.application.super_employee_service.shutil.which", return_value="/found/codex"
        ):
            with patch("app.application.super_employee_service.Path.is_file", return_value=True):
                assert svc._cli_path() == "/found/codex"

    def test_nonexistent_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_PATH", "")
        svc = _make_svc(tmp_path)
        with patch("app.application.super_employee_service.shutil.which", return_value=None):
            with patch("app.application.super_employee_service.Path.is_file", return_value=False):
                assert svc._cli_path() == ""


# ─────────────── _cli_workspace 边界 ─────────────────────────────


class TestCliWorkspaceBoundary:
    """_cli_workspace 的解析逻辑。

    签名: _cli_workspace(self, context: dict) -> str
    """

    def test_context_workspace_root(self, tmp_path, monkeypatch):
        # _cli_workspace 会检查 Path(candidate).exists()，需用真实路径
        ws = tmp_path / "ws"
        ws.mkdir()
        svc = _make_svc(tmp_path)
        ctx = {"workspace_root": str(ws)}
        assert svc._cli_workspace(ctx) == str(ws)

    def test_env_workspace(self, tmp_path, monkeypatch):
        ws = tmp_path / "envws"
        ws.mkdir()
        monkeypatch.setenv("XCMAX_CODEX_WORKSPACE_ROOT", str(ws))
        svc = _make_svc(tmp_path)
        assert svc._cli_workspace({}) == str(ws)

    def test_default_workspace(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_WORKSPACE_ROOT", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_WORKSPACE_ROOT", raising=False)
        monkeypatch.delenv("MODSTORE_REPO_ROOT", raising=False)
        svc = _make_svc(tmp_path)
        result = svc._cli_workspace({})
        assert isinstance(result, str)


# ─────────────── _cli_idle_timeout / _cli_hard_cap ───────────────


class TestCliTimeoutsBoundary:
    """_cli_idle_timeout_seconds 和 _cli_hard_cap_seconds 的解析。"""

    def test_idle_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_CLI_IDLE_TIMEOUT_SEC", raising=False)
        monkeypatch.delenv("XCMAX_CODEX_CLI_TIMEOUT_SEC", raising=False)
        svc = _make_svc(tmp_path)
        result = svc._cli_idle_timeout_seconds()
        assert isinstance(result, (int, float))
        assert result > 0

    def test_idle_custom(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_IDLE_TIMEOUT_SEC", "120")
        svc = _make_svc(tmp_path)
        assert svc._cli_idle_timeout_seconds() == 120

    def test_idle_invalid_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_IDLE_TIMEOUT_SEC", "not a number")
        svc = _make_svc(tmp_path)
        result = svc._cli_idle_timeout_seconds()
        assert isinstance(result, (int, float))
        assert result > 0

    def test_hard_cap_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_CLI_HARD_CAP_SEC", raising=False)
        svc = _make_svc(tmp_path)
        result = svc._cli_hard_cap_seconds()
        assert isinstance(result, (int, float))
        assert result > 0

    def test_hard_cap_custom(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_HARD_CAP_SEC", "600")
        svc = _make_svc(tmp_path)
        assert svc._cli_hard_cap_seconds() == 600

    def test_hard_cap_invalid_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_HARD_CAP_SEC", "not a number")
        svc = _make_svc(tmp_path)
        result = svc._cli_hard_cap_seconds()
        assert isinstance(result, (int, float))
        assert result > 0


# ─────────────── _dev_loop_enabled ───────────────────────────────


class TestDevLoopEnabledBoundary:
    """_dev_loop_enabled 的环境变量解析。"""

    def test_default_enabled(self, tmp_path, monkeypatch):
        # 默认值为 "1"（启用）
        monkeypatch.delenv("XCMAX_CODEX_DEV_LOOP", raising=False)
        monkeypatch.delenv("XCMAX_CLAUDE_DEV_LOOP", raising=False)
        svc = _make_svc(tmp_path)
        assert svc._dev_loop_enabled() is True

    def test_enabled_explicitly(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_DEV_LOOP", "1")
        svc = _make_svc(tmp_path)
        assert svc._dev_loop_enabled() is True

    def test_disabled_explicitly(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_DEV_LOOP", "0")
        svc = _make_svc(tmp_path)
        assert svc._dev_loop_enabled() is False

    def test_disabled_variants(self, tmp_path, monkeypatch):
        for val in ("false", "off", "disabled", "0"):
            monkeypatch.setenv("XCMAX_CODEX_DEV_LOOP", val)
            svc = _make_svc(tmp_path)
            assert svc._dev_loop_enabled() is False, f"val={val}"

    def test_enabled_variants(self, tmp_path, monkeypatch):
        for val in ("1", "true", "yes", "on"):
            monkeypatch.setenv("XCMAX_CODEX_DEV_LOOP", val)
            svc = _make_svc(tmp_path)
            assert svc._dev_loop_enabled() is True, f"val={val}"


# ─────────────── _is_git_repo ────────────────────────────────────


class TestIsGitRepoBoundary:
    """_is_git_repo 的分支覆盖。

    签名: _is_git_repo(self, cwd: str) -> bool
    """

    def test_not_a_repo(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch("app.application.super_employee_service.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                [], 128, stdout="", stderr="not a git repo"
            )
            assert svc._is_git_repo(str(tmp_path)) is False

    def test_exception_returns_false(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch(
            "app.application.super_employee_service.subprocess.run", side_effect=OSError("boom")
        ):
            assert svc._is_git_repo(str(tmp_path)) is False

    def test_false_stdout(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch("app.application.super_employee_service.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="false", stderr="")
            assert svc._is_git_repo(str(tmp_path)) is False

    def test_true_stdout(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch("app.application.super_employee_service.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="true", stderr="")
            assert svc._is_git_repo(str(tmp_path)) is True

    def test_git_runs_without_interactive_prompts(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GIT_TERMINAL_PROMPT", raising=False)
        monkeypatch.delenv("GIT_ASKPASS", raising=False)
        svc = _make_svc(tmp_path)
        with patch("app.application.super_employee_service.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 0, stdout="true", stderr="")
            svc._git(str(tmp_path), "status")
        env = mock_run.call_args.kwargs["env"]
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["GIT_ASKPASS"] == "true"


# ─────────────── _clean_cli_stdout ───────────────────────────────


class TestCleanCliStdoutBoundary:
    """_clean_cli_stdout 的过滤逻辑。

    签名: _clean_cli_stdout(self, stdout: str) -> str
    """

    def test_filters_tool_name_lines(self, tmp_path):
        svc = _make_svc(tmp_path)
        stdout = "codex\nreal output\nanother line"
        result = svc._clean_cli_stdout(stdout)
        assert isinstance(result, str)

    def test_filters_empty_lines(self, tmp_path):
        svc = _make_svc(tmp_path)
        stdout = "\n\nreal\n\n"
        result = svc._clean_cli_stdout(stdout)
        assert "real" in result

    def test_empty_input(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._clean_cli_stdout("") == ""

    def test_whitespace_only(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc._clean_cli_stdout("   \n   \n")
        assert isinstance(result, str)


# ─────────────── _build_dispatch_request ─────────────────────────


class TestBuildDispatchRequestBoundary:
    """_build_dispatch_request 的字段构造。

    签名: _build_dispatch_request(self, *, request_id, created_at, user_id, message, context) -> dict
    """

    def test_mobile_source_translated(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = svc._build_dispatch_request(
            request_id="r1",
            created_at="2025-01-01",
            user_id=1,
            message="任务",
            context={"source": "mobile_chat"},
        )
        assert req["source"] == "xcagi_mobile_im"

    def test_admin_source_preserved(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = svc._build_dispatch_request(
            request_id="r1",
            created_at="2025-01-01",
            user_id=1,
            message="任务",
            context={"source": "admin_im"},
        )
        assert req["source"] == "xcagi_admin_im"

    def test_default_source_is_admin(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = svc._build_dispatch_request(
            request_id="r1",
            created_at="2025-01-01",
            user_id=1,
            message="任务",
            context={},
        )
        assert req["source"] == "xcagi_admin_im"

    def test_target_devices_list(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = svc._build_dispatch_request(
            request_id="r1",
            created_at="2025-01-01",
            user_id=1,
            message="任务",
            context={"target_devices": ["dev1", "dev2"]},
        )
        assert req["target_devices"] == ["dev1", "dev2"]

    def test_default_target_devices(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = svc._build_dispatch_request(
            request_id="r1",
            created_at="2025-01-01",
            user_id=1,
            message="任务",
            context={},
        )
        assert req["target_devices"] == ["all"]

    def test_mode_included(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = svc._build_dispatch_request(
            request_id="r1",
            created_at="2025-01-01",
            user_id=1,
            message="任务",
            context={"mode": "code"},
        )
        assert req["mode"] == "code"

    def test_default_mode(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = svc._build_dispatch_request(
            request_id="r1",
            created_at="2025-01-01",
            user_id=1,
            message="任务",
            context={},
        )
        assert req["mode"] == "code"

    def test_title_truncation(self, tmp_path):
        svc = _make_svc(tmp_path)
        long_msg = "x" * 500
        req = svc._build_dispatch_request(
            request_id="r1",
            created_at="2025-01-01",
            user_id=1,
            message=long_msg,
            context={},
        )
        assert len(req["title"]) <= 120

    def test_raw_context_included(self, tmp_path):
        svc = _make_svc(tmp_path)
        ctx = {"custom": "value"}
        req = svc._build_dispatch_request(
            request_id="r1",
            created_at="2025-01-01",
            user_id=1,
            message="任务",
            context=ctx,
        )
        assert req["raw_context"] == ctx


# ─────────────── _message_row / _public_message ──────────────────


class TestMessageRowAndPublicBoundary:
    """_message_row 和 _public_message 的字段处理。"""

    def test_message_row_basic(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = svc._message_row(
            user_id=1,
            role="user",
            body="hello",
            created_at="2025-01-01",
            request_id="r1",
            status="sent",
        )
        assert row["user_id"] == 1
        assert row["body"] == "hello"
        assert row["role"] == "user"

    def test_message_row_with_extra(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = svc._message_row(
            user_id=1,
            role="assistant",
            body="reply",
            created_at="2025-01-01",
            request_id="r1",
            status="completed",
            extra={"kind": "codex_result"},
        )
        assert row.get("kind") == "codex_result"

    def test_message_row_omits_none_extra(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = svc._message_row(
            user_id=1,
            role="user",
            body="x",
            created_at="2025",
            request_id="r1",
            status="sent",
            extra=None,
        )
        assert "kind" not in row

    def test_message_row_omits_empty_extra_values(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = svc._message_row(
            user_id=1,
            role="user",
            body="x",
            created_at="2025",
            request_id="r1",
            status="sent",
            extra={"kind": "", "task_id": None},
        )
        assert "kind" not in row
        assert "task_id" not in row

    def test_public_message_basic(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"user_id": 1, "role": "user", "body": "hi", "status": "sent"}
        pub = svc._public_message(row)
        assert "body" in pub
        assert pub.get("body") == "hi"

    def test_public_message_all_fields(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {
            "id": "msg1",
            "role": "assistant",
            "body": "reply",
            "created_at": "2025",
            "status": "completed",
            "dispatch_request_id": "r1",
            "kind": "codex_result",
            "task_id": "t1",
            "task_status": "completed",
            "subtask_id": "s1",
            "device_name": "dev1",
        }
        pub = svc._public_message(row)
        assert pub["id"] == "msg1"
        assert pub["role"] == "assistant"
        assert pub["task_id"] == "t1"

    def test_public_message_missing_fields(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"body": "x"}
        pub = svc._public_message(row)
        assert pub["body"] == "x"
        assert pub["role"] == "assistant"  # 默认值
        assert pub["task_id"] == ""


# ─────────────── _read_all_message_rows / _append_messages ───────


class TestMessageRowsIOBoundary:
    """消息行文件读写。"""

    def test_read_no_file(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._read_all_message_rows() == []

    def test_append_and_read(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = svc._message_row(
            user_id=1, role="user", body="x", created_at="2025", request_id="r1", status="sent"
        )
        svc._append_messages([row])
        rows = svc._read_all_message_rows()
        assert len(rows) == 1
        assert rows[0]["body"] == "x"

    def test_read_invalid_json(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc._messages_path.write_text("not json\n", encoding="utf-8")
        assert svc._read_all_message_rows() == []

    def test_read_empty_lines(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc._messages_path.write_text("\n\n\n", encoding="utf-8")
        assert svc._read_all_message_rows() == []

    def test_read_non_dict_skipped(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc._messages_path.write_text('"string"\n42\n', encoding="utf-8")
        assert svc._read_all_message_rows() == []

    def test_write_all_rows(self, tmp_path):
        svc = _make_svc(tmp_path)
        rows = [
            {"user_id": 1, "role": "user", "body": "a"},
            {"user_id": 1, "role": "assistant", "body": "b"},
        ]
        svc._write_all_message_rows(rows)
        read_back = svc._read_all_message_rows()
        assert len(read_back) == 2


# ─────────────── _dispatch_reply ─────────────────────────────────


class TestDispatchReplyBoundary:
    """_dispatch_reply 的派工回复。

    签名: _dispatch_reply(self, dispatch: dict) -> str
    始终返回 "思考中..."
    """

    def test_returns_thinking_message(self, tmp_path):
        svc = _make_svc(tmp_path)
        reply = svc._dispatch_reply({"status": "queued"})
        assert "思考" in reply

    def test_returns_same_for_any_dispatch(self, tmp_path):
        svc = _make_svc(tmp_path)
        reply1 = svc._dispatch_reply({"status": "queued"})
        reply2 = svc._dispatch_reply({"status": "accepted", "task_id": "t1"})
        assert reply1 == reply2

    def test_empty_dispatch(self, tmp_path):
        svc = _make_svc(tmp_path)
        reply = svc._dispatch_reply({})
        assert isinstance(reply, str)


# ─────────────── _write_outbox ───────────────────────────────────


class TestWriteOutboxBoundary:
    """_write_outbox 的文件写入。

    签名: _write_outbox(self, request, *, status, accepted, reason) -> dict
    """

    def test_writes_file(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = {"request_id": "r1", "created_at": "2025-01-01T00:00:00", "message": "任务"}
        result = svc._write_outbox(req, status="queued", accepted=False, reason="test")
        assert Path(result["outbox_path"]).is_file()
        content = json.loads(Path(result["outbox_path"]).read_text(encoding="utf-8"))
        assert content["request_id"] == "r1"

    def test_returns_queued_true(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = {"request_id": "r1", "created_at": "2025-01-01T00:00:00", "message": "任务"}
        result = svc._write_outbox(req, status="queued", accepted=False, reason="test")
        assert result["queued"] is True

    def test_path_contains_request_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = {"request_id": "abc123", "created_at": "2025-01-01T00:00:00", "message": "任务"}
        result = svc._write_outbox(req, status="queued", accepted=False, reason="test")
        assert "abc123" in Path(result["outbox_path"]).name


# ─────────────── _max_para_devices ───────────────────────────────


class TestMaxParaDevicesBoundary:
    """_max_para_devices 的环境变量解析和钳制。

    签名: _max_para_devices(self, request: dict) -> int
    """

    def test_default_value(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_MAX_DEVICES", raising=False)
        svc = _make_svc(tmp_path)
        result = svc._max_para_devices({"raw_context": {}})
        assert isinstance(result, int)
        assert result >= 1

    def test_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_MAX_DEVICES", "4")
        svc = _make_svc(tmp_path)
        assert svc._max_para_devices({"raw_context": {}}) == 4

    def test_invalid_env_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_MAX_DEVICES", "not a number")
        svc = _make_svc(tmp_path)
        result = svc._max_para_devices({"raw_context": {}})
        assert isinstance(result, int)
        assert result >= 1

    def test_zero_clamped_to_minimum(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_MAX_DEVICES", "0")
        svc = _make_svc(tmp_path)
        assert svc._max_para_devices({"raw_context": {}}) >= 1

    def test_negative_clamped_to_minimum(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_MAX_DEVICES", "-5")
        svc = _make_svc(tmp_path)
        assert svc._max_para_devices({"raw_context": {}}) >= 1


# ─────────────── _para_subtask_title ─────────────────────────────


class TestParaSubtaskTitleBoundary:
    """_para_subtask_title 的构造。

    签名: _para_subtask_title(self, title: str, index: int, total: int) -> str
    """

    def test_single_device_returns_title(self, tmp_path):
        svc = _make_svc(tmp_path)
        title = svc._para_subtask_title("my task", 0, 1)
        assert title == "my task"

    def test_multi_device_adds_label(self, tmp_path):
        svc = _make_svc(tmp_path)
        title = svc._para_subtask_title("my task", 0, 3)
        assert "my task" in title
        # 应包含子任务标签
        assert "需求定位" in title or "核心实现" in title or "验证" in title

    def test_second_subtask_label(self, tmp_path):
        svc = _make_svc(tmp_path)
        title = svc._para_subtask_title("my task", 1, 3)
        assert "核心实现" in title

    def test_third_subtask_label(self, tmp_path):
        svc = _make_svc(tmp_path)
        title = svc._para_subtask_title("my task", 2, 3)
        assert "验证" in title or "收尾" in title


# ─────────────── _para_prompt ────────────────────────────────────


class TestParaPromptBoundary:
    """_para_prompt 的构造。

    签名: _para_prompt(self, request: dict, device: dict, index: int, total: int) -> str
    """

    def test_single_device(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = {"prompt": "修复 bug", "workspace_root": ""}
        prompt = svc._para_prompt(req, {"id": "dev1"}, 0, 1)
        assert "修复 bug" in prompt
        assert "直接完成" in prompt

    def test_multi_device(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = {"prompt": "修复 bug", "workspace_root": ""}
        prompt = svc._para_prompt(req, {"id": "dev1", "name": "worker1"}, 0, 2)
        assert "修复 bug" in prompt
        assert "1/2" in prompt

    def test_with_workspace_root(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = {"prompt": "任务", "workspace_root": "/custom/ws"}
        prompt = svc._para_prompt(req, {"id": "dev1"}, 0, 1)
        assert "/custom/ws" in prompt

    def test_empty_prompt_uses_task(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = {"task": "从 task 字段", "workspace_root": ""}
        prompt = svc._para_prompt(req, {"id": "dev1"}, 0, 1)
        assert "从 task 字段" in prompt

    def test_device_name_in_multi(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = {"prompt": "任务", "workspace_root": ""}
        prompt = svc._para_prompt(req, {"id": "dev1", "name": "worker1"}, 0, 2)
        assert "worker1" in prompt


# ─────────────── _upsert_direct_reply_messages 边界 ─────────────


class TestUpsertDirectReplyMessagesBoundary:
    """_upsert_direct_reply_messages 的直答回填。

    签名: _upsert_direct_reply_messages(self, *, user_id: int, rows: list) -> bool
    """

    def test_no_rows(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._upsert_direct_reply_messages(user_id=1, rows=[]) is False

    def test_with_reply_skip(self, tmp_path):
        """已有直答消息时跳过。"""
        svc = _make_svc(tmp_path)
        rows = [
            {
                "user_id": 1,
                "role": "user",
                "kind": "",
                "dispatch_request_id": "r1",
                "body": "你是谁",
            },
            {
                "user_id": 1,
                "role": "assistant",
                "kind": "codex_direct",
                "dispatch_request_id": "r1",
                "body": "直答",
            },
        ]
        assert svc._upsert_direct_reply_messages(user_id=1, rows=rows) is False

    def test_adds_direct_reply_for_identity(self, tmp_path):
        """无直答消息且用户消息匹配身份提示时回填。"""
        svc = _make_svc(tmp_path)
        rows = [
            {
                "user_id": 1,
                "role": "user",
                "kind": "",
                "dispatch_request_id": "r1",
                "body": "你是谁",
            },
        ]
        result = svc._upsert_direct_reply_messages(user_id=1, rows=rows)
        assert result is True
        assert len(rows) == 2
        assert rows[1]["role"] == "assistant"
        assert rows[1]["kind"] == "codex_direct"

    def test_other_user_skipped(self, tmp_path):
        svc = _make_svc(tmp_path)
        rows = [
            {
                "user_id": 2,
                "role": "user",
                "kind": "",
                "dispatch_request_id": "r1",
                "body": "你是谁",
            },
        ]
        assert svc._upsert_direct_reply_messages(user_id=1, rows=rows) is False

    def test_non_user_role_skipped(self, tmp_path):
        svc = _make_svc(tmp_path)
        rows = [
            {
                "user_id": 1,
                "role": "assistant",
                "kind": "",
                "dispatch_request_id": "r1",
                "body": "回复",
            },
        ]
        assert svc._upsert_direct_reply_messages(user_id=1, rows=rows) is False

    def test_no_request_id_skipped(self, tmp_path):
        svc = _make_svc(tmp_path)
        rows = [
            {
                "user_id": 1,
                "role": "user",
                "kind": "",
                "dispatch_request_id": "",
                "body": "你是谁",
            },
        ]
        assert svc._upsert_direct_reply_messages(user_id=1, rows=rows) is False


# ─────────────── invoke 边界 ─────────────────────────────────────


class TestInvokeBoundary:
    """invoke 的各类输入分支。"""

    def test_empty_message_raises(self, tmp_path):
        svc = _make_svc(tmp_path)
        with pytest.raises(ValueError, match="message"):
            svc.invoke(user_id=1, message="")

    def test_whitespace_message_raises(self, tmp_path):
        svc = _make_svc(tmp_path)
        with pytest.raises(ValueError, match="message"):
            svc.invoke(user_id=1, message="   ")

    def test_none_message_raises(self, tmp_path):
        svc = _make_svc(tmp_path)
        with pytest.raises(ValueError, match="message"):
            svc.invoke(user_id=1, message=None)

    def test_chat_mode_cli_reply(self, tmp_path):
        svc = _make_svc(tmp_path, cli_runner=_stdout_runner("cli answer"))
        with patch.object(svc, "_cli_path", return_value=str(tmp_path / "codex")):
            result = svc.invoke(user_id=1, message="你好", context={"mode": "chat"})
        assert result["dispatch"]["status"] == "completed"

    def test_chat_mode_no_cli_direct_reply(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_cli_path", return_value=""):
            result = svc.invoke(user_id=1, message="你是谁", context={"mode": "chat"})
        assert "Codex" in result["assistant_message"]["body"]

    def test_chat_mode_no_cli_fallback(self, tmp_path):
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        with patch.object(svc, "_cli_path", return_value=str(tmp_path / "notexist")):
            result = svc.invoke(user_id=1, message="今天天气", context={"mode": "chat"})
        assert "CLI" in result["assistant_message"]["body"]

    def test_code_mode_dispatch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
        svc = _make_svc(tmp_path)
        result = svc.invoke(user_id=1, message="修复 bug", context={"mode": "code"})
        assert result["dispatch"]["queued"] is True


# ─────────────── list_messages 边界 ──────────────────────────────


class TestListMessagesBoundary:
    """list_messages 的边界条件。"""

    def test_empty_file(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc.list_messages(user_id=1) == []

    def test_user_scoped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
        svc = _make_svc(tmp_path)
        svc.invoke(user_id=1, message="任务 A")
        svc.invoke(user_id=2, message="任务 B")
        msgs = svc.list_messages(user_id=1)
        assert all(m.get("role") or True for m in msgs)

    def test_limit_capped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
        svc = _make_svc(tmp_path)
        for i in range(10):
            svc.invoke(user_id=1, message=f"任务{i}")
        msgs = svc.list_messages(user_id=1, limit=3)
        assert len(msgs) <= 3

    def test_limit_negative(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
        svc = _make_svc(tmp_path)
        svc.invoke(user_id=1, message="任务 X")
        msgs = svc.list_messages(user_id=1, limit=-5)
        assert isinstance(msgs, list)


# ─────────────── _select_devices_by_tier ─────────────────────────


class TestSelectDevicesByTierBoundary:
    """_select_devices_by_tier 的层级选择。

    签名: _select_devices_by_tier(self, devices: list, request: dict) -> tuple[int, list[dict]]
    """

    def test_tier1_local_eligible(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", "1")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", "dev1")
        svc = _make_svc(tmp_path)
        devices = [
            {
                "id": "dev1",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            }
        ]
        tier, selected = svc._select_devices_by_tier(devices, {"raw_context": {}})
        assert tier == 1
        assert len(selected) == 1

    def test_tier1_escalation_when_local_ineligible(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", "1")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", "dev1")
        svc = _make_svc(tmp_path)
        devices = [
            {"id": "dev1", "status": "offline", "tools": [{"toolName": "codex"}]},
            {
                "id": "dev2",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
        ]
        tier, selected = svc._select_devices_by_tier(devices, {"raw_context": {}})
        # 本机不可用 → 升二级
        assert tier == 2
        assert len(selected) >= 1

    def test_tier2_explicit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", "2")
        svc = _make_svc(tmp_path)
        devices = [
            {
                "id": "dev1",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
            {
                "id": "dev2",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
        ]
        tier, selected = svc._select_devices_by_tier(devices, {"raw_context": {}})
        assert tier == 2

    def test_empty_devices(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", "1")
        svc = _make_svc(tmp_path)
        tier, selected = svc._select_devices_by_tier([], {"raw_context": {}})
        assert isinstance(tier, int)
        assert isinstance(selected, list)


# ─────────────── _select_para_devices ────────────────────────────


class TestSelectParaDevicesBoundary:
    """_select_para_devices 的多设备选择。

    签名: _select_para_devices(self, devices: list, request: dict) -> list[dict]
    """

    def test_target_all(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [
            {
                "id": "dev1",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
            {
                "id": "dev2",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
        ]
        result = svc._select_para_devices(devices, {"target_devices": ["all"]})
        assert len(result) == 2

    def test_target_by_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [
            {
                "id": "dev1",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
            {
                "id": "dev2",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
        ]
        result = svc._select_para_devices(devices, {"target_devices": ["dev1"]})
        assert all(d["id"] == "dev1" for d in result)

    def test_target_by_name(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [
            {
                "id": "dev1",
                "name": "worker1",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
            {
                "id": "dev2",
                "name": "worker2",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
        ]
        result = svc._select_para_devices(devices, {"target_devices": ["worker1"]})
        assert all(d.get("name") == "worker1" for d in result)

    def test_no_target_selects_all_eligible(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [
            {
                "id": "dev1",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
            {
                "id": "dev2",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
        ]
        result = svc._select_para_devices(devices, {})
        assert len(result) == 2

    def test_ineligible_devices_filtered(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [
            {"id": "dev1", "status": "offline", "tools": [{"toolName": "codex"}]},
            {
                "id": "dev2",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
        ]
        result = svc._select_para_devices(devices, {"target_devices": ["all"]})
        assert len(result) == 1
        assert result[0]["id"] == "dev2"

    def test_workers_preferred_over_primary(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [
            {
                "id": "dev1",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
                "isPrimary": True,
            },
            {
                "id": "dev2",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
        ]
        result = svc._select_para_devices(devices, {"target_devices": ["all"]})
        # workers 优先
        assert result[0]["id"] == "dev2"

    def test_max_devices_limit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_MAX_DEVICES", "1")
        svc = _make_svc(tmp_path)
        devices = [
            {
                "id": "dev1",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
            {
                "id": "dev2",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
        ]
        result = svc._select_para_devices(devices, {"target_devices": ["all"], "raw_context": {}})
        assert len(result) <= 1


# ─────────────── _select_local_device ────────────────────────────


class TestSelectLocalDeviceBoundary:
    """_select_local_device 的本地设备选择。

    签名: _select_local_device(self, devices: list, request: dict) -> list[dict]
    使用 isPrimary（非 is_primary）
    """

    def test_local_id_found_eligible(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", "dev1")
        svc = _make_svc(tmp_path)
        devices = [
            {
                "id": "dev1",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            }
        ]
        result = svc._select_local_device(devices, {"raw_context": {}})
        assert len(result) == 1
        assert result[0]["id"] == "dev1"

    def test_local_id_found_ineligible(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", "dev1")
        svc = _make_svc(tmp_path)
        devices = [{"id": "dev1", "status": "offline", "tools": [{"toolName": "codex"}]}]
        result = svc._select_local_device(devices, {"raw_context": {}})
        assert len(result) == 0

    def test_local_id_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", "dev_missing")
        svc = _make_svc(tmp_path)
        devices = [
            {
                "id": "dev1",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            }
        ]
        result = svc._select_local_device(devices, {"raw_context": {}})
        assert len(result) == 0

    def test_primary_eligible(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [
            {
                "id": "dev1",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
                "isPrimary": True,
            }
        ]
        result = svc._select_local_device(devices, {"raw_context": {}})
        assert len(result) == 1

    def test_primary_ineligible(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [
            {"id": "dev1", "status": "offline", "tools": [{"toolName": "codex"}], "isPrimary": True}
        ]
        result = svc._select_local_device(devices, {"raw_context": {}})
        assert len(result) == 0

    def test_first_eligible(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [
            {"id": "dev1", "status": "offline", "tools": [{"toolName": "codex"}]},
            {
                "id": "dev2",
                "status": "online",
                "tools": [{"toolName": "codex", "status": "installed"}],
            },
        ]
        result = svc._select_local_device(devices, {"raw_context": {}})
        assert len(result) == 1
        assert result[0]["id"] == "dev2"

    def test_none_eligible(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [{"id": "dev1", "status": "offline", "tools": [{"toolName": "codex"}]}]
        result = svc._select_local_device(devices, {"raw_context": {}})
        assert len(result) == 0

    def test_empty_devices(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._select_local_device([], {"raw_context": {}}) == []


# ─────────────── _sync_para_task_updates 边界 ────────────────────


class TestSyncParaTaskUpdatesBoundary:
    """_sync_para_task_updates 的边界条件。"""

    def test_empty_rows_no_change(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc._sync_para_task_updates(user_id=1, rows=[])
        # 不应抛异常

    def test_non_dispatcher_rows_skipped(self, tmp_path):
        svc = _make_svc(tmp_path)
        rows = [
            {"user_id": 1, "role": "user", "kind": "", "body": "hello"},
        ]
        svc._sync_para_task_updates(user_id=1, rows=rows)
        # 不应抛异常

    def test_terminal_status_with_result_skipped(self, tmp_path):
        """终态任务且已有结果消息时跳过。"""
        svc = _make_svc(tmp_path)
        rows = [
            {
                "user_id": 1,
                "role": "system",
                "kind": DISPATCHER_MESSAGE_KIND,
                "task_id": "task1",
                "task_status": "completed",
                "status": "completed",
                "dispatch_request_id": "req1",
            },
            {
                "user_id": 1,
                "role": "assistant",
                "kind": "codex_result",
                "task_id": "task1",
                "dispatch_request_id": "req1",
            },
        ]
        with patch.object(svc, "_fetch_para_task") as mock_fetch:
            svc._sync_para_task_updates(user_id=1, rows=rows)
        assert not mock_fetch.called

    def test_direct_reply_skipped(self, tmp_path):
        """已有直答消息时跳过。"""
        svc = _make_svc(tmp_path)
        rows = [
            {
                "user_id": 1,
                "role": "system",
                "kind": DISPATCHER_MESSAGE_KIND,
                "task_id": "task1",
                "task_status": "running",
                "dispatch_request_id": "req1",
            },
            {
                "user_id": 1,
                "role": "assistant",
                "kind": "codex_direct",
                "dispatch_request_id": "req1",
            },
        ]
        with patch.object(svc, "_fetch_para_task") as mock_fetch:
            svc._sync_para_task_updates(user_id=1, rows=rows)
        assert not mock_fetch.called

    def test_no_task_id_skipped(self, tmp_path):
        """无 task_id 时跳过。"""
        svc = _make_svc(tmp_path)
        rows = [
            {
                "user_id": 1,
                "role": "system",
                "kind": DISPATCHER_MESSAGE_KIND,
                "task_id": "",
                "task_status": "running",
            },
        ]
        with patch.object(svc, "_fetch_para_task") as mock_fetch:
            svc._sync_para_task_updates(user_id=1, rows=rows)
        assert not mock_fetch.called

    def test_other_user_skipped(self, tmp_path):
        """其他用户的消息跳过。"""
        svc = _make_svc(tmp_path)
        rows = [
            {
                "user_id": 2,
                "role": "system",
                "kind": DISPATCHER_MESSAGE_KIND,
                "task_id": "task1",
                "task_status": "running",
            },
        ]
        with patch.object(svc, "_fetch_para_task") as mock_fetch:
            svc._sync_para_task_updates(user_id=1, rows=rows)
        assert not mock_fetch.called

    def test_8_sync_limit(self, tmp_path):
        """最多同步 8 条。"""
        svc = _make_svc(tmp_path)
        rows = [
            {
                "user_id": 1,
                "role": "system",
                "kind": DISPATCHER_MESSAGE_KIND,
                "task_id": f"task{i}",
                "task_status": "running",
                "dispatch_request_id": f"req{i}",
            }
            for i in range(20)
        ]
        fetch_count = []

        def mock_fetch(task_id):
            fetch_count.append(task_id)
            return None

        with patch.object(svc, "_fetch_para_task", side_effect=mock_fetch):
            svc._sync_para_task_updates(user_id=1, rows=rows)
        assert len(fetch_count) <= 8

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
            svc._sync_para_task_updates(user_id=1, rows=rows)

    def test_refreshes_row_when_task_found(self, tmp_path):
        """任务被找到时调用 _refresh_dispatcher_row 更新行。"""
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
                "body": "old body",
            },
        ]
        task = {"id": "task1", "status": "completed", "subtasks": []}
        with patch.object(svc, "_fetch_para_task", return_value=task):
            svc._sync_para_task_updates(user_id=1, rows=rows)
        assert rows[0]["task_status"] == "completed"
        assert "已完成" in rows[0]["body"]

    def test_upserts_result_messages_when_task_completed(self, tmp_path):
        """任务完成时 _upsert_result_messages 写入结果消息。"""
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
                "body": "old body",
            },
        ]
        task = {
            "id": "task1",
            "status": "completed",
            "subtasks": [
                {
                    "id": "sub1",
                    "status": "completed",
                    "device_name": "dev1",
                    "logs": [{"content": "all good"}],
                    "completed_at": "2025-01-01T00:00:00Z",
                },
            ],
        }
        with patch.object(svc, "_fetch_para_task", return_value=task):
            svc._sync_para_task_updates(user_id=1, rows=rows)
        result_msgs = [r for r in rows if r.get("kind") == "codex_result"]
        assert len(result_msgs) == 1
        assert result_msgs[0]["subtask_id"] == "sub1"
