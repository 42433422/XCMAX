"""扩展覆盖：employee_specialized_tools 缺失分支（_run_cmd/_api_call 异常 + 工具分支）。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.mod_sdk.employee_specialized_tools as est
from app.mod_sdk.employee_specialized_tools import (
    _api_call,
    _err,
    _mask_secret,
    _ok,
    _provider_base_url,
    _provider_has_key,
    _provider_model,
    _read_env_file,
    _run_cmd,
    handle_specialized,
    tool_git_diff,
    tool_list_deploy_scripts,
    tool_list_scripts,
    tool_nginx_test,
    tool_pack_release,
    tool_patch_file,
    tool_run_mypy,
    tool_run_pytest,
    tool_run_ruff_check,
    tool_run_ruff_format,
    tool_sandbox_python,
    tool_tail_logs,
    tool_trigger_gh_workflow,
    tool_validate_employee_pack,
    tool_write_file,
)

# ---------------------------------------------------------------------------
# _run_cmd — 异常分支
# ---------------------------------------------------------------------------


class TestRunCmdErrorBranches:
    @pytest.mark.asyncio
    async def test_timeout_error(self):
        async def _fake_communicate():
            raise TimeoutError()

        proc = AsyncMock()
        proc.communicate = _fake_communicate

        async def _create_proc(*a, **kw):
            return proc

        with patch("asyncio.create_subprocess_exec", new=_create_proc):
            with patch("asyncio.wait_for", side_effect=TimeoutError()):
                r = await _run_cmd(["echo", "hi"])
        assert r["ok"] is False
        assert "timeout" in r["stderr"]
        assert r["returncode"] == -1

    @pytest.mark.asyncio
    async def test_file_not_found_error(self):
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("no such file"),
        ):
            r = await _run_cmd(["nonexistent_binary_abc"])
        assert r["ok"] is False
        assert r["returncode"] == -1
        assert "no such file" in r["stderr"]

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=OSError("permission denied"),
        ):
            r = await _run_cmd(["ls"])
        assert r["ok"] is False
        assert r["returncode"] == -1
        assert "permission denied" in r["stderr"]

    @pytest.mark.asyncio
    async def test_cwd_none_passes_none_to_subprocess(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"ok", b"")
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            with patch("asyncio.wait_for", return_value=(b"ok", b"")):
                await _run_cmd(["echo"], cwd=None)
        call_kw = mock_exec.call_args.kwargs
        assert call_kw.get("cwd") is None

    @pytest.mark.asyncio
    async def test_stdout_none_decodes_empty_string(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", return_value=(None, None)):
                r = await _run_cmd(["echo"])
        assert r["stdout"] == ""
        assert r["stderr"] == ""


# ---------------------------------------------------------------------------
# _api_call — 异常分支
# ---------------------------------------------------------------------------


class TestApiCallErrorBranches:
    @pytest.mark.asyncio
    async def test_httpx_none_returns_error(self):
        """httpx 未安装时返回结构化 error。"""
        original = est.httpx
        try:
            est.httpx = None
            r = await _api_call("GET", "/ping")
        finally:
            est.httpx = original
        assert r["ok"] is False
        assert "httpx" in r["error"]

    @pytest.mark.asyncio
    async def test_json_parse_failure_falls_back_to_text(self):
        """resp.json() 抛出异常时降级为 resp.text。"""
        import httpx

        mock_resp = MagicMock()
        mock_resp.json.side_effect = Exception("parse error")
        mock_resp.text = "plain text body"
        mock_resp.is_success = True
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.request = AsyncMock(return_value=mock_resp)

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            r = await _api_call("GET", "/ping")
        assert r["body"] == "plain text body"
        assert r["ok"] is True

    @pytest.mark.asyncio
    async def test_network_exception_returns_error(self):
        """网络异常转为结构化结果。"""
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            r = await _api_call("POST", "/api/action")
        assert r["ok"] is False
        assert "error" in r

    @pytest.mark.asyncio
    async def test_path_without_leading_slash(self):
        """path 不以 / 开头时 URL 拼接仍正确。"""
        import httpx

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_resp.is_success = True
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.request = AsyncMock(return_value=mock_resp)

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            r = await _api_call("GET", "health", api_base="http://localhost:9999")
        assert r["ok"] is True
        # 验证 URL 包含 health
        call_args = mock_client.request.call_args
        assert "health" in call_args.args[1]


# ---------------------------------------------------------------------------
# 质量工具 — args/targets 为 str 时拆分
# ---------------------------------------------------------------------------


class TestQualityToolStringArgs:
    @pytest.mark.asyncio
    async def test_run_pytest_args_as_string(self):
        with patch.object(est, "_run_cmd", return_value={"returncode": 0, "stdout": "ok", "stderr": "", "ok": True}) as mock_cmd:
            result = await tool_run_pytest({"args": "tests/ -q --tb=short"}, {})
        assert result["ok"] is True
        # 确认 args 被 split 成列表
        cmd_args = mock_cmd.call_args.args[0]
        assert "tests/" in cmd_args
        assert "-q" in cmd_args

    @pytest.mark.asyncio
    async def test_run_pytest_extra_env_as_dict(self):
        with patch.object(est, "_run_cmd", return_value={"returncode": 0, "stdout": "", "stderr": "", "ok": True}) as mock_cmd:
            await tool_run_pytest({"env": {"MY_VAR": "1"}}, {})
        call_kw = mock_cmd.call_args.kwargs
        assert call_kw["env"].get("MY_VAR") == "1"

    @pytest.mark.asyncio
    async def test_run_ruff_check_targets_as_string(self):
        with patch.object(est, "_run_cmd", return_value={"returncode": 0, "stdout": "", "stderr": "", "ok": True}) as mock_cmd:
            result = await tool_run_ruff_check({"targets": "app/ tests/"}, {})
        assert result["ok"] is True
        cmd_args = mock_cmd.call_args.args[0]
        assert "app/" in cmd_args
        assert "tests/" in cmd_args

    @pytest.mark.asyncio
    async def test_run_ruff_format_targets_as_string(self):
        with patch.object(est, "_run_cmd", return_value={"returncode": 1, "stdout": "diff", "stderr": "", "ok": False}) as mock_cmd:
            result = await tool_run_ruff_format({"targets": "app/"}, {})
        assert result["ok"] is True  # _ok wrapper always returns ok=True for summary
        cmd_args = mock_cmd.call_args.args[0]
        assert "app/" in cmd_args

    @pytest.mark.asyncio
    async def test_run_mypy_targets_as_string(self):
        with patch.object(est, "_run_cmd", return_value={"returncode": 0, "stdout": "Success", "stderr": "", "ok": True}) as mock_cmd:
            result = await tool_run_mypy({"targets": "app/ tests/"}, {})
        assert result["ok"] is True
        cmd_args = mock_cmd.call_args.args[0]
        assert "app/" in cmd_args
        assert "tests/" in cmd_args

    @pytest.mark.asyncio
    async def test_run_pytest_default_args(self):
        """无参数时使用默认 args。"""
        with patch.object(est, "_run_cmd", return_value={"returncode": 0, "stdout": "", "stderr": "", "ok": True}) as mock_cmd:
            await tool_run_pytest({}, {})
        cmd_args = mock_cmd.call_args.args[0]
        assert "tests/" in cmd_args


# ---------------------------------------------------------------------------
# git_diff — ref 和 stat 分支
# ---------------------------------------------------------------------------


class TestGitDiffBranches:
    @pytest.mark.asyncio
    async def test_git_diff_with_ref(self):
        with patch.object(est, "_run_cmd", return_value={"returncode": 0, "stdout": "diff", "stderr": "", "ok": True}) as mock_cmd:
            r = await tool_git_diff({"ref": "HEAD~1"}, {})
        assert r["ok"] is True
        cmd = mock_cmd.call_args.args[0]
        assert "HEAD~1" in cmd

    @pytest.mark.asyncio
    async def test_git_diff_with_stat(self):
        with patch.object(est, "_run_cmd", return_value={"returncode": 0, "stdout": "stat", "stderr": "", "ok": True}) as mock_cmd:
            r = await tool_git_diff({"stat": True}, {})
        cmd = mock_cmd.call_args.args[0]
        assert "--stat" in cmd

    @pytest.mark.asyncio
    async def test_git_diff_no_ref_no_stat(self):
        with patch.object(est, "_run_cmd", return_value={"returncode": 0, "stdout": "", "stderr": "", "ok": True}) as mock_cmd:
            await tool_git_diff({}, {})
        cmd = mock_cmd.call_args.args[0]
        assert "--stat" not in cmd


# ---------------------------------------------------------------------------
# tool_trigger_gh_workflow
# ---------------------------------------------------------------------------


class TestTriggerGhWorkflow:
    @pytest.mark.asyncio
    async def test_no_confirm_returns_error(self):
        r = await tool_trigger_gh_workflow({}, {})
        assert r["ok"] is False
        assert "confirm" in r["error"]
        assert r.get("requires_confirm") is True

    @pytest.mark.asyncio
    async def test_missing_workflow_param(self):
        r = await tool_trigger_gh_workflow({"confirm": True}, {})
        assert r["ok"] is False
        assert "workflow" in r["error"]

    @pytest.mark.asyncio
    async def test_success_with_ref(self):
        with patch.object(est, "_run_cmd", return_value={"returncode": 0, "stdout": "ok", "stderr": "", "ok": True}):
            r = await tool_trigger_gh_workflow(
                {"confirm": True, "workflow": "ci.yml", "ref": "develop"}, {}
            )
        assert r["ok"] is True


# ---------------------------------------------------------------------------
# tool_nginx_test
# ---------------------------------------------------------------------------


class TestNginxTest:
    @pytest.mark.asyncio
    async def test_nginx_not_found_skipped(self):
        with patch("shutil.which", return_value=None):
            r = await tool_nginx_test({}, {})
        assert r["ok"] is True
        assert r.get("skipped") is True
        assert r["syntax_valid"] is None

    @pytest.mark.asyncio
    async def test_nginx_found_runs(self):
        with patch("shutil.which", return_value="/usr/sbin/nginx"):
            with patch.object(est, "_run_cmd", return_value={"returncode": 0, "stdout": "", "stderr": "ok", "ok": True}):
                r = await tool_nginx_test({}, {})
        assert r["syntax_valid"] is True


# ---------------------------------------------------------------------------
# tool_tail_logs
# ---------------------------------------------------------------------------


class TestTailLogs:
    @pytest.mark.asyncio
    async def test_log_dir_not_exists(self, tmp_path):
        with patch.object(est, "_FHD_ROOT", tmp_path):
            r = await tool_tail_logs({}, {})
        assert r["ok"] is True
        assert r["lines"] == []

    @pytest.mark.asyncio
    async def test_log_file_not_found(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "other.log").write_text("x")
        with patch.object(est, "_FHD_ROOT", tmp_path):
            r = await tool_tail_logs({"file": "app.log"}, {})
        assert r["ok"] is True
        assert "available_files" in r

    @pytest.mark.asyncio
    async def test_log_file_read_success(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "app.log").write_text("line1\nline2\nline3")
        with patch.object(est, "_FHD_ROOT", tmp_path):
            r = await tool_tail_logs({"lines": 2}, {})
        assert r["ok"] is True
        assert len(r["lines"]) == 2

    @pytest.mark.asyncio
    async def test_log_file_oserror(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "app.log"
        log_file.write_text("x")
        with patch.object(est, "_FHD_ROOT", tmp_path):
            with patch("pathlib.Path.read_text", side_effect=OSError("perm")):
                r = await tool_tail_logs({}, {})
        assert r["ok"] is False
        assert "perm" in r["error"]


# ---------------------------------------------------------------------------
# tool_sandbox_python
# ---------------------------------------------------------------------------


class TestSandboxPython:
    @pytest.mark.asyncio
    async def test_missing_code(self):
        r = await tool_sandbox_python({}, {})
        assert r["ok"] is False
        assert "code" in r["error"]

    @pytest.mark.asyncio
    async def test_code_too_long(self):
        r = await tool_sandbox_python({"code": "x" * 20001}, {})
        assert r["ok"] is False
        assert "20KB" in r["error"]

    @pytest.mark.asyncio
    async def test_forbidden_import_with_confirm(self):
        """有 confirm=true 时跳过危险检查，直接执行。"""
        with patch.object(est, "_run_cmd", return_value={"returncode": 0, "stdout": "/tmp", "stderr": "", "ok": True}):
            r = await tool_sandbox_python({"code": "import os; print(os.getcwd())", "confirm": True}, {})
        assert r["ok"] is True


# ---------------------------------------------------------------------------
# tool_write_file
# ---------------------------------------------------------------------------


class TestWriteFile:
    @pytest.mark.asyncio
    async def test_no_confirm(self):
        r = await tool_write_file({}, {})
        assert r["ok"] is False
        assert "confirm" in r["error"]

    @pytest.mark.asyncio
    async def test_missing_path(self):
        r = await tool_write_file({"confirm": True}, {})
        assert r["ok"] is False
        assert "path" in r["error"]

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, tmp_path):
        r = await tool_write_file(
            {"confirm": True, "path": "../../../etc/out.txt", "content": "x"},
            {"workspace_root": str(tmp_path)},
        )
        assert r["ok"] is False
        assert "越出" in r["error"]

    @pytest.mark.asyncio
    async def test_write_success(self, tmp_path):
        r = await tool_write_file(
            {"confirm": True, "path": "sub/file.txt", "content": "hello"},
            {"workspace_root": str(tmp_path)},
        )
        assert r["ok"] is True
        assert (tmp_path / "sub" / "file.txt").read_text() == "hello"

    @pytest.mark.asyncio
    async def test_write_oserror(self, tmp_path):
        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            r = await tool_write_file(
                {"confirm": True, "path": "f.txt", "content": "x"},
                {"workspace_root": str(tmp_path)},
            )
        assert r["ok"] is False
        assert "disk full" in r["error"]


# ---------------------------------------------------------------------------
# tool_patch_file
# ---------------------------------------------------------------------------


class TestPatchFile:
    @pytest.mark.asyncio
    async def test_no_confirm(self):
        r = await tool_patch_file({}, {})
        assert r["ok"] is False
        assert "confirm" in r["error"]

    @pytest.mark.asyncio
    async def test_missing_path_or_patch(self):
        r = await tool_patch_file({"confirm": True}, {})
        assert r["ok"] is False
        assert "path" in r["error"] or "patch" in r["error"]

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, tmp_path):
        r = await tool_patch_file(
            {"confirm": True, "path": "../out.py", "patch": "--- a\n+++ b\n"},
            {"workspace_root": str(tmp_path)},
        )
        assert r["ok"] is False
        assert "越出" in r["error"]

    @pytest.mark.asyncio
    async def test_target_not_file(self, tmp_path):
        r = await tool_patch_file(
            {"confirm": True, "path": "nonexistent.py", "patch": "--- a\n+++ b\n"},
            {"workspace_root": str(tmp_path)},
        )
        assert r["ok"] is False
        assert "不存在" in r["error"]

    @pytest.mark.asyncio
    async def test_patch_check_fails(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("print(1)\n")
        with patch.object(est, "_run_cmd", return_value={"returncode": 1, "stdout": "", "stderr": "bad patch", "ok": False}):
            r = await tool_patch_file(
                {"confirm": True, "path": "f.py", "patch": "--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y\n"},
                {"workspace_root": str(tmp_path)},
            )
        assert r["ok"] is False
        assert "校验失败" in r["error"]

    @pytest.mark.asyncio
    async def test_patch_apply_fails(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("print(1)\n")

        call_count = 0

        async def _fake_run_cmd(args, **kw):
            nonlocal call_count
            call_count += 1
            if "--check" in args:
                return {"returncode": 0, "stdout": "", "stderr": "", "ok": True}
            return {"returncode": 1, "stdout": "", "stderr": "conflict", "ok": False}

        with patch.object(est, "_run_cmd", side_effect=_fake_run_cmd):
            r = await tool_patch_file(
                {"confirm": True, "path": "f.py", "patch": "--- a\n+++ b\n"},
                {"workspace_root": str(tmp_path)},
            )
        assert r["ok"] is False
        assert "应用失败" in r["error"]


# ---------------------------------------------------------------------------
# tool_list_scripts
# ---------------------------------------------------------------------------


class TestListScripts:
    @pytest.mark.asyncio
    async def test_scripts_dir_not_found(self, tmp_path):
        with patch.object(est, "_FHD_ROOT", tmp_path):
            r = await tool_list_scripts({}, {})
        assert r["ok"] is True
        assert r["scripts"] == []

    @pytest.mark.asyncio
    async def test_invalid_category(self, tmp_path):
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        with patch.object(est, "_FHD_ROOT", tmp_path):
            r = await tool_list_scripts({"category": "nonexistent"}, {})
        assert r["ok"] is False
        assert "不存在" in r["error"]

    @pytest.mark.asyncio
    async def test_category_filter(self, tmp_path):
        scripts_dir = tmp_path / "scripts" / "deploy"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "pack.sh").write_text("#!/bin/bash")
        with patch.object(est, "_FHD_ROOT", tmp_path):
            r = await tool_list_scripts({"category": "deploy"}, {})
        assert r["ok"] is True
        assert len(r["shell"]) >= 1


# ---------------------------------------------------------------------------
# tool_validate_employee_pack — manifest parse error
# ---------------------------------------------------------------------------


class TestValidateEmployeePackBranches:
    @pytest.mark.asyncio
    async def test_missing_pack_id(self):
        r = await tool_validate_employee_pack({}, {})
        assert r["ok"] is False
        assert "pack_id" in r["error"]

    @pytest.mark.asyncio
    async def test_manifest_parse_error(self, tmp_path):
        emp_dir = tmp_path / "_employees" / "bad-pack"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text("{invalid json")
        with patch.object(est, "_EMPLOYEES_DIR", tmp_path / "_employees"):
            r = await tool_validate_employee_pack({"pack_id": "bad-pack"}, {})
        assert r["ok"] is False
        assert "解析失败" in r["error"]

    @pytest.mark.asyncio
    async def test_wrong_artifact(self, tmp_path):
        import json

        emp_dir = tmp_path / "_employees" / "wp"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text(
            json.dumps({"artifact": "wrong_type", "id": "wp"})
        )
        with patch.object(est, "_EMPLOYEES_DIR", tmp_path / "_employees"):
            r = await tool_validate_employee_pack({"pack_id": "wp"}, {})
        assert r["ok"] is True
        assert r["valid"] is False
        assert any("employee_pack" in iss for iss in r["issues"])

    @pytest.mark.asyncio
    async def test_missing_id_field(self, tmp_path):
        import json

        emp_dir = tmp_path / "_employees" / "wp2"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text(
            json.dumps({"artifact": "employee_pack"})  # no "id"
        )
        with patch.object(est, "_EMPLOYEES_DIR", tmp_path / "_employees"):
            r = await tool_validate_employee_pack({"pack_id": "wp2"}, {})
        assert r["valid"] is False
        assert any("id" in iss for iss in r["issues"])

    @pytest.mark.asyncio
    async def test_missing_system_prompt(self, tmp_path):
        import json

        emp_dir = tmp_path / "_employees" / "wp3"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text(
            json.dumps({
                "artifact": "employee_pack",
                "id": "wp3",
                "employee_config_v2": {"cognition": {"agent": {}}},  # no system_prompt
            })
        )
        with patch.object(est, "_EMPLOYEES_DIR", tmp_path / "_employees"):
            r = await tool_validate_employee_pack({"pack_id": "wp3"}, {})
        assert r["valid"] is False
        assert any("system_prompt" in iss for iss in r["issues"])


# ---------------------------------------------------------------------------
# tool_list_deploy_scripts — deploy dir absent
# ---------------------------------------------------------------------------


class TestListDeployScripts:
    @pytest.mark.asyncio
    async def test_deploy_dir_missing(self, tmp_path):
        with patch.object(est, "_FHD_ROOT", tmp_path):
            r = await tool_list_deploy_scripts({}, {})
        assert r["ok"] is True
        assert r["scripts"] == []

    @pytest.mark.asyncio
    async def test_deploy_dir_present(self, tmp_path):
        deploy_dir = tmp_path / "scripts" / "deploy"
        deploy_dir.mkdir(parents=True)
        (deploy_dir / "pack.sh").write_text("#!/bin/bash")
        with patch.object(est, "_FHD_ROOT", tmp_path):
            r = await tool_list_deploy_scripts({}, {})
        assert "pack.sh" in r["scripts"]


# ---------------------------------------------------------------------------
# handle_specialized — 工具抛异常 / 返回非 dict
# ---------------------------------------------------------------------------


class TestHandleSpecializedEdgeCases:
    @pytest.mark.asyncio
    async def test_tool_raises_exception(self):
        async def _boom(params, ctx):
            raise ValueError("unexpected")

        with patch.dict(est.TOOL_REGISTRY, {"git_status": _boom}):
            with patch.dict(est.EMPLOYEE_TOOLS, {"site-content-editor": ["git_status"]}):
                r = await handle_specialized(
                    "site-content-editor",
                    {"handler": "specialized", "tool": "git_status", "params": {}},
                    {},
                )
        assert r["ok"] is False
        assert "unexpected" in r["error"]

    @pytest.mark.asyncio
    async def test_tool_returns_non_dict(self):
        async def _non_dict(params, ctx):
            return "just a string"

        with patch.dict(est.TOOL_REGISTRY, {"git_status": _non_dict}):
            with patch.dict(est.EMPLOYEE_TOOLS, {"site-content-editor": ["git_status"]}):
                r = await handle_specialized(
                    "site-content-editor",
                    {"handler": "specialized", "tool": "git_status", "params": {}},
                    {},
                )
        assert r["ok"] is True
        assert r["raw"] == "just a string"


# ---------------------------------------------------------------------------
# _mask_secret / _read_env_file / provider helpers
# ---------------------------------------------------------------------------


class TestLlmHelpers:
    def test_mask_secret_short(self):
        assert _mask_secret("abc") == "***"

    def test_mask_secret_long(self):
        s = _mask_secret("sk-abcdefghijk")
        assert s.startswith("sk-")
        assert s.endswith("ijk")
        assert "***" in s

    def test_mask_secret_empty(self):
        assert _mask_secret("") == ""

    def test_read_env_file_missing(self, tmp_path):
        r = _read_env_file(tmp_path / "nonexistent.env")
        assert r == {}

    def test_read_env_file_parses_values(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n# comment\nNO_EQ\nSECRET='s3cr3t'\n")
        r = _read_env_file(env_file)
        assert r["KEY"] == "value"
        assert r["SECRET"] == "s3cr3t"
        assert "NO_EQ" not in r

    def test_read_env_file_oserror(self, tmp_path):
        """OSError 时静默返回空 dict。"""
        env_file = tmp_path / ".env"
        env_file.write_text("K=V")
        with patch("pathlib.Path.read_text", side_effect=OSError("perm")):
            r = _read_env_file(env_file)
        assert r == {}

    def test_provider_has_key_found(self):
        profile = {"env_keys": ["DEEPSEEK_API_KEY"]}
        env = {"DEEPSEEK_API_KEY": "sk-abc"}
        assert _provider_has_key(profile, env) == "sk-abc"

    def test_provider_has_key_missing(self):
        profile = {"env_keys": ["DEEPSEEK_API_KEY"]}
        assert _provider_has_key(profile, {}) is None

    def test_provider_base_url_from_env(self):
        profile = {"base_url_env": "DEEPSEEK_BASE_URL", "base_url_default": "https://default"}
        env = {"DEEPSEEK_BASE_URL": "https://custom"}
        assert _provider_base_url(profile, env) == "https://custom"

    def test_provider_base_url_fallback(self):
        profile = {"base_url_env": "DEEPSEEK_BASE_URL", "base_url_default": "https://default"}
        assert _provider_base_url(profile, {}) == "https://default"

    def test_provider_base_url_no_env_key(self):
        profile = {"base_url_default": "https://default"}
        assert _provider_base_url(profile, {}) == "https://default"

    def test_provider_model_from_env(self):
        profile = {"model_env": "DEEPSEEK_MODEL", "default_model": "deepseek-chat"}
        env = {"DEEPSEEK_MODEL": "deepseek-coder"}
        assert _provider_model(profile, env) == "deepseek-coder"

    def test_provider_model_fallback(self):
        profile = {"model_env": "DEEPSEEK_MODEL", "default_model": "deepseek-chat"}
        assert _provider_model(profile, {}) == "deepseek-chat"

    def test_provider_model_no_env_key(self):
        profile = {"default_model": "gpt-4"}
        assert _provider_model(profile, {}) == "gpt-4"
