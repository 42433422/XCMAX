"""Branch-coverage supplement for super_employee_service.py (round 2).

目标：覆盖 super_employee_service.py 的 101 个缺失分支（当前 73.8% 覆盖率）。

test_super_employee_service_cov.py (147 tests) 和 test_codex_super_employee_service_branch_cov.py
(319 tests) 已覆盖大量基础分支。本文件聚焦仍未覆盖的分支：

- _dispatch：mode=outbox / mode=mcp(para 不可用) / webhook 空 content / webhook 非 JSON
- _dispatch_to_para：httpx.NetworkError / 一般异常(outbox) / 设备 devTool 已匹配
- _para_token：env token / 缓存命中 / 缓存过期 / guest 登录失败 / 无 token
- _para_request：status >= 400 抛异常
- _ensure_para_device：devTool 已匹配 / 无 device_id / updated 非 dict
- _create_para_task：repo_url / task_id 链式 / task 非 dict
- _cli_reply_body：conversation 模式(claude) / dev loop 路径
- _run_conversation_turn：idle/hardcap/resume 失效/新 sid
- _verify_workspace：自定义命令 / py 编译错误 / 无改动 / 重命名路径
- _commit_and_push：无改动 / commit 失败 / push 失败 / 异常
- _run_dev_task_loop：worktree 失败 / 验证失败 / 修复循环
- _prepare_worktree：非 git / worktree add 失败
- _session_get/_session_set：文件读写异常
- _ensure_session_workspace：已有工作区 / 非 git / worktree add 分支
- _parse_stream_json_full：session_id 提取
- _cli_subprocess_env：代理设置
- _fetch_para_task：各错误分支
- _upsert_result_messages：existing 更新分支
- _refresh_dispatcher_row：无变更 / 有变更
- _cursor_cli_command：trust/force 各组合
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.application.super_employee_service import (
    CLAUDE_PROFILE,
    CODEX_PROFILE,
    CURSOR_PROFILE,
    DISPATCHER_MESSAGE_KIND,
    SuperEmployeeService,
    SuperEmployeeToolProfile,
    _claude_cli_command,
    _codex_cli_command,
    _coerce_list,
    _cursor_cli_command,
    _safe_json_line,
    _utc_now,
)

# ───────────────────── helpers ─────────────────────


def _make_svc(
    tmp_path: Path,
    *,
    profile: SuperEmployeeToolProfile | None = None,
    cli_runner=None,
    http_client_factory=None,
) -> SuperEmployeeService:
    """构造隔离存储的 SuperEmployeeService。"""
    return SuperEmployeeService(
        profile=profile or CODEX_PROFILE,
        storage_root=tmp_path,
        cli_runner=cli_runner,
        http_client_factory=http_client_factory,
    )


def _null_runner(cmd, **kw):
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def _stdout_runner(stdout: str, returncode: int = 0):
    def _run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    return _run


def _make_request(request_id: str = "req-1", **overrides) -> dict:
    base = {
        "request_id": request_id,
        "created_at": "2026-01-01T00:00:00+00:00",
        "source": "xcagi_admin_im",
        "employee_id": "codex-super-employee",
        "employee_name": "超级员工-Codex",
        "mode": "code",
        "device_scope": "all_devices",
        "target_devices": ["all"],
        "user_id": 1,
        "title": "test task",
        "task": "test task",
        "prompt": "test task",
        "workspace_root": "",
        "raw_context": {},
    }
    base.update(overrides)
    return base


def _mock_response(
    status_code: int = 200,
    json_data: dict | None = None,
    text: str = "",
    content: bytes | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = (
        content if content is not None else (json.dumps(json_data).encode() if json_data else b"")
    )
    resp.text = text or (json.dumps(json_data) if json_data else "")
    resp.json = MagicMock(return_value=json_data or {})
    return resp


def _mock_http_client(
    *,
    post_resp: MagicMock | None = None,
    get_resp: MagicMock | None = None,
    request_resp: MagicMock | None = None,
    post_exc: Exception | None = None,
    get_exc: Exception | None = None,
    request_exc: Exception | None = None,
) -> MagicMock:
    """Build a mock httpx.Client-compatible context manager.

    The returned mock supports ``with client:`` and exposes ``.post`` / ``.get``
    / ``.request`` configured with the provided responses or side effects.
    """
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    if post_exc is not None:
        client.post.side_effect = post_exc
    elif post_resp is not None:
        client.post.return_value = post_resp
    if get_exc is not None:
        client.get.side_effect = get_exc
    elif get_resp is not None:
        client.get.return_value = get_resp
    if request_exc is not None:
        client.request.side_effect = request_exc
    elif request_resp is not None:
        client.request.return_value = request_resp
    return client


# ───────────────────── _cursor_cli_command ─────────────────────


class TestCursorCliCommand:
    def test_trust_enabled_by_default(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("DEVFLEET_CURSOR_TRUST", raising=False)
        monkeypatch.delenv("XCMAX_CURSOR_AGENT_TRUST", raising=False)
        cmd = _cursor_cli_command("/usr/bin/cursor", "prompt", tmp_path / "out.txt", str(tmp_path))
        assert "--trust" in cmd
        assert "--force" in cmd

    def test_trust_disabled_via_devfleet_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DEVFLEET_CURSOR_TRUST", "0")
        monkeypatch.delenv("XCMAX_CURSOR_AGENT_TRUST", raising=False)
        cmd = _cursor_cli_command("/usr/bin/cursor", "prompt", tmp_path / "out.txt", str(tmp_path))
        assert "--trust" not in cmd

    def test_trust_disabled_via_xcmax_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("DEVFLEET_CURSOR_TRUST", raising=False)
        monkeypatch.setenv("XCMAX_CURSOR_AGENT_TRUST", "false")
        cmd = _cursor_cli_command("/usr/bin/cursor", "prompt", tmp_path / "out.txt", str(tmp_path))
        assert "--trust" not in cmd

    def test_force_disabled(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DEVFLEET_CURSOR_FORCE", "off")
        cmd = _cursor_cli_command("/usr/bin/cursor", "prompt", tmp_path / "out.txt", str(tmp_path))
        assert "--force" not in cmd

    def test_force_disabled_disabled_keyword(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CURSOR_AGENT_FORCE", "disabled")
        cmd = _cursor_cli_command("/usr/bin/cursor", "prompt", tmp_path / "out.txt", str(tmp_path))
        assert "--force" not in cmd

    def test_prompt_appended_last(self, tmp_path) -> None:
        cmd = _cursor_cli_command(
            "/usr/bin/cursor", "my prompt", tmp_path / "out.txt", str(tmp_path)
        )
        assert cmd[-1] == "my prompt"


# ───────────────────── _claude_cli_command ─────────────────────


class TestClaudeCliCommand:
    def test_default_permission_mode(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("DEVFLEET_CLAUDE_PERMISSION_MODE", raising=False)
        cmd = _claude_cli_command("/usr/bin/claude", "prompt", tmp_path / "out.txt", str(tmp_path))
        assert "acceptEdits" in cmd

    def test_custom_permission_mode(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DEVFLEET_CLAUDE_PERMISSION_MODE", "bypassPermissions")
        cmd = _claude_cli_command("/usr/bin/claude", "prompt", tmp_path / "out.txt", str(tmp_path))
        assert "bypassPermissions" in cmd

    def test_empty_permission_mode_falls_back(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DEVFLEET_CLAUDE_PERMISSION_MODE", "  ")
        cmd = _claude_cli_command("/usr/bin/claude", "prompt", tmp_path / "out.txt", str(tmp_path))
        assert "acceptEdits" in cmd


# ───────────────────── _dispatch mode branches ─────────────────────


class TestDispatchModeBranches:
    def test_outbox_mode_writes_outbox(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        req = _make_request()
        result = svc._dispatch(req)
        assert result["queued"] is True
        assert result["accepted"] is False
        assert result["reason"] == "dispatch_mode_outbox"

    def test_auto_mode_para_disabled_no_webhook(self, tmp_path, monkeypatch) -> None:
        # When para is disabled and no webhook is configured, the para_reason
        # ("para_dispatcher_disabled") takes precedence over the webhook reason.
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "auto")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "disabled")
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_DELEGATE_WEBHOOK", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        req = _make_request()
        result = svc._dispatch(req)
        assert result["accepted"] is False
        assert result["reason"] == "para_dispatcher_disabled"

    def test_para_mode_para_unavailable(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "para")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "disabled")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        req = _make_request()
        result = svc._dispatch(req)
        assert result["accepted"] is False
        assert result["reason"] == "para_dispatcher_disabled"

    def test_mcp_mode_para_unavailable(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "mcp")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "disabled")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        req = _make_request()
        result = svc._dispatch(req)
        assert result["accepted"] is False

    def test_unknown_mode_no_webhook(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "unknown_mode")
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_DELEGATE_WEBHOOK", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        req = _make_request()
        result = svc._dispatch(req)
        assert result["accepted"] is False

    def test_webhook_empty_content(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "unknown_mode")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", "http://hook.test")
        mock_resp = _mock_response(status_code=200, json_data=None, content=b"")
        mock_resp.json = MagicMock(side_effect=ValueError("no json"))
        mock_resp.text = ""
        mock_resp.content = b""
        mock_client = _mock_http_client(post_resp=mock_resp)
        svc = _make_svc(
            tmp_path,
            cli_runner=_null_runner,
            http_client_factory=lambda: mock_client,
        )
        req = _make_request()
        result = svc._dispatch(req)
        assert result["accepted"] is False

    def test_webhook_non_json_body(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "unknown_mode")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", "http://hook.test")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"not json"
        mock_resp.text = "not json"
        mock_resp.json = MagicMock(side_effect=ValueError("bad json"))
        mock_client = _mock_http_client(post_resp=mock_resp)
        svc = _make_svc(
            tmp_path,
            cli_runner=_null_runner,
            http_client_factory=lambda: mock_client,
        )
        req = _make_request()
        result = svc._dispatch(req)
        assert result["accepted"] is False
        # Non-JSON body with 200 status and no success flag → dispatch_failed
        assert result["status"] == "dispatch_failed"

    def test_webhook_accepted_with_success_flag(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "unknown_mode")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", "http://hook.test")
        mock_resp = _mock_response(status_code=200, json_data={"success": True})
        mock_client = _mock_http_client(post_resp=mock_resp)
        svc = _make_svc(
            tmp_path,
            cli_runner=_null_runner,
            http_client_factory=lambda: mock_client,
        )
        req = _make_request()
        result = svc._dispatch(req)
        assert result["accepted"] is True
        assert result["status"] == "accepted"

    def test_webhook_accepted_with_accepted_flag(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "unknown_mode")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", "http://hook.test")
        mock_resp = _mock_response(status_code=200, json_data={"accepted": True})
        mock_client = _mock_http_client(post_resp=mock_resp)
        svc = _make_svc(
            tmp_path,
            cli_runner=_null_runner,
            http_client_factory=lambda: mock_client,
        )
        req = _make_request()
        result = svc._dispatch(req)
        assert result["accepted"] is True

    def test_webhook_exception_goes_to_outbox(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "unknown_mode")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", "http://hook.test")
        mock_client = _mock_http_client(post_exc=Exception("network error"))
        svc = _make_svc(
            tmp_path,
            cli_runner=_null_runner,
            http_client_factory=lambda: mock_client,
        )
        req = _make_request()
        result = svc._dispatch(req)
        assert result["accepted"] is False
        assert result["status"] == "dispatch_error"


# ───────────────────── _dispatch_to_para error branches ─────────────────────


class TestDispatchToParaErrors:
    def test_network_error_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test")
        mock_client = _mock_http_client(get_exc=httpx.NetworkError("net error"))
        svc = _make_svc(
            tmp_path,
            cli_runner=_null_runner,
            http_client_factory=lambda: mock_client,
        )
        req = _make_request()
        result, reason = svc._dispatch_to_para(req)
        assert result is None
        assert "para_api_unreachable" in reason

    def test_connect_error_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test")
        mock_client = _mock_http_client(get_exc=httpx.ConnectError("connect error"))
        svc = _make_svc(
            tmp_path,
            cli_runner=_null_runner,
            http_client_factory=lambda: mock_client,
        )
        req = _make_request()
        result, reason = svc._dispatch_to_para(req)
        assert result is None
        assert "para_api_unreachable" in reason

    def test_general_exception_writes_outbox(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test")
        mock_client = _mock_http_client(get_exc=ValueError("bad value"))
        svc = _make_svc(
            tmp_path,
            cli_runner=_null_runner,
            http_client_factory=lambda: mock_client,
        )
        req = _make_request()
        result, reason = svc._dispatch_to_para(req)
        assert result is not None
        assert result["accepted"] is False
        assert result["status"] == "dispatch_error"


# ───────────────────── _para_token branches ─────────────────────


class TestParaToken:
    def test_env_token_returned_directly(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "env-token-123")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        token = svc._para_token(mock_client, "http://para.test")
        assert token == "env-token-123"
        mock_client.post.assert_not_called()

    def test_modstore_env_token(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", raising=False)
        monkeypatch.setenv("MODSTORE_PARA_TOKEN", "modstore-token")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        token = svc._para_token(mock_client, "http://para.test")
        assert token == "modstore-token"

    def test_devfleet_env_token(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_TOKEN", raising=False)
        monkeypatch.setenv("DEVFLEET_TOKEN", "devfleet-token")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        token = svc._para_token(mock_client, "http://para.test")
        assert token == "devfleet-token"

    def test_guest_login_success(self, tmp_path, monkeypatch) -> None:
        from app.application.super_employee_service import _PARA_TOKEN_CACHE

        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("DEVFLEET_TOKEN", raising=False)
        _PARA_TOKEN_CACHE.clear()
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        mock_resp = _mock_response(status_code=200, json_data={"token": "guest-token"})
        mock_client.post.return_value = mock_resp
        token = svc._para_token(mock_client, "http://para.test")
        assert token == "guest-token"

    def test_guest_login_access_token_field(self, tmp_path, monkeypatch) -> None:
        from app.application.super_employee_service import _PARA_TOKEN_CACHE

        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("DEVFLEET_TOKEN", raising=False)
        _PARA_TOKEN_CACHE.clear()
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        mock_resp = _mock_response(status_code=200, json_data={"access_token": "atoken"})
        mock_client.post.return_value = mock_resp
        token = svc._para_token(mock_client, "http://para.test")
        assert token == "atoken"

    def test_guest_login_failure_clears_cache(self, tmp_path, monkeypatch) -> None:
        from app.application.super_employee_service import _PARA_TOKEN_CACHE

        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("DEVFLEET_TOKEN", raising=False)
        _PARA_TOKEN_CACHE.clear()
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        # Body without "error"/"message" so fallback message is used
        mock_resp = _mock_response(status_code=401, json_data={})
        mock_client.post.return_value = mock_resp
        with pytest.raises(RuntimeError, match="Para guest 登录失败"):
            svc._para_token(mock_client, "http://para.test")
        assert ("http://para.test", "XCMAX_CODEX_SUPER_EMPLOYEE") not in _PARA_TOKEN_CACHE

    def test_guest_login_no_token_raises(self, tmp_path, monkeypatch) -> None:
        from app.application.super_employee_service import _PARA_TOKEN_CACHE

        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("DEVFLEET_TOKEN", raising=False)
        _PARA_TOKEN_CACHE.clear()
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        mock_resp = _mock_response(status_code=200, json_data={})
        mock_client.post.return_value = mock_resp
        with pytest.raises(RuntimeError, match="未返回 token"):
            svc._para_token(mock_client, "http://para.test")

    def test_cached_token_returned(self, tmp_path, monkeypatch) -> None:
        import time

        from app.application.super_employee_service import _PARA_TOKEN_CACHE

        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("DEVFLEET_TOKEN", raising=False)
        cache_key = ("http://para.test", "XCMAX_CODEX_SUPER_EMPLOYEE")
        _PARA_TOKEN_CACHE[cache_key] = ("cached-token", time.time() + 600)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        token = svc._para_token(mock_client, "http://para.test")
        assert token == "cached-token"
        mock_client.post.assert_not_called()
        _PARA_TOKEN_CACHE.clear()

    def test_expired_cache_refetches(self, tmp_path, monkeypatch) -> None:
        import time

        from app.application.super_employee_service import _PARA_TOKEN_CACHE

        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_TOKEN", raising=False)
        monkeypatch.delenv("DEVFLEET_TOKEN", raising=False)
        cache_key = ("http://para.test", "XCMAX_CODEX_SUPER_EMPLOYEE")
        _PARA_TOKEN_CACHE[cache_key] = ("expired-token", time.time() - 100)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        mock_resp = _mock_response(status_code=200, json_data={"token": "new-token"})
        mock_client.post.return_value = mock_resp
        token = svc._para_token(mock_client, "http://para.test")
        assert token == "new-token"
        _PARA_TOKEN_CACHE.clear()


# ───────────────────── _para_request ─────────────────────


class TestParaRequest:
    def test_status_ge_400_raises(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        # Body without "error"/"message" so fallback message is used
        mock_resp = _mock_response(status_code=403, json_data={})
        mock_client.request.return_value = mock_resp
        with pytest.raises(RuntimeError, match="Para API 请求失败"):
            svc._para_request(mock_client, "http://para.test", "tok", "GET", "/api/devices")

    def test_status_ge_400_returns_body_error(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        mock_resp = _mock_response(status_code=403, json_data={"error": "forbidden"})
        mock_client.request.return_value = mock_resp
        with pytest.raises(RuntimeError, match="forbidden"):
            svc._para_request(mock_client, "http://para.test", "tok", "GET", "/api/devices")

    def test_success_returns_body(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        mock_resp = _mock_response(status_code=200, json_data={"devices": []})
        mock_client.request.return_value = mock_resp
        body = svc._para_request(mock_client, "http://para.test", "tok", "GET", "/api/devices")
        assert body == {"devices": []}

    def test_post_with_json_body(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        mock_resp = _mock_response(status_code=200, json_data={"ok": True})
        mock_client.request.return_value = mock_resp
        body = svc._para_request(
            mock_client,
            "http://para.test",
            "tok",
            "POST",
            "/api/tasks",
            json_body={"title": "t"},
        )
        assert body == {"ok": True}
        # Verify json_body was passed
        call_kwargs = mock_client.request.call_args
        assert call_kwargs.kwargs.get("json") == {"title": "t"}


# ───────────────────── _ensure_para_device ─────────────────────


class TestEnsureParaDevice:
    def test_devtool_already_matches(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        device = {"id": "d1", "devTool": "codex"}
        result = svc._ensure_para_device(MagicMock(), "http://para.test", "tok", device)
        assert result is device

    def test_no_device_id_returns_original(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        device = {"devTool": "other"}
        result = svc._ensure_para_device(MagicMock(), "http://para.test", "tok", device)
        assert result is device

    def test_updated_not_dict_returns_merged(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        mock_resp = _mock_response(status_code=200, json_data={"device": "not a dict"})
        mock_client.request.return_value = mock_resp
        device = {"id": "d1", "devTool": "other"}
        result = svc._ensure_para_device(mock_client, "http://para.test", "tok", device)
        assert result["devTool"] == "codex"
        assert result["id"] == "d1"

    def test_updated_dict_returned(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        updated = {"id": "d1", "devTool": "codex", "name": "updated"}
        mock_resp = _mock_response(status_code=200, json_data={"device": updated})
        mock_client.request.return_value = mock_resp
        device = {"id": "d1", "devTool": "other"}
        result = svc._ensure_para_device(mock_client, "http://para.test", "tok", device)
        assert result == updated


# ───────────────────── _create_para_task ─────────────────────


class TestCreateParaTask:
    def test_repo_url_included(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "https://repo.git")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        mock_resp = _mock_response(
            status_code=200,
            json_data={"task": {"id": "t1", "status": "pending"}, "subtask": {"id": "s1"}},
        )
        mock_client.request.return_value = mock_resp
        req = _make_request()
        result = svc._create_para_task(
            mock_client,
            "http://para.test",
            "tok",
            req,
            [{"id": "d1", "name": "dev1"}],
            tier=1,
        )
        assert result["accepted"] is True
        assert result["task_id"] == "t1"
        # Verify repo_url was in the request body
        call_kwargs = mock_client.request.call_args
        assert call_kwargs.kwargs.get("json", {}).get("repo_url") == "https://repo.git"

    def test_task_not_dict_keeps_previous(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        mock_resp = _mock_response(
            status_code=200,
            json_data={"task": "not a dict", "subtask": {"id": "s1"}},
        )
        mock_client.request.return_value = mock_resp
        req = _make_request()
        result = svc._create_para_task(
            mock_client,
            "http://para.test",
            "tok",
            req,
            [{"id": "d1", "name": "dev1"}],
            tier=2,
        )
        assert result["accepted"] is True
        assert result["task_id"] == ""

    def test_task_id_chained_across_devices(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        # First call returns task with id, second call should include task_id
        responses = [
            _mock_response(
                status_code=200, json_data={"task": {"id": "t1"}, "subtask": {"id": "s1"}}
            ),
            _mock_response(
                status_code=200, json_data={"task": {"id": "t1"}, "subtask": {"id": "s2"}}
            ),
        ]
        mock_client.request.side_effect = responses
        req = _make_request()
        result = svc._create_para_task(
            mock_client,
            "http://para.test",
            "tok",
            req,
            [{"id": "d1", "name": "dev1"}, {"id": "d2", "name": "dev2"}],
            tier=2,
        )
        assert result["task_id"] == "t1"
        # Second call should have task_id in body
        second_call = mock_client.request.call_args_list[1]
        assert second_call.kwargs.get("json", {}).get("task_id") == "t1"

    def test_subtask_not_dict(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_client = MagicMock()
        mock_resp = _mock_response(
            status_code=200,
            json_data={"task": {"id": "t1"}, "subtask": "not a dict"},
        )
        mock_client.request.return_value = mock_resp
        req = _make_request()
        result = svc._create_para_task(
            mock_client,
            "http://para.test",
            "tok",
            req,
            [{"id": "d1", "name": "dev1"}],
            tier=1,
        )
        assert result["accepted"] is True
        assert result["devices"][0]["subtask_id"] == ""


# ───────────────────── _cli_subprocess_env ─────────────────────


class TestCliSubprocessEnv:
    def test_no_proxy_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CLI_PROXY", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._cli_subprocess_env() is None

    def test_proxy_set_injects_env_vars(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CLI_PROXY", "http://proxy:8080")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        env = svc._cli_subprocess_env()
        assert env is not None
        assert env["HTTP_PROXY"] == "http://proxy:8080"
        assert env["HTTPS_PROXY"] == "http://proxy:8080"
        assert env["ALL_PROXY"] == "http://proxy:8080"
        assert env["http_proxy"] == "http://proxy:8080"
        assert env["https_proxy"] == "http://proxy:8080"
        assert env["all_proxy"] == "http://proxy:8080"

    def test_empty_proxy_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CLI_PROXY", "  ")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._cli_subprocess_env() is None


# ───────────────────── _fetch_para_task ─────────────────────


class TestFetchParaTask:
    def test_no_api_url_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "disabled")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._fetch_para_task("t1") is None

    def test_empty_task_id_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._fetch_para_task("") is None

    def test_task_not_dict_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "tok")
        mock_resp = _mock_response(status_code=200, json_data={"task": "not a dict"})
        mock_client = _mock_http_client(request_resp=mock_resp)
        svc = _make_svc(
            tmp_path,
            cli_runner=_null_runner,
            http_client_factory=lambda: mock_client,
        )
        assert svc._fetch_para_task("t1") is None

    def test_http_error_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "tok")
        mock_client = _mock_http_client(request_exc=httpx.HTTPError("http error"))
        svc = _make_svc(
            tmp_path,
            cli_runner=_null_runner,
            http_client_factory=lambda: mock_client,
        )
        assert svc._fetch_para_task("t1") is None

    def test_value_error_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "tok")
        mock_client = _mock_http_client(request_exc=ValueError("bad"))
        svc = _make_svc(
            tmp_path,
            cli_runner=_null_runner,
            http_client_factory=lambda: mock_client,
        )
        assert svc._fetch_para_task("t1") is None

    def test_key_error_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "tok")
        mock_client = _mock_http_client(request_exc=KeyError("key"))
        svc = _make_svc(
            tmp_path,
            cli_runner=_null_runner,
            http_client_factory=lambda: mock_client,
        )
        assert svc._fetch_para_task("t1") is None

    def test_type_error_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "tok")
        mock_client = _mock_http_client(request_exc=TypeError("type"))
        svc = _make_svc(
            tmp_path,
            cli_runner=_null_runner,
            http_client_factory=lambda: mock_client,
        )
        assert svc._fetch_para_task("t1") is None

    def test_success_returns_task(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test")
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "tok")
        task = {"id": "t1", "status": "completed"}
        mock_resp = _mock_response(status_code=200, json_data={"task": task})
        mock_client = _mock_http_client(request_resp=mock_resp)
        svc = _make_svc(
            tmp_path,
            cli_runner=_null_runner,
            http_client_factory=lambda: mock_client,
        )
        assert svc._fetch_para_task("t1") == task


# ───────────────────── _refresh_dispatcher_row ─────────────────────


class TestRefreshDispatcherRow:
    def test_no_change_when_values_match(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        row = {
            "task_id": "t1",
            "task_status": "completed",
            "status": "completed",
            "body": "old body",
        }
        task = {"id": "t1", "status": "completed"}
        changed = svc._refresh_dispatcher_row(row, task)
        # body changes because _para_task_status_reply generates new body
        # but task_id and task_status don't change
        assert row["task_id"] == "t1"
        assert row["task_status"] == "completed"

    def test_change_when_task_id_differs(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        row = {"task_id": "", "task_status": "", "status": "queued", "body": ""}
        task = {"id": "t1", "status": "running"}
        changed = svc._refresh_dispatcher_row(row, task)
        assert changed is True
        assert row["task_id"] == "t1"
        assert row["task_status"] == "running"

    def test_change_when_status_differs(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        row = {"task_id": "t1", "task_status": "pending", "status": "queued", "body": ""}
        task = {"id": "t1", "status": "completed"}
        changed = svc._refresh_dispatcher_row(row, task)
        assert changed is True
        assert row["task_status"] == "completed"

    def test_empty_task_status_keeps_row_status(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        row = {"task_id": "t1", "task_status": "", "status": "queued", "body": ""}
        task = {"id": "t1", "status": ""}
        svc._refresh_dispatcher_row(row, task)
        assert row["status"] == "queued"


# ───────────────────── _upsert_result_messages ─────────────────────


class TestUpsertResultMessages:
    def test_existing_message_updated(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        existing = {
            "user_id": 1,
            "kind": "codex_result",
            "task_id": "t1",
            "subtask_id": "s1",
            "body": "old",
            "status": "running",
            "task_status": "",
            "device_name": "",
        }
        rows = [existing]
        dispatch_row = {"dispatch_request_id": "r1"}
        task = {
            "id": "t1",
            "subTasks": [{"id": "s1", "status": "completed", "logs": [{"content": "done"}]}],
        }
        changed = svc._upsert_result_messages(
            user_id=1,
            dispatch_row=dispatch_row,
            task=task,
            rows=rows,
        )
        assert changed is True
        assert existing["status"] == "completed"
        assert existing["task_status"] == ""
        assert "done" in existing["body"]

    def test_new_message_appended(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        rows = []
        dispatch_row = {"dispatch_request_id": "r1"}
        task = {
            "id": "t1",
            "subTasks": [{"id": "s1", "status": "completed", "logs": [{"content": "done"}]}],
        }
        changed = svc._upsert_result_messages(
            user_id=1,
            dispatch_row=dispatch_row,
            task=task,
            rows=rows,
        )
        assert changed is True
        assert len(rows) == 1
        assert rows[0]["kind"] == "codex_result"
        assert rows[0]["status"] == "completed"

    def test_skip_non_terminal_subtask(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        rows = []
        dispatch_row = {"dispatch_request_id": "r1"}
        task = {
            "id": "t1",
            "subTasks": [{"id": "s1", "status": "running", "logs": []}],
        }
        changed = svc._upsert_result_messages(
            user_id=1,
            dispatch_row=dispatch_row,
            task=task,
            rows=rows,
        )
        assert changed is False
        assert len(rows) == 0

    def test_skip_empty_body(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        rows = []
        dispatch_row = {"dispatch_request_id": "r1"}
        task = {
            "id": "t1",
            "subTasks": [{"id": "s1", "status": "completed", "logs": []}],
        }
        # subtask completed but no logs and no last_error → body is "prefix\n\ntool 已完成该子任务。"
        # which is non-empty, so this WILL be added
        changed = svc._upsert_result_messages(
            user_id=1,
            dispatch_row=dispatch_row,
            task=task,
            rows=rows,
        )
        # body is non-empty (completed → "已完成该子任务")
        assert changed is True

    def test_failed_subtask_with_error(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        rows = []
        dispatch_row = {"dispatch_request_id": "r1"}
        task = {
            "id": "t1",
            "subTasks": [{"id": "s1", "status": "failed", "last_error": "boom", "logs": []}],
        }
        changed = svc._upsert_result_messages(
            user_id=1,
            dispatch_row=dispatch_row,
            task=task,
            rows=rows,
        )
        assert changed is True
        assert "boom" in rows[0]["body"]

    def test_uses_dispatch_row_task_id_when_task_no_id(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        rows = []
        dispatch_row = {"dispatch_request_id": "r1", "task_id": "from_dispatch"}
        task = {
            "subTasks": [{"id": "s1", "status": "completed", "logs": [{"content": "ok"}]}],
        }
        svc._upsert_result_messages(
            user_id=1,
            dispatch_row=dispatch_row,
            task=task,
            rows=rows,
        )
        assert rows[0]["task_id"] == "from_dispatch"


# ───────────────────── _session_get / _session_set ─────────────────────


class TestSessionStore:
    @pytest.fixture(autouse=True)
    def _isolate_session_store(self, tmp_path, monkeypatch):
        # _session_store_path uses get_app_data_dir() which is global; redirect
        # it to tmp_path so tests are fully isolated from each other.
        monkeypatch.setattr(
            "app.application.super_employee_service.get_app_data_dir",
            lambda: str(tmp_path),
        )

    def test_session_get_no_file_returns_empty(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._session_get("key") == {}

    def test_session_get_invalid_json_returns_empty(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        store = svc._session_store_path()
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text("not json", encoding="utf-8")
        assert svc._session_get("key") == {}

    def test_session_get_valid_data(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        store = svc._session_store_path()
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps({"key": {"session_id": "sid1"}}), encoding="utf-8")
        result = svc._session_get("key")
        assert result == {"session_id": "sid1"}

    def test_session_get_non_dict_data_returns_empty(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        store = svc._session_store_path()
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
        assert svc._session_get("key") == {}

    def test_session_get_non_dict_value_returns_empty(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        store = svc._session_store_path()
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps({"key": "not a dict"}), encoding="utf-8")
        assert svc._session_get("key") == {}

    def test_session_set_creates_file(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        svc._session_set("key", {"session_id": "sid1"})
        result = svc._session_get("key")
        assert result == {"session_id": "sid1"}

    def test_session_set_overwrites_existing_key(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        svc._session_set("key1", {"session_id": "sid1"})
        svc._session_set("key2", {"session_id": "sid2"})
        svc._session_set("key1", {"session_id": "sid1_updated"})
        assert svc._session_get("key1") == {"session_id": "sid1_updated"}
        assert svc._session_get("key2") == {"session_id": "sid2"}

    def test_session_set_invalid_existing_file(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        store = svc._session_store_path()
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text("not json", encoding="utf-8")
        svc._session_set("key", {"session_id": "sid1"})
        assert svc._session_get("key") == {"session_id": "sid1"}


# ───────────────────── _parse_stream_json_full ─────────────────────


class TestParseStreamJsonFull:
    def test_extracts_session_id(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        out = '{"type":"result","result":"hello","session_id":"sess-123"}\n'
        body, sid = svc._parse_stream_json_full(out)
        assert body == "hello"
        assert sid == "sess-123"

    def test_takes_last_session_id(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        out = (
            '{"type":"assistant","session_id":"sess-1"}\n'
            '{"type":"result","result":"done","session_id":"sess-2"}\n'
        )
        body, sid = svc._parse_stream_json_full(out)
        assert sid == "sess-2"

    def test_no_session_id_returns_empty(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        out = '{"type":"result","result":"hello"}\n'
        body, sid = svc._parse_stream_json_full(out)
        assert body == "hello"
        assert sid == ""

    def test_invalid_json_lines_skipped(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        out = 'not json\n{"type":"result","result":"ok","session_id":"s1"}\n'
        body, sid = svc._parse_stream_json_full(out)
        assert body == "ok"
        assert sid == "s1"

    def test_non_dict_events_skipped(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        out = '["list","not","dict"]\n{"type":"result","result":"ok","session_id":"s1"}\n'
        body, sid = svc._parse_stream_json_full(out)
        assert body == "ok"


# ───────────────────── _parse_claude_stream_json ─────────────────────


class TestParseClaudeStreamJson:
    def test_result_event_string(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        out = '{"type":"result","result":"final answer"}\n'
        assert svc._parse_claude_stream_json(out) == "final answer"

    def test_result_event_non_string_ignored(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        out = '{"type":"result","result":123}\n'
        # result is not a string, falls through to assistant text
        assert svc._parse_claude_stream_json(out) == ""

    def test_assistant_event_text_blocks(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        out = '{"type":"assistant","message":{"content":[{"type":"text","text":"hello world"}]}}\n'
        assert svc._parse_claude_stream_json(out) == "hello world"

    def test_assistant_event_non_text_blocks_skipped(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        out = '{"type":"assistant","message":{"content":[{"type":"tool_use","text":"skip"}]}}\n'
        assert svc._parse_claude_stream_json(out) == ""

    def test_assistant_event_empty_text_skipped(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        out = '{"type":"assistant","message":{"content":[{"type":"text","text":"  "}]}}\n'
        assert svc._parse_claude_stream_json(out) == ""

    def test_result_takes_priority_over_assistant(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        out = (
            '{"type":"assistant","message":{"content":[{"type":"text","text":"partial"}]}}\n'
            '{"type":"result","result":"final"}\n'
        )
        assert svc._parse_claude_stream_json(out) == "final"

    def test_non_dict_event_skipped(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        out = '["not","dict"]\n{"type":"result","result":"ok"}\n'
        assert svc._parse_claude_stream_json(out) == "ok"

    def test_message_not_dict(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        out = '{"type":"assistant","message":"not a dict"}\n'
        assert svc._parse_claude_stream_json(out) == ""

    def test_empty_output(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._parse_claude_stream_json("") == ""

    def test_lines_not_starting_with_brace_skipped(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        out = 'some log line\n{"type":"result","result":"ok"}\n'
        assert svc._parse_claude_stream_json(out) == "ok"


# ───────────────────── _verify_workspace ─────────────────────


class TestVerifyWorkspace:
    def test_custom_command_passes(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CLAUDE_VERIFY_CMD", "true")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        ok, msg = svc._verify_workspace(str(tmp_path))
        assert ok is True
        assert "自定义验证命令通过" in msg

    def test_custom_command_fails(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CLAUDE_VERIFY_CMD", "false")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        ok, msg = svc._verify_workspace(str(tmp_path))
        assert ok is False

    def test_custom_command_exception(self, tmp_path, monkeypatch) -> None:
        # When subprocess.run raises an exception (e.g. timeout), the
        # "验证命令异常" branch is taken. We mock subprocess.run to raise.
        monkeypatch.setenv("XCMAX_CLAUDE_VERIFY_CMD", "some_cmd")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        with patch(
            "app.application.super_employee_service.subprocess.run",
            side_effect=TimeoutError("timed out"),
        ):
            ok, msg = svc._verify_workspace(str(tmp_path))
        assert ok is False
        assert "验证命令异常" in msg

    def test_custom_command_nonzero_returns_stderr(self, tmp_path, monkeypatch) -> None:
        # A nonexistent command via shell returns non-zero exit code (not an
        # exception); the stderr/stdout is returned as the failure message.
        monkeypatch.setenv("XCMAX_CLAUDE_VERIFY_CMD", "nonexistent_cmd_xyz")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        ok, msg = svc._verify_workspace(str(tmp_path))
        assert ok is False
        assert "nonexistent_cmd_xyz" in msg or "not found" in msg

    def test_no_changes_passes(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        # tmp_path is not a git repo, so git status fails → changed=[]
        ok, msg = svc._verify_workspace(str(tmp_path))
        assert ok is True
        assert "无文件改动" in msg

    def test_python_compile_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        # Create a .py file with syntax error
        bad_py = tmp_path / "bad.py"
        bad_py.write_text("def broken(:\n", encoding="utf-8")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        # Mock git status to return our file
        mock_result = MagicMock()
        mock_result.stdout = "?? bad.py\n"
        mock_result.returncode = 0
        with patch.object(svc, "_git", return_value=mock_result):
            ok, msg = svc._verify_workspace(str(tmp_path))
            assert ok is False
            assert "Python 语法错误" in msg

    def test_python_compile_success(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        good_py = tmp_path / "good.py"
        good_py.write_text("x = 1\n", encoding="utf-8")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_result = MagicMock()
        mock_result.stdout = "?? good.py\n"
        mock_result.returncode = 0
        with patch.object(svc, "_git", return_value=mock_result):
            ok, msg = svc._verify_workspace(str(tmp_path))
            assert ok is True
            assert "1 个改动的 .py" in msg

    def test_non_py_changes_pass_without_compile(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_result = MagicMock()
        mock_result.stdout = "?? readme.md\n"
        mock_result.returncode = 0
        with patch.object(svc, "_git", return_value=mock_result):
            ok, msg = svc._verify_workspace(str(tmp_path))
            assert ok is True
            assert "非 .py" in msg

    def test_rename_path_parsed(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_result = MagicMock()
        mock_result.stdout = "R  old.py -> new.py\n"
        mock_result.returncode = 0
        with patch.object(svc, "_git", return_value=mock_result):
            ok, msg = svc._verify_workspace(str(tmp_path))
            assert ok is True

    def test_git_exception_returns_no_changes(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CLAUDE_VERIFY_CMD", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        with patch.object(svc, "_git", side_effect=Exception("git error")):
            ok, msg = svc._verify_workspace(str(tmp_path))
            assert ok is True
            assert "无文件改动" in msg


# ───────────────────── _commit_and_push ─────────────────────


class TestCommitAndPush:
    def test_no_changes_returns_false(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_add = MagicMock()
        mock_status = MagicMock()
        mock_status.stdout = ""
        with patch.object(svc, "_git", side_effect=[mock_add, mock_status]):
            ok, msg = svc._commit_and_push(str(tmp_path), "branch", "task")
            assert ok is False
            assert "无改动可提交" in msg

    def test_commit_fails(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_add = MagicMock()
        mock_status = MagicMock()
        mock_status.stdout = "M file.py\n"
        mock_commit = MagicMock()
        mock_commit.returncode = 1
        mock_commit.stderr = "commit error"
        mock_commit.stdout = ""
        with patch.object(svc, "_git", side_effect=[mock_add, mock_status, mock_commit]):
            ok, msg = svc._commit_and_push(str(tmp_path), "branch", "task")
            assert ok is False
            assert "提交失败" in msg

    def test_push_fails(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_add = MagicMock()
        mock_status = MagicMock()
        mock_status.stdout = "M file.py\n"
        mock_commit = MagicMock()
        mock_commit.returncode = 0
        mock_commit.stderr = ""
        mock_commit.stdout = "committed"
        mock_push = MagicMock()
        mock_push.returncode = 1
        mock_push.stderr = "push error"
        mock_push.stdout = ""
        with patch.object(svc, "_git", side_effect=[mock_add, mock_status, mock_commit, mock_push]):
            ok, msg = svc._commit_and_push(str(tmp_path), "branch", "task")
            assert ok is False
            assert "push 失败" in msg

    def test_success(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_add = MagicMock()
        mock_status = MagicMock()
        mock_status.stdout = "M file.py\n"
        mock_commit = MagicMock()
        mock_commit.returncode = 0
        mock_commit.stderr = ""
        mock_commit.stdout = "committed"
        mock_push = MagicMock()
        mock_push.returncode = 0
        mock_push.stderr = ""
        mock_push.stdout = "pushed"
        with patch.object(svc, "_git", side_effect=[mock_add, mock_status, mock_commit, mock_push]):
            ok, msg = svc._commit_and_push(str(tmp_path), "branch", "task")
            assert ok is True
            assert "已 push" in msg
            assert svc._git.call_args_list[-1].args[4] == "HEAD:branch"

    def test_exception_returns_false(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        with patch.object(svc, "_git", side_effect=Exception("git crash")):
            ok, msg = svc._commit_and_push(str(tmp_path), "branch", "task")
            assert ok is False
            assert "git 异常" in msg


# ───────────────────── _prepare_worktree ─────────────────────


class TestPrepareWorktree:
    def test_not_git_repo_returns_none(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        with patch.object(svc, "_is_git_repo", return_value=False):
            assert svc._prepare_worktree(str(tmp_path), "task") is None

    def test_worktree_add_fails(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "worktree error"
        mock_result.stdout = ""
        with (
            patch.object(svc, "_is_git_repo", return_value=True),
            patch.object(svc, "_git", return_value=mock_result),
        ):
            assert svc._prepare_worktree(str(tmp_path), "task") is None

    def test_worktree_add_success(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = ""
        with (
            patch.object(svc, "_is_git_repo", return_value=True),
            patch.object(svc, "_git", return_value=mock_result) as mock_git,
        ):
            result = svc._prepare_worktree(str(tmp_path), "task")
            assert result is not None
            wt_path, branch = result
            assert "super-employee/codex/" in branch

    def test_worktree_add_selected_branch_uses_detached_ref(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = ""
        with (
            patch.object(svc, "_is_git_repo", return_value=True),
            patch.object(svc, "_resolve_branch_ref", return_value="origin/feature/mobile"),
            patch.object(svc, "_git", return_value=mock_result) as mock_git,
        ):
            result = svc._prepare_worktree(str(tmp_path), "task", "origin/feature/mobile")
            assert result is not None
            _, branch = result
            assert branch == "feature/mobile"
            assert "--detach" in mock_git.call_args.args
            assert mock_git.call_args.args[-1] == "origin/feature/mobile"

    def test_worktree_add_exception(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        with (
            patch.object(svc, "_is_git_repo", return_value=True),
            patch.object(svc, "_git", side_effect=Exception("crash")),
        ):
            assert svc._prepare_worktree(str(tmp_path), "task") is None


# ───────────────────── _run_dev_task_loop ─────────────────────


class TestRunDevTaskLoop:
    def test_worktree_fail_falls_back_to_cli_once(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_stdout_runner("cli answer"))
        with patch.object(svc, "_prepare_worktree", return_value=None):
            result = svc._run_dev_task_loop("/fake/cli", "do task", str(tmp_path))
            assert "cli answer" in result

    def test_selected_branch_worktree_fail_does_not_write_live_checkout(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_stdout_runner("cli answer"))
        with (
            patch.object(svc, "_prepare_worktree", return_value=None),
            patch.object(svc, "_run_cli_once") as run_once,
        ):
            result = svc._run_dev_task_loop(
                "/fake/cli",
                "do task",
                str(tmp_path),
                {"branch_context": "feature/mobile"},
            )
            assert "选中的工作分支不可用" in result
            run_once.assert_not_called()

    def test_verify_fail_triggers_fix(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_stdout_runner("fixed"))
        wt_path = str(tmp_path / "wt")
        Path(wt_path).mkdir()
        with (
            patch.object(svc, "_prepare_worktree", return_value=(wt_path, "branch")),
            patch.object(svc, "_verify_workspace", side_effect=[(False, "error"), (True, "ok")]),
            patch.object(svc, "_commit_and_push", return_value=(True, "pushed")),
            patch.object(svc, "_remove_worktree"),
        ):
            result = svc._run_dev_task_loop("/fake/cli", "do task", str(tmp_path))
            assert "fixed" in result

    def test_success_path(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_stdout_runner("done"))
        wt_path = str(tmp_path / "wt")
        Path(wt_path).mkdir()
        with (
            patch.object(svc, "_prepare_worktree", return_value=(wt_path, "branch")),
            patch.object(svc, "_verify_workspace", return_value=(True, "ok")),
            patch.object(svc, "_commit_and_push", return_value=(True, "pushed")),
            patch.object(svc, "_remove_worktree"),
        ):
            result = svc._run_dev_task_loop("/fake/cli", "do task", str(tmp_path))
            assert "done" in result
            assert "✅" in result


# ───────────────────── _ensure_session_workspace ─────────────────────


class TestEnsureSessionWorkspace:
    @pytest.fixture(autouse=True)
    def _isolate_session_store(self, tmp_path, monkeypatch):
        # _session_store_path and _ensure_session_workspace use get_app_data_dir()
        # which is global; redirect it to tmp_path so tests are fully isolated.
        monkeypatch.setattr(
            "app.application.super_employee_service.get_app_data_dir",
            lambda: str(tmp_path),
        )

    def test_existing_workspace_returned(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        wt = str(tmp_path / "existing_wt")
        Path(wt).mkdir()
        # Pre-populate session store
        svc._session_set("codex:test", {"workspace": wt, "branch": "b1"})
        result = svc._ensure_session_workspace("codex:test")
        assert result == (wt, "b1")

    def test_not_git_repo_returns_none(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        with (
            patch.object(svc, "_is_git_repo", return_value=False),
            patch.object(svc, "_cli_workspace", return_value=str(tmp_path)),
        ):
            result = svc._ensure_session_workspace("codex:newkey")
            assert result == (None, None)

    def test_worktree_add_existing_branch(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_remove = MagicMock()  # worktree remove (in try/except)
        mock_rev_parse = MagicMock()
        mock_rev_parse.returncode = 0  # branch exists
        mock_worktree_add = MagicMock()
        mock_worktree_add.returncode = 0
        mock_worktree_add.stderr = ""
        mock_worktree_add.stdout = ""
        with (
            patch.object(svc, "_is_git_repo", return_value=True),
            patch.object(svc, "_cli_workspace", return_value=str(tmp_path)),
            patch.object(svc, "_git", side_effect=[mock_remove, mock_rev_parse, mock_worktree_add]),
        ):
            result = svc._ensure_session_workspace("codex:newkey2")
            assert result[0] is not None

    def test_worktree_add_new_branch(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_remove = MagicMock()  # worktree remove (in try/except)
        mock_rev_parse = MagicMock()
        mock_rev_parse.returncode = 1  # branch doesn't exist
        mock_worktree_add = MagicMock()
        mock_worktree_add.returncode = 0
        mock_worktree_add.stderr = ""
        mock_worktree_add.stdout = ""
        with (
            patch.object(svc, "_is_git_repo", return_value=True),
            patch.object(svc, "_cli_workspace", return_value=str(tmp_path)),
            patch.object(svc, "_git", side_effect=[mock_remove, mock_rev_parse, mock_worktree_add]),
        ):
            result = svc._ensure_session_workspace("codex:newkey3")
            assert result[0] is not None
            assert "super-employee/codex/" in result[1]

    def test_worktree_add_fails_returns_none(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_remove = MagicMock()  # worktree remove (in try/except)
        mock_rev_parse = MagicMock()
        mock_rev_parse.returncode = 1
        mock_worktree_add = MagicMock()
        mock_worktree_add.returncode = 1
        mock_worktree_add.stderr = "error"
        mock_worktree_add.stdout = ""
        with (
            patch.object(svc, "_is_git_repo", return_value=True),
            patch.object(svc, "_cli_workspace", return_value=str(tmp_path)),
            patch.object(svc, "_git", side_effect=[mock_remove, mock_rev_parse, mock_worktree_add]),
        ):
            result = svc._ensure_session_workspace("codex:newkey4")
            assert result == (None, None)


# ───────────────────── _conversation_mode_enabled ─────────────────────


class TestConversationMode:
    def test_default_enabled(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_CONVERSATION", raising=False)
        monkeypatch.delenv("XCMAX_CLAUDE_CONVERSATION", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._conversation_mode_enabled() is True

    def test_disabled_via_tool_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_CONVERSATION", "0")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._conversation_mode_enabled() is False

    def test_disabled_via_xcmax_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_CONVERSATION", raising=False)
        monkeypatch.setenv("XCMAX_CLAUDE_CONVERSATION", "false")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._conversation_mode_enabled() is False

    def test_disabled_variants(self, tmp_path, monkeypatch) -> None:
        for val in ("off", "disabled", "false"):
            monkeypatch.setenv("XCMAX_CODEX_CONVERSATION", val)
            svc = _make_svc(tmp_path, cli_runner=_null_runner)
            assert svc._conversation_mode_enabled() is False


# ───────────────────── _session_key ─────────────────────


class TestSessionKey:
    def test_with_conversation_id(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._session_key({"conversation_id": "conv1"}) == "codex:conv1"

    def test_without_conversation_id(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._session_key({}) == "codex"

    def test_with_none_context(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._session_key(None) == "codex"  # type: ignore[arg-type]

    def test_with_whitespace_conversation_id(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._session_key({"conversation_id": "  "}) == "codex"


# ───────────────────── _conversation_prompt ─────────────────────


class TestConversationPrompt:
    def test_resuming_returns_text(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        result = svc._conversation_prompt("hello", "/cwd", resuming=True)
        assert result == "hello"

    def test_new_session_includes_instructions(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        result = svc._conversation_prompt("hello", "/cwd", resuming=False)
        assert "超级员工" in result
        assert "hello" in result
        assert "/cwd" in result


# ───────────────────── _conversation_perm ─────────────────────


class TestConversationPerm:
    def test_default_acceptEdits(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("DEVFLEET_CLAUDE_PERMISSION_MODE", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._conversation_perm() == "acceptEdits"

    def test_custom_perm(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DEVFLEET_CLAUDE_PERMISSION_MODE", "bypassPermissions")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._conversation_perm() == "bypassPermissions"

    def test_empty_perm_falls_back(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DEVFLEET_CLAUDE_PERMISSION_MODE", "")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._conversation_perm() == "acceptEdits"


# ───────────────────── _conversation_cmd ─────────────────────


class TestConversationCmd:
    def test_without_resume(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        cmd = svc._conversation_cmd("/cli", "prompt", None)
        assert "--resume" not in cmd
        assert cmd[-1] == "prompt"

    def test_with_resume(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        cmd = svc._conversation_cmd("/cli", "prompt", "sess-123")
        assert "--resume" in cmd
        assert "sess-123" in cmd


# ───────────────────── _dev_loop_enabled ─────────────────────


class TestDevLoopEnabled:
    def test_default_enabled(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_DEV_LOOP", raising=False)
        monkeypatch.delenv("XCMAX_CLAUDE_DEV_LOOP", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._dev_loop_enabled() is True

    def test_disabled_via_tool_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_DEV_LOOP", "0")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._dev_loop_enabled() is False

    def test_disabled_via_xcmax_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_DEV_LOOP", raising=False)
        monkeypatch.setenv("XCMAX_CLAUDE_DEV_LOOP", "off")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._dev_loop_enabled() is False


# ───────────────────── _is_dispatcher_log ─────────────────────


class TestIsDispatcherLog:
    def test_subtask_prefix(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._is_dispatcher_log("子任务「abc」已派发") is True

    def test_subtask_not_dispatched_prefix(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._is_dispatcher_log("子任务未派发") is True

    def test_link_unavailable_prefix(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._is_dispatcher_log("链路不可用") is True

    def test_device_disconnected_prefix(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._is_dispatcher_log("设备连接已断开") is True

    def test_manual_prefix(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._is_dispatcher_log("手动操作") is True

    def test_non_dispatcher_log(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._is_dispatcher_log("普通日志内容") is False


# ───────────────────── _dedupe_log_tail edge cases ─────────────────────


class TestDedupeLogTailEdge:
    def test_single_item(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._dedupe_log_tail(["only one"]) == "only one"

    def test_all_duplicates(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._dedupe_log_tail(["dup", "dup", "dup"]) == "dup"

    def test_mixed_empty_and_content(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._dedupe_log_tail(["", "real", "", "  "]) == "real"

    def test_custom_max_items(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        logs = [f"item_{i}" for i in range(10)]
        result = svc._dedupe_log_tail(logs, max_items=3)
        assert result.count("\n\n") == 2  # 3 items joined by \n\n

    def test_custom_max_chars(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        logs = ["x" * 100]
        result = svc._dedupe_log_tail(logs, max_chars=50)
        assert len(result) <= 50


# ───────────────────── _is_dispatcher_ack_body ─────────────────────


class TestIsDispatcherAckBody:
    def test_multi_device_marker(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._is_dispatcher_ack_body("多设备调度器已派发") is True

    def test_queue_marker(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._is_dispatcher_ack_body("调用队列已满") is True

    def test_channel_marker(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._is_dispatcher_ack_body("调度通道异常") is True

    def test_no_online_device_marker(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._is_dispatcher_ack_body("未发现在线可用 Codex 设备") is True

    def test_task_dispatched_marker(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._is_dispatcher_ack_body("任务已派发到设备") is True

    def test_para_tool_marker(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._is_dispatcher_ack_body("Para/Codex 已就绪") is True

    def test_no_marker(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._is_dispatcher_ack_body("普通回复") is False


# ───────────────────── _extract_task_id_from_body ─────────────────────


class TestExtractTaskIdFromBody:
    def test_chinese_colon(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._extract_task_id_from_body("任务ID：abc1234567") == "abc1234567"

    def test_english_colon(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._extract_task_id_from_body("任务ID: xyz1234567") == "xyz1234567"

    def test_no_match(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._extract_task_id_from_body("no task id here") == ""

    def test_short_id_ignored(self, tmp_path) -> None:
        # ID must be at least 7 chars total (1 + 6+)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._extract_task_id_from_body("任务ID: abc") == ""


# ───────────────────── _cli_hard_cap_seconds ─────────────────────


class TestCliHardCapSeconds:
    def test_default_3600(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_CLI_HARD_CAP_SEC", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._cli_hard_cap_seconds() == 3600.0

    def test_custom_value(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_CLI_HARD_CAP_SEC", "7200")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._cli_hard_cap_seconds() == 7200.0

    def test_invalid_falls_back(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_CLI_HARD_CAP_SEC", "not a number")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._cli_hard_cap_seconds() == 3600.0


# ───────────────────── _cli_idle_timeout_seconds ─────────────────────


class TestCliIdleTimeoutSeconds:
    def test_default_180(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_CLI_IDLE_TIMEOUT_SEC", raising=False)
        monkeypatch.delenv("XCMAX_CODEX_CLI_TIMEOUT_SEC", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._cli_idle_timeout_seconds() == 180.0

    def test_custom_value(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_CLI_IDLE_TIMEOUT_SEC", "300")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._cli_idle_timeout_seconds() == 300.0

    def test_clamped_to_minimum_15(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_CLI_IDLE_TIMEOUT_SEC", "5")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._cli_idle_timeout_seconds() == 15.0

    def test_invalid_falls_back(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_CLI_IDLE_TIMEOUT_SEC", "bad")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._cli_idle_timeout_seconds() == 180.0

    def test_legacy_timeout_env_var(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_CLI_IDLE_TIMEOUT_SEC", raising=False)
        monkeypatch.setenv("XCMAX_CODEX_CLI_TIMEOUT_SEC", "240")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._cli_idle_timeout_seconds() == 240.0


# ───────────────────── _cli_fix_prompt ─────────────────────


class TestCliFixPrompt:
    def test_includes_verify_msg(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        result = svc._cli_fix_prompt("syntax error on line 5", "/cwd")
        assert "syntax error on line 5" in result
        assert "/cwd" in result

    def test_truncates_long_msg(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        long_msg = "x" * 2000
        result = svc._cli_fix_prompt(long_msg, "/cwd")
        # Message is truncated to 1500 chars in the prompt
        assert "x" * 1500 in result
        assert "x" * 1501 not in result


# ───────────────────── _remove_worktree ─────────────────────


class TestRemoveWorktree:
    def test_calls_git_worktree_remove(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        with patch.object(svc, "_git") as mock_git:
            mock_git.return_value = MagicMock()
            svc._remove_worktree(str(tmp_path), "/wt/path")
            mock_git.assert_called_once()
            args = mock_git.call_args
            assert "worktree" in args.args
            assert "remove" in args.args

    def test_exception_swallowed(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        with patch.object(svc, "_git", side_effect=Exception("fail")):
            # Should not raise
            svc._remove_worktree(str(tmp_path), "/wt/path")


# ───────────────────── _is_git_repo ─────────────────────


class TestIsGitRepo:
    def test_true_stdout(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "true\n"
        with patch.object(svc, "_git", return_value=mock_result):
            assert svc._is_git_repo(str(tmp_path)) is True

    def test_false_stdout(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "false\n"
        with patch.object(svc, "_git", return_value=mock_result):
            assert svc._is_git_repo(str(tmp_path)) is False

    def test_nonzero_returncode(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch.object(svc, "_git", return_value=mock_result):
            assert svc._is_git_repo(str(tmp_path)) is False

    def test_exception_returns_false(self, tmp_path) -> None:
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        with patch.object(svc, "_git", side_effect=Exception("fail")):
            assert svc._is_git_repo(str(tmp_path)) is False


# ───────────────────── _default_http_client ─────────────────────


class TestDefaultHttpClient:
    def test_uses_default_timeout(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_DISPATCH_TIMEOUT_SEC", raising=False)
        monkeypatch.delenv("XCMAX_CODEX_WEBHOOK_TIMEOUT_SEC", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        client = svc._default_http_client()
        assert isinstance(client, httpx.Client)
        client.close()

    def test_uses_dispatch_timeout_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_DISPATCH_TIMEOUT_SEC", "60")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        client = svc._default_http_client()
        assert isinstance(client, httpx.Client)
        client.close()

    def test_uses_webhook_timeout_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_DISPATCH_TIMEOUT_SEC", raising=False)
        monkeypatch.setenv("XCMAX_CODEX_WEBHOOK_TIMEOUT_SEC", "45")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        client = svc._default_http_client()
        assert isinstance(client, httpx.Client)
        client.close()


# ───────────────────── _para_api_url ─────────────────────


class TestParaApiUrl:
    def test_disabled_returns_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "disabled")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._para_api_url() == ""

    def test_false_returns_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "false")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._para_api_url() == ""

    def test_off_returns_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "off")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._para_api_url() == ""

    def test_none_returns_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "none")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._para_api_url() == ""

    def test_zero_returns_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "0")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._para_api_url() == ""

    def test_trailing_slash_stripped(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test/")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._para_api_url() == "http://para.test"

    def test_modstore_env_fallback(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", raising=False)
        monkeypatch.setenv("MODSTORE_PARA_API_URL", "http://modstore.test")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._para_api_url() == "http://modstore.test"

    def test_devfleet_env_fallback(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_API_URL", raising=False)
        monkeypatch.setenv("DEVFLEET_API_URL", "http://devfleet.test")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._para_api_url() == "http://devfleet.test"

    def test_default_url(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_API_URL", raising=False)
        monkeypatch.delenv("DEVFLEET_API_URL", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._para_api_url() == "http://127.0.0.1:3001"


# ───────────────────── _local_device_id ─────────────────────


class TestLocalDeviceId:
    def test_tool_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", "dev-1")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._local_device_id() == "dev-1"

    def test_modstore_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", raising=False)
        monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "dev-2")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._local_device_id() == "dev-2"

    def test_devfleet_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_DEVICE_ID", raising=False)
        monkeypatch.setenv("DEVFLEET_DEVICE_ID", "dev-3")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._local_device_id() == "dev-3"

    def test_empty_when_no_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", raising=False)
        monkeypatch.delenv("MODSTORE_PARA_DEVICE_ID", raising=False)
        monkeypatch.delenv("DEVFLEET_DEVICE_ID", raising=False)
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._local_device_id() == ""

    def test_whitespace_stripped(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DEVICE_ID", "  dev-1  ")
        svc = _make_svc(tmp_path, cli_runner=_null_runner)
        assert svc._local_device_id() == "dev-1"
