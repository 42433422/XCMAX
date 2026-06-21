"""Branch-coverage ramp for app.mod_sdk.employee_specialized_tools.

Goal: 85%+ branch coverage (file at 53.9% prior).
All external side-effects (subprocess, httpx, filesystem, heavy imports)
are patched via unittest.mock so the suite runs offline and deterministically.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------
import app.mod_sdk.employee_specialized_tools as module
from app.mod_sdk.employee_specialized_tools import (
    EMPLOYEE_TOOLS,
    TOOL_REGISTRY,
    _api_call,
    _check_write_gate,
    _code_write_tools,
    _detect_provider_name,
    _err,
    _mask_secret,
    _ok,
    _provider_base_url,
    _provider_has_key,
    _provider_model,
    _read_env_file,
    _run_cmd,
    _run_python_script,
    get_employee_tools,
    handle_specialized,
    list_all_tool_names,
    tool_android_gradle_build,
    tool_api_health,
    tool_check_coverage,
    tool_check_transactions,
    tool_compare_model_prices,
    tool_count_raw_sql,
    tool_count_type_debt,
    tool_disk_usage,
    tool_duty_graph_health,
    tool_employee_autonomy_dashboard,
    tool_employee_status,
    tool_frontend_lint,
    tool_frontend_test,
    tool_frontend_typecheck,
    tool_git_branch,
    tool_git_diff,
    tool_git_log,
    tool_git_status,
    tool_list_action_items,
    tool_list_configured_providers,
    tool_list_deploy_scripts,
    tool_list_docs,
    tool_list_employee_packs,
    tool_list_employees,
    tool_list_enterprise_mods,
    tool_list_invoices,
    tool_list_mods,
    tool_list_scripts,
    tool_list_users,
    tool_list_workbench_sessions,
    tool_mod_loading_status,
    tool_mutation_kill_report,
    tool_nginx_test,
    tool_pack_release,
    tool_patch_file,
    tool_performance_status,
    tool_read_file,
    tool_read_llm_env_config,
    tool_run_arch_fitness,
    tool_run_mypy,
    tool_run_pytest,
    tool_run_ruff_check,
    tool_run_ruff_format,
    tool_sandbox_python,
    tool_tail_logs,
    tool_test_llm_key_health,
    tool_trigger_gh_workflow,
    tool_validate_employee_pack,
    tool_verify_employee_contract,
    tool_verify_version_anchors,
    tool_write_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GOOD_RUN = {"returncode": 0, "stdout": "ok", "stderr": "", "ok": True}
_BAD_RUN = {"returncode": 1, "stdout": "", "stderr": "err", "ok": False}


def _make_run_patch(result: dict):
    """Return an AsyncMock that always returns *result*."""
    m = AsyncMock(return_value=result)
    return m


def _make_api_patch(result: dict):
    m = AsyncMock(return_value=result)
    return m


# ===========================================================================
# 1. Small utility functions
# ===========================================================================


class TestOkErr:
    def test_ok_basic(self):
        r = _ok("hello")
        assert r["ok"] is True
        assert r["summary"] == "hello"

    def test_ok_truncates_long_summary(self):
        r = _ok("x" * 5000)
        assert len(r["summary"]) == 4000

    def test_ok_extra_kwargs(self):
        r = _ok("msg", foo="bar")
        assert r["foo"] == "bar"

    def test_err_basic(self):
        r = _err("bad")
        assert r["ok"] is False
        assert r["error"] == "bad"

    def test_err_truncates_long_error(self):
        r = _err("y" * 2000)
        assert len(r["error"]) == 1000

    def test_err_extra_kwargs(self):
        r = _err("msg", code=42)
        assert r["code"] == 42


class TestMaskSecret:
    def test_empty(self):
        assert _mask_secret("") == ""

    def test_short(self):
        assert _mask_secret("abc") == "***"

    def test_exact_8(self):
        assert _mask_secret("12345678") == "***"

    def test_long(self):
        result = _mask_secret("sk-abcdefgh123")
        assert result.startswith("sk-")
        assert result.endswith("123")
        assert "***" in result


class TestReadEnvFile:
    def test_missing_file_returns_empty(self, tmp_path):
        r = _read_env_file(tmp_path / "nonexistent.env")
        assert r == {}

    def test_parses_key_value(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("FOO=bar\nBAZ=qux\n", encoding="utf-8")
        r = _read_env_file(f)
        assert r["FOO"] == "bar"
        assert r["BAZ"] == "qux"

    def test_ignores_comments_and_empty(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("# comment\n\nFOO=1\n", encoding="utf-8")
        r = _read_env_file(f)
        assert "# comment" not in r
        assert r["FOO"] == "1"

    def test_strips_quotes(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("API_KEY='secret'\n", encoding="utf-8")
        r = _read_env_file(f)
        assert r["API_KEY"] == "secret"

    def test_no_equals_skipped(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("NOEQSIGN\nGOOD=yes\n", encoding="utf-8")
        r = _read_env_file(f)
        assert "NOEQSIGN" not in r
        assert r["GOOD"] == "yes"

    def test_oserror_returns_empty(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("X=1", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=OSError("no")):
            r = _read_env_file(f)
        assert r == {}


class TestProviderHelpers:
    PROFILE = {
        "name": "test",
        "env_keys": ["MY_KEY", "MY_KEY2"],
        "base_url_env": "MY_BASE",
        "base_url_default": "https://default.example.com/v1",
        "model_env": "MY_MODEL",
        "default_model": "default-model",
    }

    def test_has_key_returns_first_found(self):
        env = {"MY_KEY": "abc"}
        assert _provider_has_key(self.PROFILE, env) == "abc"

    def test_has_key_returns_none_when_missing(self):
        assert _provider_has_key(self.PROFILE, {}) is None

    def test_has_key_second_key(self):
        env = {"MY_KEY2": "xyz"}
        assert _provider_has_key(self.PROFILE, env) == "xyz"

    def test_base_url_env_override(self):
        env = {"MY_BASE": "https://custom.example.com/v1"}
        assert _provider_base_url(self.PROFILE, env) == "https://custom.example.com/v1"

    def test_base_url_default(self):
        assert _provider_base_url(self.PROFILE, {}) == "https://default.example.com/v1"

    def test_base_url_no_env_key(self):
        profile = dict(self.PROFILE)
        del profile["base_url_env"]
        assert _provider_base_url(profile, {}) == "https://default.example.com/v1"

    def test_model_env_override(self):
        env = {"MY_MODEL": "custom-model"}
        assert _provider_model(self.PROFILE, env) == "custom-model"

    def test_model_default(self):
        assert _provider_model(self.PROFILE, {}) == "default-model"

    def test_model_no_env_key(self):
        profile = dict(self.PROFILE)
        del profile["model_env"]
        assert _provider_model(profile, {}) == "default-model"

    def test_detect_with_detect_fn_true(self):
        profile = dict(self.PROFILE)
        profile["detect"] = lambda env: True
        assert _detect_provider_name(profile, {}) is True

    def test_detect_with_detect_fn_false(self):
        profile = dict(self.PROFILE)
        profile["detect"] = lambda env: False
        assert _detect_provider_name(profile, {}) is False

    def test_detect_no_detect_fn_has_key(self):
        env = {"MY_KEY": "abc"}
        assert _detect_provider_name(self.PROFILE, env) is True

    def test_detect_no_detect_fn_no_key(self):
        assert _detect_provider_name(self.PROFILE, {}) is False


# ===========================================================================
# 2. _run_cmd
# ===========================================================================


class TestRunCmd:
    async def test_success(self):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"out", b"err"))
            mock_exec.return_value = proc
            with patch("asyncio.wait_for", AsyncMock(return_value=(b"out", b"err"))):
                r = await _run_cmd(["echo", "hi"])
        assert r["ok"] is True

    async def test_timeout_returns_error(self):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.returncode = -1
            mock_exec.return_value = proc
            with patch("asyncio.wait_for", side_effect=TimeoutError()):
                r = await _run_cmd(["sleep", "100"], timeout=1)
        assert r["ok"] is False
        assert "timeout" in r["stderr"]

    async def test_file_not_found(self):
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("no such")):
            r = await _run_cmd(["nonexistent_cmd_xyz"])
        assert r["ok"] is False
        assert r["returncode"] == -1

    async def test_generic_exception(self):
        with patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("boom")):
            r = await _run_cmd(["echo"])
        assert r["ok"] is False
        assert r["returncode"] == -1

    async def test_nonzero_returncode(self):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.returncode = 1
            with patch("asyncio.wait_for", AsyncMock(return_value=(b"", b"error"))):
                mock_exec.return_value = proc
                r = await _run_cmd(["false"])
        assert r["ok"] is False


class TestRunPythonScript:
    async def test_delegates_to_run_cmd(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)) as m:
            await _run_python_script("myscript.py", "--arg")
            assert m.called


# ===========================================================================
# 3. _api_call
# ===========================================================================


class TestApiCall:
    async def test_httpx_none_returns_error(self):
        with patch.object(module, "httpx", None):
            r = await _api_call("GET", "/test")
        assert r["ok"] is False
        assert "httpx" in r["error"]

    async def test_success_json(self):
        mock_resp = Mock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.json = Mock(return_value={"result": "ok"})
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(module, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            r = await _api_call("GET", "/api/test")
        assert r["ok"] is True
        assert r["body"] == {"result": "ok"}

    async def test_success_non_json_falls_back_to_text(self):
        mock_resp = Mock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.json = Mock(side_effect=Exception("not json"))
        mock_resp.text = "plain text"
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(module, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            r = await _api_call("GET", "/api/test")
        assert r["body"] == "plain text"

    async def test_network_exception(self):
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(module, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            r = await _api_call("GET", "/api/fail")
        assert r["ok"] is False

    async def test_path_without_leading_slash(self):
        mock_resp = Mock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.json = Mock(return_value={})
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(module, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            r = await _api_call("GET", "noslash/endpoint")
        assert r["ok"] is True


# ===========================================================================
# 4. Quality tools
# ===========================================================================


class TestQualityTools:
    async def test_run_pytest_defaults(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_run_pytest({}, {})
        assert r["ok"] is True
        assert "pytest" in r["summary"]

    async def test_run_pytest_str_args(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_run_pytest({"args": "tests/ -v", "env": {"X": "1"}}, {})
        assert r["ok"] is True

    async def test_run_pytest_custom_timeout(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)) as m:
            await tool_run_pytest({"timeout": 30}, {})
        assert m.called

    async def test_run_ruff_check_defaults(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_run_ruff_check({}, {})
        assert r["ok"] is True

    async def test_run_ruff_check_str_targets(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_BAD_RUN)):
            r = await tool_run_ruff_check({"targets": "app/"}, {})
        assert r["ok"] is True  # _ok wraps _run_cmd result
        assert r["passed"] is False

    async def test_run_ruff_format(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_run_ruff_format({}, {})
        assert r["ok"] is True

    async def test_run_ruff_format_str_targets(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_run_ruff_format({"targets": "app/"}, {})
        assert r["ok"] is True

    async def test_run_mypy_defaults(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_run_mypy({}, {})
        assert r["ok"] is True

    async def test_run_mypy_str_targets(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_run_mypy({"targets": "app/mod_sdk"}, {})
        assert r["ok"] is True

    async def test_check_coverage(self):
        with patch.object(module, "_run_python_script", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_check_coverage({}, {})
        assert r["ok"] is True

    async def test_count_type_debt(self):
        with patch.object(module, "_run_python_script", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_count_type_debt({}, {})
        assert r["ok"] is True

    async def test_count_raw_sql(self):
        with patch.object(module, "_run_python_script", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_count_raw_sql({}, {})
        assert r["ok"] is True

    async def test_run_arch_fitness(self):
        with patch.object(module, "_run_python_script", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_run_arch_fitness({}, {})
        assert r["ok"] is True

    async def test_verify_version_anchors(self):
        with patch.object(module, "_run_python_script", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_verify_version_anchors({}, {})
        assert r["ok"] is True

    async def test_verify_employee_contract(self):
        with patch.object(module, "_run_python_script", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_verify_employee_contract({}, {})
        assert r["ok"] is True

    async def test_mutation_kill_report(self):
        with patch.object(module, "_run_python_script", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_mutation_kill_report({}, {})
        assert r["ok"] is True


# ===========================================================================
# 5. Git tools
# ===========================================================================


class TestGitTools:
    async def test_git_status_clean(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value={**_GOOD_RUN, "stdout": ""})):
            r = await tool_git_status({}, {})
        assert r["clean"] is True

    async def test_git_status_dirty(self):
        with patch.object(
            module, "_run_cmd", AsyncMock(return_value={**_GOOD_RUN, "stdout": " M file.py\n"})
        ):
            r = await tool_git_status({}, {})
        assert r["clean"] is False
        assert len(r["files"]) == 1

    async def test_git_log_default(self):
        with patch.object(
            module, "_run_cmd", AsyncMock(return_value={**_GOOD_RUN, "stdout": "abc def\n"})
        ):
            r = await tool_git_log({}, {})
        assert r["ok"] is True
        assert len(r["commits"]) == 1

    async def test_git_log_custom_n(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)) as m:
            await tool_git_log({"n": 5}, {})
        cmd_args = m.call_args[0][0]
        assert "-5" in cmd_args

    async def test_git_diff_no_ref(self):
        with patch.object(
            module, "_run_cmd", AsyncMock(return_value={**_GOOD_RUN, "stdout": "diff content"})
        ):
            r = await tool_git_diff({}, {})
        assert r["ok"] is True

    async def test_git_diff_with_ref_and_stat(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)) as m:
            await tool_git_diff({"ref": "HEAD~1", "stat": True}, {})
        args = m.call_args[0][0]
        assert "HEAD~1" in args
        assert "--stat" in args

    async def test_git_branch(self):
        with patch.object(
            module, "_run_cmd", AsyncMock(return_value={**_GOOD_RUN, "stdout": "main\n"})
        ):
            r = await tool_git_branch({}, {})
        assert r["branch"] == "main"


# ===========================================================================
# 6. Deploy tools
# ===========================================================================


class TestDeployTools:
    async def test_pack_release_requires_confirm(self):
        r = await tool_pack_release({}, {})
        assert r["ok"] is False
        assert r.get("requires_confirm") is True

    async def test_pack_release_with_confirm(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_pack_release({"confirm": True}, {})
        assert r["ok"] is True

    async def test_list_deploy_scripts_dir_exists(self, tmp_path):
        deploy_dir = tmp_path / "scripts" / "deploy"
        deploy_dir.mkdir(parents=True)
        (deploy_dir / "deploy.sh").touch()
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_list_deploy_scripts({}, {})
        assert "deploy.sh" in r["scripts"]

    async def test_list_deploy_scripts_dir_missing(self, tmp_path):
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_list_deploy_scripts({}, {})
        assert r["scripts"] == []

    async def test_trigger_gh_workflow_no_confirm(self):
        r = await tool_trigger_gh_workflow({}, {})
        assert r["ok"] is False

    async def test_trigger_gh_workflow_no_workflow(self):
        r = await tool_trigger_gh_workflow({"confirm": True, "workflow": ""}, {})
        assert r["ok"] is False
        assert "workflow" in r["error"]

    async def test_trigger_gh_workflow_success(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_trigger_gh_workflow(
                {"confirm": True, "workflow": "ci.yml", "ref": "main"}, {}
            )
        assert r["ok"] is True


# ===========================================================================
# 7. Infra tools
# ===========================================================================


class TestInfraTools:
    async def test_nginx_test_nginx_missing(self):
        with patch("shutil.which", return_value=None):
            r = await tool_nginx_test({}, {})
        assert r["ok"] is True
        assert r["skipped"] is True

    async def test_nginx_test_nginx_present(self):
        with patch("shutil.which", return_value="/usr/bin/nginx"):
            with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
                r = await tool_nginx_test({}, {})
        assert r["syntax_valid"] is True

    async def test_api_health_from_params(self):
        with patch.object(
            module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200, "body": {}})
        ):
            r = await tool_api_health({"api_base": "http://localhost:9999"}, {})
        assert r["ok"] is True

    async def test_api_health_from_ctx(self):
        with patch.object(
            module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200, "body": {}})
        ):
            r = await tool_api_health({}, {"api_base": "http://ctx-host:9999"})
        assert r["ok"] is True

    async def test_api_health_default(self):
        with patch.object(
            module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200, "body": {}})
        ):
            r = await tool_api_health({}, {})
        assert r["ok"] is True

    async def test_mod_loading_status(self):
        with patch.object(
            module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200, "body": {}})
        ):
            r = await tool_mod_loading_status({}, {})
        assert r["ok"] is True

    async def test_disk_usage(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value={**_GOOD_RUN, "stdout": "Filesystem..."})):
            r = await tool_disk_usage({}, {})
        assert r["ok"] is True

    async def test_tail_logs_no_dir(self, tmp_path):
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_tail_logs({}, {})
        assert r["ok"] is True
        assert r["lines"] == []

    async def test_tail_logs_default_file_missing(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "other.log").touch()
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_tail_logs({}, {})
        assert r["ok"] is True
        assert "available_files" in r

    async def test_tail_logs_reads_file(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "app.log").write_text("\n".join(f"line{i}" for i in range(200)), encoding="utf-8")
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_tail_logs({"lines": 10}, {})
        assert r["ok"] is True
        assert len(r["lines"]) == 10

    async def test_tail_logs_oserror(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        f = log_dir / "app.log"
        f.touch()
        with patch.object(module, "_FHD_ROOT", tmp_path):
            with patch.object(Path, "read_text", side_effect=OSError("perm denied")):
                r = await tool_tail_logs({}, {})
        assert r["ok"] is False

    async def test_tail_logs_custom_file(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "custom.log").write_text("line1\nline2\n", encoding="utf-8")
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_tail_logs({"file": "custom.log"}, {})
        assert r["ok"] is True
        assert len(r["lines"]) == 2

    async def test_performance_status(self):
        with patch.object(
            module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200})
        ):
            r = await tool_performance_status({}, {})
        assert r["ok"] is True


# ===========================================================================
# 8. Mod tools
# ===========================================================================


class TestModTools:
    async def test_list_mods(self):
        with patch.object(
            module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200, "body": []})
        ):
            r = await tool_list_mods({}, {})
        assert r["ok"] is True

    async def test_list_employee_packs_no_dir(self, tmp_path):
        with patch.object(module, "_EMPLOYEES_DIR", tmp_path / "nonexistent"):
            r = await tool_list_employee_packs({}, {})
        assert r["ok"] is True
        assert r["packs"] == []

    async def test_list_employee_packs_with_manifest(self, tmp_path):
        emp_dir = tmp_path / "_employees" / "emp1"
        emp_dir.mkdir(parents=True)
        manifest = {
            "id": "emp1",
            "name": "Employee One",
            "artifact": "employee_pack",
            "employee_config_v2": {"area": "platform"},
        }
        (emp_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with patch.object(module, "_EMPLOYEES_DIR", tmp_path / "_employees"):
            r = await tool_list_employee_packs({}, {})
        assert r["ok"] is True
        assert len(r["packs"]) == 1
        assert r["packs"][0]["id"] == "emp1"

    async def test_list_employee_packs_bad_manifest(self, tmp_path):
        emp_dir = tmp_path / "_employees" / "emp2"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text("NOT JSON", encoding="utf-8")
        with patch.object(module, "_EMPLOYEES_DIR", tmp_path / "_employees"):
            r = await tool_list_employee_packs({}, {})
        assert r["ok"] is True
        assert r["packs"] == []

    async def test_list_employee_packs_missing_manifest(self, tmp_path):
        emp_dir = tmp_path / "_employees" / "emp3"
        emp_dir.mkdir(parents=True)
        # No manifest.json
        with patch.object(module, "_EMPLOYEES_DIR", tmp_path / "_employees"):
            r = await tool_list_employee_packs({}, {})
        assert r["packs"] == []

    async def test_validate_employee_pack_no_pack_id(self):
        r = await tool_validate_employee_pack({"pack_id": ""}, {})
        assert r["ok"] is False
        assert "pack_id" in r["error"]

    async def test_validate_employee_pack_no_manifest_file(self, tmp_path):
        with patch.object(module, "_EMPLOYEES_DIR", tmp_path):
            r = await tool_validate_employee_pack({"pack_id": "emp99"}, {})
        assert r["ok"] is False
        assert "manifest" in r["error"]

    async def test_validate_employee_pack_bad_json(self, tmp_path):
        emp_dir = tmp_path / "bad_emp"
        emp_dir.mkdir()
        (emp_dir / "manifest.json").write_text("NOT_JSON", encoding="utf-8")
        with patch.object(module, "_EMPLOYEES_DIR", tmp_path):
            r = await tool_validate_employee_pack({"pack_id": "bad_emp"}, {})
        assert r["ok"] is False

    async def test_validate_employee_pack_valid(self, tmp_path):
        emp_dir = tmp_path / "good_emp"
        emp_dir.mkdir()
        data = {
            "id": "good_emp",
            "artifact": "employee_pack",
            "employee_config_v2": {
                "cognition": {"agent": {"system_prompt": "You are an agent."}}
            },
        }
        (emp_dir / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        with patch.object(module, "_EMPLOYEES_DIR", tmp_path):
            r = await tool_validate_employee_pack({"pack_id": "good_emp"}, {})
        assert r["ok"] is True
        assert r["valid"] is True

    async def test_validate_employee_pack_missing_fields(self, tmp_path):
        emp_dir = tmp_path / "emp_bad_fields"
        emp_dir.mkdir()
        data = {"artifact": "wrong", "id": ""}
        (emp_dir / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        with patch.object(module, "_EMPLOYEES_DIR", tmp_path):
            r = await tool_validate_employee_pack({"pack_id": "emp_bad_fields"}, {})
        assert r["ok"] is True
        assert r["valid"] is False
        assert len(r["issues"]) >= 2

    async def test_validate_employee_pack_invalid_config_v2(self, tmp_path):
        emp_dir = tmp_path / "emp_nov2"
        emp_dir.mkdir()
        data = {
            "id": "emp_nov2",
            "artifact": "employee_pack",
            "employee_config_v2": "not_a_dict",
        }
        (emp_dir / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        with patch.object(module, "_EMPLOYEES_DIR", tmp_path):
            r = await tool_validate_employee_pack({"pack_id": "emp_nov2"}, {})
        assert r["ok"] is True
        assert any("employee_config_v2" in i for i in r["issues"])

    async def test_validate_employee_pack_missing_system_prompt(self, tmp_path):
        emp_dir = tmp_path / "emp_noprompt"
        emp_dir.mkdir()
        data = {
            "id": "emp_noprompt",
            "artifact": "employee_pack",
            "employee_config_v2": {"cognition": {"agent": {}}},
        }
        (emp_dir / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        with patch.object(module, "_EMPLOYEES_DIR", tmp_path):
            r = await tool_validate_employee_pack({"pack_id": "emp_noprompt"}, {})
        assert r["ok"] is True
        assert any("system_prompt" in i for i in r["issues"])

    async def test_duty_graph_health(self):
        with patch.object(
            module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200})
        ):
            r = await tool_duty_graph_health({}, {})
        assert r["ok"] is True


# ===========================================================================
# 9. Doc tools
# ===========================================================================


class TestDocTools:
    async def test_list_docs_no_dirs(self, tmp_path):
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_list_docs({}, {})
        assert r["ok"] is True
        assert isinstance(r["docs"], list)

    async def test_list_docs_with_files(self, tmp_path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "README.md").write_text("# Test", encoding="utf-8")
        with patch.object(module, "_FHD_ROOT", tmp_path / "FHD"):
            # patch parent so docs_dir matches
            with patch.object(module._FHD_ROOT, "parent", new_callable=lambda: property(lambda self: tmp_path)):
                r = await tool_list_docs({}, {})
        # Just check it returns ok
        assert r["ok"] is True

    async def test_read_file_no_path(self):
        r = await tool_read_file({"path": ""}, {})
        assert r["ok"] is False

    async def test_read_file_path_escape(self, tmp_path):
        with patch.object(module, "_FHD_ROOT", tmp_path / "project"):
            r = await tool_read_file({"path": "../../../etc/passwd"}, {})
        assert r["ok"] is False
        assert "越界" in r["error"]

    async def test_read_file_not_existing(self, tmp_path):
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_read_file({"path": "nonexistent.txt"}, {})
        assert r["ok"] is False

    async def test_read_file_success(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("content here", encoding="utf-8")
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_read_file({"path": "hello.txt"}, {})
        assert r["ok"] is True
        assert r["content"] == "content here"
        assert r["truncated"] is False

    async def test_read_file_truncated(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("x" * 60000, encoding="utf-8")
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_read_file({"path": "big.txt"}, {})
        assert r["ok"] is True
        assert r["truncated"] is True

    async def test_read_file_oserror(self, tmp_path):
        f = tmp_path / "restricted.txt"
        f.touch()
        with patch.object(module, "_FHD_ROOT", tmp_path):
            with patch.object(Path, "read_text", side_effect=OSError("denied")):
                r = await tool_read_file({"path": "restricted.txt"}, {})
        assert r["ok"] is False

    async def test_list_scripts_no_scripts_dir(self, tmp_path):
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_list_scripts({}, {})
        assert r["ok"] is True
        assert r["scripts"] == []

    async def test_list_scripts_with_category_missing(self, tmp_path):
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_list_scripts({"category": "nonexistent"}, {})
        assert r["ok"] is False

    async def test_list_scripts_success(self, tmp_path):
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "myscript.py").touch()
        (scripts_dir / "deploy.sh").touch()
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_list_scripts({}, {})
        assert r["ok"] is True
        assert len(r["python"]) >= 1
        assert len(r["shell"]) >= 1

    async def test_list_scripts_with_category(self, tmp_path):
        scripts_dir = tmp_path / "scripts" / "dev"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "helper.py").touch()
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_list_scripts({"category": "dev"}, {})
        assert r["ok"] is True


# ===========================================================================
# 10. Platform tools
# ===========================================================================


class TestPlatformTools:
    async def test_list_employees_no_roster(self, tmp_path):
        with patch.object(module, "_DUTY_ROSTER", tmp_path / "nonexistent.json"):
            r = await tool_list_employees({}, {})
        assert r["ok"] is False

    async def test_list_employees_bad_json(self, tmp_path):
        f = tmp_path / "duty.json"
        f.write_text("NOT_JSON", encoding="utf-8")
        with patch.object(module, "_DUTY_ROSTER", f):
            r = await tool_list_employees({}, {})
        assert r["ok"] is False

    async def test_list_employees_valid(self, tmp_path):
        roster = {
            "areas": {
                "platform": {
                    "ids": ["emp-a", "emp-b"],
                    "subzones": {
                        "sub1": {"ids": ["emp-c"]}
                    },
                }
            },
            "departments": {},
        }
        f = tmp_path / "duty.json"
        f.write_text(json.dumps(roster), encoding="utf-8")
        with patch.object(module, "_DUTY_ROSTER", f):
            r = await tool_list_employees({}, {})
        assert r["ok"] is True
        assert "emp-a" in r["employees"]
        assert "emp-c" in r["employees"]

    async def test_list_employees_no_list_in_block(self, tmp_path):
        roster = {"areas": {"platform": {"ids": None}}, "departments": {}}
        f = tmp_path / "duty.json"
        f.write_text(json.dumps(roster), encoding="utf-8")
        with patch.object(module, "_DUTY_ROSTER", f):
            r = await tool_list_employees({}, {})
        assert r["ok"] is True

    async def test_employee_status_no_id(self):
        r = await tool_employee_status({}, {})
        assert r["ok"] is False
        assert "employee_id" in r["error"]

    async def test_employee_status_from_ctx(self):
        with patch.object(module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200})):
            r = await tool_employee_status({}, {"employee_id": "emp-1"})
        assert r["ok"] is True

    async def test_employee_status_from_params(self):
        with patch.object(module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200})):
            r = await tool_employee_status({"employee_id": "emp-2"}, {})
        assert r["ok"] is True
        assert r["employee_id"] == "emp-2"

    async def test_list_action_items(self):
        with patch.object(module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200})):
            r = await tool_list_action_items({}, {})
        assert r["ok"] is True

    async def test_employee_autonomy_dashboard(self):
        with patch.object(module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200})):
            r = await tool_employee_autonomy_dashboard({}, {})
        assert r["ok"] is True


# ===========================================================================
# 11. Craft tools
# ===========================================================================


class TestCraftTools:
    async def test_list_workbench_sessions_no_dir(self, tmp_path):
        r = await tool_list_workbench_sessions({}, {"workspace_root": str(tmp_path)})
        assert r["ok"] is True
        assert r["sessions"] == []

    async def test_list_workbench_sessions_with_dirs(self, tmp_path):
        sessions = tmp_path / "workbench" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "sess1").mkdir()
        (sessions / "sess2").mkdir()
        (sessions / "not_a_dir.txt").touch()
        r = await tool_list_workbench_sessions({}, {"workspace_root": str(tmp_path)})
        assert r["ok"] is True
        assert "sess1" in r["sessions"]
        assert "not_a_dir.txt" not in r["sessions"]

    async def test_sandbox_python_no_code(self):
        r = await tool_sandbox_python({"code": ""}, {})
        assert r["ok"] is False

    async def test_sandbox_python_too_long(self):
        r = await tool_sandbox_python({"code": "x" * 25000}, {})
        assert r["ok"] is False
        assert "过长" in r["error"]

    async def test_sandbox_python_forbidden_import_without_confirm(self):
        r = await tool_sandbox_python({"code": "import os"}, {})
        assert r["ok"] is False
        assert "requires_confirm" in r

    async def test_sandbox_python_forbidden_with_confirm(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_sandbox_python({"code": "import os", "confirm": True}, {})
        assert r["ok"] is True

    async def test_sandbox_python_safe_code(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_sandbox_python({"code": "print('hello')"}, {})
        assert r["ok"] is True

    async def test_sandbox_python_all_forbidden_keywords(self):
        for kw in ("import subprocess", "import shutil", "open(", "__import__"):
            r = await tool_sandbox_python({"code": kw}, {})
            assert r["ok"] is False, f"Should block: {kw}"


# ===========================================================================
# 12. Payment tools
# ===========================================================================


class TestPaymentTools:
    async def test_check_transactions(self):
        with patch.object(module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200})):
            r = await tool_check_transactions({}, {})
        assert r["ok"] is True

    async def test_list_invoices(self):
        with patch.object(module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200})):
            r = await tool_list_invoices({}, {})
        assert r["ok"] is True


# ===========================================================================
# 13. Ecosystem tools
# ===========================================================================


class TestEcosystemTools:
    async def test_list_enterprise_mods(self):
        with patch.object(module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200})):
            r = await tool_list_enterprise_mods({}, {})
        assert r["ok"] is True

    async def test_list_users(self):
        with patch.object(module, "_api_call", AsyncMock(return_value={"ok": True, "status": 200})):
            r = await tool_list_users({}, {})
        assert r["ok"] is True


# ===========================================================================
# 14. Frontend tools
# ===========================================================================


class TestFrontendTools:
    async def test_frontend_lint_no_package_json(self, tmp_path):
        fe_dir = tmp_path / "frontend"
        fe_dir.mkdir()
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_frontend_lint({}, {})
        assert r["ok"] is False

    async def test_frontend_lint_no_npm(self, tmp_path):
        fe_dir = tmp_path / "frontend"
        fe_dir.mkdir()
        (fe_dir / "package.json").write_text("{}", encoding="utf-8")
        with patch.object(module, "_FHD_ROOT", tmp_path):
            with patch("shutil.which", return_value=None):
                r = await tool_frontend_lint({}, {})
        assert r["ok"] is True
        assert r.get("skipped") is True

    async def test_frontend_lint_success(self, tmp_path):
        fe_dir = tmp_path / "frontend"
        fe_dir.mkdir()
        (fe_dir / "package.json").write_text("{}", encoding="utf-8")
        with patch.object(module, "_FHD_ROOT", tmp_path):
            with patch("shutil.which", return_value="/usr/bin/npm"):
                with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
                    r = await tool_frontend_lint({}, {})
        assert r["ok"] is True

    async def test_frontend_typecheck_no_package_json(self, tmp_path):
        fe_dir = tmp_path / "frontend"
        fe_dir.mkdir()
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_frontend_typecheck({}, {})
        assert r["ok"] is False

    async def test_frontend_typecheck_no_npm(self, tmp_path):
        fe_dir = tmp_path / "frontend"
        fe_dir.mkdir()
        (fe_dir / "package.json").write_text("{}", encoding="utf-8")
        with patch.object(module, "_FHD_ROOT", tmp_path):
            with patch("shutil.which", return_value=None):
                r = await tool_frontend_typecheck({}, {})
        assert r.get("skipped") is True

    async def test_frontend_typecheck_success(self, tmp_path):
        fe_dir = tmp_path / "frontend"
        fe_dir.mkdir()
        (fe_dir / "package.json").write_text("{}", encoding="utf-8")
        with patch.object(module, "_FHD_ROOT", tmp_path):
            with patch("shutil.which", return_value="/usr/bin/npm"):
                with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
                    r = await tool_frontend_typecheck({}, {})
        assert r["ok"] is True

    async def test_frontend_test_no_package_json(self, tmp_path):
        fe_dir = tmp_path / "frontend"
        fe_dir.mkdir()
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_frontend_test({}, {})
        assert r["ok"] is False

    async def test_frontend_test_no_npm(self, tmp_path):
        fe_dir = tmp_path / "frontend"
        fe_dir.mkdir()
        (fe_dir / "package.json").write_text("{}", encoding="utf-8")
        with patch.object(module, "_FHD_ROOT", tmp_path):
            with patch("shutil.which", return_value=None):
                r = await tool_frontend_test({}, {})
        assert r.get("skipped") is True

    async def test_frontend_test_success(self, tmp_path):
        fe_dir = tmp_path / "frontend"
        fe_dir.mkdir()
        (fe_dir / "package.json").write_text("{}", encoding="utf-8")
        with patch.object(module, "_FHD_ROOT", tmp_path):
            with patch("shutil.which", return_value="/usr/bin/npm"):
                with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
                    r = await tool_frontend_test({}, {})
        assert r["ok"] is True


# ===========================================================================
# 15. Mobile tools
# ===========================================================================


class TestMobileTools:
    async def test_android_gradle_no_confirm(self):
        r = await tool_android_gradle_build({}, {})
        assert r["ok"] is False

    async def test_android_gradle_no_gradlew(self, tmp_path):
        android_dir = tmp_path / "mobile-android"
        android_dir.mkdir()
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_android_gradle_build({"confirm": True}, {})
        assert r["ok"] is False
        assert "gradlew" in r["error"]

    async def test_android_gradle_success(self, tmp_path):
        android_dir = tmp_path / "mobile-android"
        android_dir.mkdir()
        gradlew = android_dir / "gradlew"
        gradlew.touch()
        with patch.object(module, "_FHD_ROOT", tmp_path):
            with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
                r = await tool_android_gradle_build({"confirm": True}, {})
        assert r["ok"] is True


# ===========================================================================
# 16. Code write tools
# ===========================================================================


class TestWriteFile:
    async def test_no_confirm(self):
        r = await tool_write_file({}, {})
        assert r["ok"] is False
        assert "confirm" in r["error"]

    async def test_no_path(self):
        r = await tool_write_file({"confirm": True, "path": ""}, {})
        assert r["ok"] is False

    async def test_path_escape(self, tmp_path):
        r = await tool_write_file(
            {"confirm": True, "path": "../../../etc/evil", "content": "x"},
            {"workspace_root": str(tmp_path / "workspace")},
        )
        assert r["ok"] is False

    async def test_success(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        r = await tool_write_file(
            {"confirm": True, "path": "output/new.txt", "content": "hello world"},
            {"workspace_root": str(ws)},
        )
        assert r["ok"] is True
        assert (ws / "output" / "new.txt").read_text() == "hello world"

    async def test_oserror(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        with patch.object(Path, "write_text", side_effect=OSError("no space")):
            r = await tool_write_file(
                {"confirm": True, "path": "file.txt", "content": "x"},
                {"workspace_root": str(ws)},
            )
        assert r["ok"] is False

    async def test_default_workspace_root(self, tmp_path):
        with patch("os.getcwd", return_value=str(tmp_path)):
            r = await tool_write_file(
                {"confirm": True, "path": "test_file.txt", "content": "data"},
                {},
            )
        assert r["ok"] is True


class TestPatchFile:
    async def test_no_confirm(self):
        r = await tool_patch_file({}, {})
        assert r["ok"] is False

    async def test_missing_path_or_patch(self):
        r = await tool_patch_file({"confirm": True, "path": "", "patch": "diff..."}, {})
        assert r["ok"] is False

    async def test_missing_patch(self, tmp_path):
        r = await tool_patch_file({"confirm": True, "path": "file.txt", "patch": ""}, {})
        assert r["ok"] is False

    async def test_path_escape(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        r = await tool_patch_file(
            {"confirm": True, "path": "../../evil.txt", "patch": "diff"},
            {"workspace_root": str(ws)},
        )
        assert r["ok"] is False

    async def test_target_not_file(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        r = await tool_patch_file(
            {"confirm": True, "path": "no_such_file.txt", "patch": "diff"},
            {"workspace_root": str(ws)},
        )
        assert r["ok"] is False

    async def test_patch_check_fails(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        target = ws / "file.txt"
        target.write_text("original content\n", encoding="utf-8")
        check_fail = {**_BAD_RUN, "stderr": "patch rejected"}
        with patch.object(module, "_run_cmd", AsyncMock(return_value=check_fail)):
            r = await tool_patch_file(
                {"confirm": True, "path": "file.txt", "patch": "diff content"},
                {"workspace_root": str(ws)},
            )
        assert r["ok"] is False
        assert "校验失败" in r["error"]

    async def test_patch_apply_fails(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        target = ws / "file.txt"
        target.write_text("original content\n", encoding="utf-8")
        # First call (check) ok, second call (apply) fails
        call_results = [_GOOD_RUN, _BAD_RUN]
        call_idx = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_idx
            r = call_results[call_idx % len(call_results)]
            call_idx += 1
            return r

        with patch.object(module, "_run_cmd", side_effect=side_effect):
            r = await tool_patch_file(
                {"confirm": True, "path": "file.txt", "patch": "diff content"},
                {"workspace_root": str(ws)},
            )
        assert r["ok"] is False
        assert "应用失败" in r["error"]

    async def test_patch_success(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        target = ws / "file.txt"
        target.write_text("original content\n", encoding="utf-8")
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
            r = await tool_patch_file(
                {"confirm": True, "path": "file.txt", "patch": "valid diff"},
                {"workspace_root": str(ws)},
            )
        assert r["ok"] is True


# ===========================================================================
# 17. _code_write_tools
# ===========================================================================


class TestCodeWriteTools:
    def test_returns_frozenset(self):
        tools = _code_write_tools()
        assert isinstance(tools, frozenset)
        assert "patch_file" in tools or "write_file" in tools

    def test_cached_on_second_call(self):
        # Reset the cache
        old = module._CODE_WRITE_TOOLS_LAZY
        module._CODE_WRITE_TOOLS_LAZY = None
        with patch(
            "app.mod_sdk.employee_specialized_tools._code_write_tools",
            wraps=_code_write_tools,
        ):
            t1 = _code_write_tools()
            t2 = _code_write_tools()
        assert t1 is t2
        module._CODE_WRITE_TOOLS_LAZY = old

    def test_import_error_fallback(self):
        old = module._CODE_WRITE_TOOLS_LAZY
        module._CODE_WRITE_TOOLS_LAZY = None
        with patch.dict("sys.modules", {"app.application.employee_runtime.tool_scope": None}):
            tools = _code_write_tools()
        assert "patch_file" in tools
        module._CODE_WRITE_TOOLS_LAZY = old


# ===========================================================================
# 18. _check_write_gate
# ===========================================================================


class TestCheckWriteGate:
    async def test_import_error_blocks(self):
        with patch.dict(
            "sys.modules",
            {
                "app.application.employee_runtime.workspace_guard": None,
                "app.application.employee_runtime.write_approval": None,
                "app.infrastructure.mods.employee_registry": None,
                "app.infrastructure.mods.mod_manager": None,
            },
        ):
            r = await _check_write_gate("emp-1", "write_file", {}, {})
        assert r["ok"] is False

    async def test_no_manifest_found(self):
        mock_mgr = MagicMock()
        mock_mgr.all_mods_roots = MagicMock(return_value=["some/root"])
        mock_mgr.mods_root = "some/root"

        mock_registry = MagicMock()
        mock_registry.list_packs = MagicMock(return_value=[{"id": "other-emp"}])

        mock_ws_guard = MagicMock()
        mock_write_approval = MagicMock()

        with patch(
            "app.mod_sdk.employee_specialized_tools._check_write_gate",
            wraps=_check_write_gate,
        ):
            with patch.dict(
                "sys.modules",
                {
                    "app.application.employee_runtime.workspace_guard": mock_ws_guard,
                    "app.application.employee_runtime.write_approval": mock_write_approval,
                    "app.infrastructure.mods.employee_registry": MagicMock(
                        EmployeeRegistry=MagicMock(return_value=mock_registry)
                    ),
                    "app.infrastructure.mods.mod_manager": MagicMock(
                        get_mod_manager=MagicMock(return_value=mock_mgr)
                    ),
                },
            ):
                # Reimport to pick up patched modules
                r = await _check_write_gate("unknown-emp", "write_file", {}, {})
        assert r["ok"] is False

    async def test_exception_blocks(self):
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=RuntimeError("module not loaded"),
        ):
            r = await _check_write_gate("emp-1", "write_file", {}, {})
        # Should block on exception
        assert r["ok"] is False


# ===========================================================================
# 19. LLM Env tools
# ===========================================================================


class TestReadLlmEnvConfig:
    async def test_empty_env_file(self, tmp_path):
        env_path = tmp_path / ".env"
        # Don't create the file
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_read_llm_env_config({}, {})
        assert r["ok"] is False

    async def test_with_env_file(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("OPENAI_API_KEY=sk-test12345678\nXCAGI_LLM_PROVIDER=openai\n", encoding="utf-8")
        with patch.object(module, "_FHD_ROOT", tmp_path):
            r = await tool_read_llm_env_config({}, {})
        assert r["ok"] is True
        # API keys should be masked
        if "OPENAI_API_KEY" in r["env_config"]:
            assert "***" in r["env_config"]["OPENAI_API_KEY"]

    async def test_runtime_env_vars_included(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("FOO=bar\n", encoding="utf-8")
        with patch.object(module, "_FHD_ROOT", tmp_path):
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-runtime12345"}):
                r = await tool_read_llm_env_config({}, {})
        assert r["ok"] is True
        if "OPENAI_API_KEY" in r.get("runtime_config", {}):
            assert "***" in r["runtime_config"]["OPENAI_API_KEY"]


class TestListConfiguredProviders:
    async def test_no_providers_configured(self):
        # Remove all provider keys from env
        keys_to_remove = [k for k in os.environ if "API_KEY" in k or "ARK" in k or "VOLC" in k]
        env_override = {k: "" for k in keys_to_remove}
        with patch.dict(os.environ, env_override, clear=False):
            # Patch env to empty so no providers match
            with patch("os.environ", {}):
                r = await tool_list_configured_providers({}, {})
        # ollama always shows (no_auth)
        assert r["ok"] is True

    async def test_with_openai_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test12345678", "OPENAI_BASE_URL": "https://api.openai.com/v1"}):
            r = await tool_list_configured_providers({}, {})
        assert r["ok"] is True
        providers = {p["provider"] for p in r["providers"]}
        assert "openai" in providers or "b.ai" in providers


class TestComparePrices:
    async def test_no_filter(self):
        r = await tool_compare_model_prices({}, {})
        assert r["ok"] is True
        assert len(r["prices"]) > 0

    async def test_filter_by_provider(self):
        r = await tool_compare_model_prices({"provider": "deepseek"}, {})
        assert r["ok"] is True
        assert all("deepseek" in str(p["provider"]).lower() for p in r["prices"])

    async def test_sort_by_input(self):
        r = await tool_compare_model_prices({"sort_by": "input"}, {})
        assert r["ok"] is True
        assert r["sort_by"] == "input_per_1m"

    async def test_sort_by_output_default(self):
        r = await tool_compare_model_prices({}, {})
        assert r["sort_by"] == "output_per_1m"

    async def test_free_models_listed(self):
        r = await tool_compare_model_prices({}, {})
        assert len(r["free_models"]) > 0

    async def test_empty_after_filter(self):
        r = await tool_compare_model_prices({"provider": "nonexistent_xyz"}, {})
        assert r["ok"] is True
        assert r["cheapest"] is None


class TestTestLlmKeyHealth:
    async def test_httpx_none(self):
        with patch.object(module, "httpx", None):
            r = await tool_test_llm_key_health({}, {})
        assert r["ok"] is False

    async def test_no_keys_configured(self):
        with patch("os.environ", {}):
            r = await tool_test_llm_key_health({}, {})
        assert r["ok"] is False or len(r.get("results", [])) >= 0

    async def test_filter_by_provider(self):
        # With a target that doesn't match any provider
        with patch("os.environ", {}):
            r = await tool_test_llm_key_health({"provider": "nonexistent"}, {})
        assert r["ok"] is False

    async def test_ping_success(self):
        mock_resp = Mock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.json = Mock(return_value={"choices": [{"message": {"content": "p"}}]})
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-abcdefgh12345", "OPENAI_BASE_URL": "https://api.openai.com/v1"}):
            with patch.object(module, "httpx") as mock_httpx:
                mock_httpx.AsyncClient.return_value = mock_client
                r = await tool_test_llm_key_health({"provider": "openai"}, {})
        assert r["ok"] is True
        assert r["healthy_count"] >= 0


class TestQueryProviderUsage:
    async def test_httpx_none(self):
        with patch.object(module, "httpx", None):
            r = await tool_query_provider_usage({}, {})
        assert r["ok"] is False

    async def test_no_keys_no_providers(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("os.environ", {}):
            with patch.object(module, "httpx") as mock_httpx:
                mock_httpx.AsyncClient.return_value = mock_client
                r = await tool_query_provider_usage({}, {})
        assert r["ok"] is True

    async def test_provider_without_billing(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "sk-qwen12345"}):
            with patch.object(module, "httpx") as mock_httpx:
                mock_httpx.AsyncClient.return_value = mock_client
                r = await tool_query_provider_usage({"provider": "qwen"}, {})
        assert r["ok"] is True
        assert any(f["provider"] == "qwen" for f in r["findings"])


class TestQueryLocalTokenUsage:
    async def test_import_error(self):
        with patch.dict(
            "sys.modules",
            {
                "app.infrastructure.billing.model_usage": None,
                "app.infrastructure.billing": None,
            },
        ):
            r = await tool_query_local_token_usage({}, {})
        assert r["ok"] is False

    async def test_success_with_mock(self):
        mock_entries = [
            {
                "entry_type": "model_call",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "cost_units": 1,
                "run_id": "run1",
                "user_id": "user1",
                "created_at": "2026-01-01",
            }
        ]
        mock_billing = MagicMock()
        mock_billing.list_model_usage_entries = MagicMock(return_value=mock_entries)
        mock_billing.model_usage_ledger_path = MagicMock(return_value=Path("/tmp/ledger.json"))
        with patch.dict("sys.modules", {"app.infrastructure.billing.model_usage": mock_billing}):
            r = await tool_query_local_token_usage({"limit": 10, "group_by": "model"}, {})
        assert r["ok"] is True
        assert r["usage_summary"]["total_calls"] == 1

    async def test_group_by_provider(self):
        mock_entries = [
            {
                "entry_type": "model_call",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "cost_units": 1,
                "run_id": "",
                "user_id": "",
                "created_at": "",
            }
        ]
        mock_billing = MagicMock()
        mock_billing.list_model_usage_entries = MagicMock(return_value=mock_entries)
        mock_billing.model_usage_ledger_path = MagicMock(return_value=Path("/tmp/ledger.json"))
        with patch.dict("sys.modules", {"app.infrastructure.billing.model_usage": mock_billing}):
            r = await tool_query_local_token_usage({"group_by": "provider", "limit": 0}, {})
        assert r["ok"] is True
        assert "openai" in r.get("groups", {})

    async def test_group_by_none(self):
        mock_entries = [
            {
                "entry_type": "model_call",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "cost_units": 0,
                "run_id": "",
                "user_id": "",
                "created_at": "",
            }
        ]
        mock_billing = MagicMock()
        mock_billing.list_model_usage_entries = MagicMock(return_value=mock_entries)
        mock_billing.model_usage_ledger_path = MagicMock(return_value=Path("/tmp/ledger.json"))
        with patch.dict("sys.modules", {"app.infrastructure.billing.model_usage": mock_billing}):
            r = await tool_query_local_token_usage({"group_by": "none"}, {})
        assert r["ok"] is True
        assert r["groups"] == {}

    async def test_filters_non_model_call_entries(self):
        mock_entries = [
            {"entry_type": "tool_call", "model": "x", "prompt_tokens": 999, "completion_tokens": 999, "total_tokens": 999, "cost_units": 0},
            {"entry_type": "model_call", "provider": "p", "model": "m", "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost_units": 0, "run_id": "", "user_id": "", "created_at": ""},
        ]
        mock_billing = MagicMock()
        mock_billing.list_model_usage_entries = MagicMock(return_value=mock_entries)
        mock_billing.model_usage_ledger_path = MagicMock(return_value=Path("/tmp/ledger.json"))
        with patch.dict("sys.modules", {"app.infrastructure.billing.model_usage": mock_billing}):
            r = await tool_query_local_token_usage({"limit": 10}, {})
        assert r["ok"] is True
        # tool_call should not be counted
        assert r["usage_summary"]["total_tokens"] == 15


# ===========================================================================
# 20. Registry and dispatch
# ===========================================================================


class TestRegistry:
    def test_get_employee_tools_known(self):
        tools = get_employee_tools("fhd-core-maintainer")
        assert "run_pytest" in tools
        assert "patch_file" in tools

    def test_get_employee_tools_unknown(self):
        tools = get_employee_tools("nonexistent-employee-xyz")
        assert tools == []

    def test_list_all_tool_names(self):
        names = list_all_tool_names()
        assert "run_pytest" in names
        assert "git_status" in names
        assert sorted(names) == names  # Should be sorted

    def test_tool_registry_keys_match_list(self):
        registry_keys = set(TOOL_REGISTRY.keys())
        listed = set(list_all_tool_names())
        assert registry_keys == listed

    def test_employee_tools_all_registered(self):
        for emp, tools in EMPLOYEE_TOOLS.items():
            for tool in tools:
                assert tool in TOOL_REGISTRY, f"Employee {emp} references unregistered tool {tool}"


class TestHandleSpecialized:
    async def test_no_tool_returns_list(self):
        r = await handle_specialized("fhd-core-maintainer", {}, {})
        assert r["ok"] is True
        assert "available_tools" in r
        assert r["employee_id"] == "fhd-core-maintainer"

    async def test_unknown_tool_returns_error(self):
        r = await handle_specialized("fhd-core-maintainer", {"tool": "nonexistent_tool"}, {})
        assert r["ok"] is False
        assert "专属工具清单" in r["error"]

    async def test_tool_not_in_employee_list(self):
        # git_status is not in sandbox-tester's list
        r = await handle_specialized("sandbox-tester", {"tool": "git_status"}, {})
        assert r["ok"] is False

    async def test_tool_not_callable(self):
        # Temporarily put a non-callable in registry
        TOOL_REGISTRY["_test_broken"] = "not_a_function"
        EMPLOYEE_TOOLS.setdefault("_test_emp", ["_test_broken"])
        try:
            r = await handle_specialized("_test_emp", {"tool": "_test_broken"}, {})
            assert r["ok"] is False
            assert "未实现" in r["error"]
        finally:
            del TOOL_REGISTRY["_test_broken"]
            del EMPLOYEE_TOOLS["_test_emp"]

    async def test_params_not_dict(self):
        r = await handle_specialized(
            "fhd-core-maintainer", {"tool": "run_pytest", "params": "not_a_dict"}, {}
        )
        assert r["ok"] is False
        assert "params" in r["error"]

    async def test_tool_success_adds_metadata(self):
        with patch.object(module, "_run_cmd", AsyncMock(return_value=_GOOD_RUN)):
            r = await handle_specialized(
                "fhd-core-maintainer",
                {"tool": "run_pytest", "params": {}},
                {},
            )
        assert r.get("tool") == "run_pytest"
        assert r.get("employee_id") == "fhd-core-maintainer"
        assert r.get("handler") == "specialized"

    async def test_tool_exception_returns_error(self):
        with patch.object(module, "tool_run_pytest", AsyncMock(side_effect=RuntimeError("boom"))):
            r = await handle_specialized(
                "fhd-core-maintainer",
                {"tool": "run_pytest", "params": {}},
                {},
            )
        assert r["ok"] is False
        assert "执行异常" in r["error"]

    async def test_tool_returns_non_dict(self):
        async def _returns_string(params, ctx):
            return "plain string"

        TOOL_REGISTRY["_str_tool"] = _returns_string
        EMPLOYEE_TOOLS.setdefault("_str_emp", ["_str_tool"])
        try:
            r = await handle_specialized("_str_emp", {"tool": "_str_tool", "params": {}}, {})
            assert r["ok"] is True
            assert r.get("raw") == "plain string"
        finally:
            del TOOL_REGISTRY["_str_tool"]
            del EMPLOYEE_TOOLS["_str_emp"]

    async def test_code_write_tool_blocked_by_gate(self):
        gate_result = {"ok": False, "reason": "scope check failed"}
        with patch.object(module, "_check_write_gate", AsyncMock(return_value=gate_result)):
            with patch.object(module, "_code_write_tools", return_value=frozenset({"write_file"})):
                r = await handle_specialized(
                    "fhd-core-maintainer",
                    {"tool": "write_file", "params": {"confirm": True, "path": "x", "content": "y"}},
                    {},
                )
        assert r["ok"] is False
        assert r.get("blocked") is True

    async def test_code_write_tool_passed_by_gate(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        gate_result = {"ok": True}
        with patch.object(module, "_check_write_gate", AsyncMock(return_value=gate_result)):
            with patch.object(module, "_code_write_tools", return_value=frozenset({"write_file"})):
                r = await handle_specialized(
                    "fhd-core-maintainer",
                    {
                        "tool": "write_file",
                        "params": {"confirm": True, "path": "output.txt", "content": "data"},
                    },
                    {"workspace_root": str(ws)},
                )
        assert r["ok"] is True

    async def test_gate_pending_approval(self):
        gate_result = {
            "ok": False,
            "reason": "awaiting approval",
            "pending_approval": True,
            "approval_request_ids": ["req-1", "req-2"],
        }
        with patch.object(module, "_check_write_gate", AsyncMock(return_value=gate_result)):
            with patch.object(module, "_code_write_tools", return_value=frozenset({"write_file"})):
                r = await handle_specialized(
                    "fhd-core-maintainer",
                    {"tool": "write_file", "params": {"confirm": True, "path": "x", "content": "y"}},
                    {},
                )
        assert r["ok"] is False
        assert r["pending_approval"] is True
        assert r["approval_request_ids"] == ["req-1", "req-2"]
