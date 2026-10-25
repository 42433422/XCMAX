"""Public employee tools assemble explicit execution, workspace, policy and usage collaborators."""

from __future__ import annotations

import asyncio as asyncio
import inspect as inspect
import json as json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from typing import cast as cast

from app.utils.operational_errors import RECOVERABLE_ERRORS as RECOVERABLE_ERRORS

from .employee_specialized_tools_employee_map import EMPLOYEE_TOOLS as EMPLOYEE_TOOLS
from .employee_specialized_tools_provider_catalog import _LLM_ENV_KEYS as _LLM_ENV_KEYS
from .employee_specialized_tools_provider_catalog import _MODEL_PRICES as _MODEL_PRICES
from .employee_specialized_tools_provider_catalog import _PROVIDER_PROFILES as _PROVIDER_PROFILES
from .employee_tools import (
    adapters,
    codex_usage,
    configuration,
    cursor_usage,
    dispatch,
    employees,
    providers,
    quality,
    release,
    status,
    trae_usage,
    usage,
    workspace,
)
from .employee_tools.configuration import _detect_provider_name as _detect_provider_name
from .employee_tools.configuration import _mask_secret as _mask_secret
from .employee_tools.configuration import _provider_base_url as _provider_base_url
from .employee_tools.configuration import _provider_has_key as _provider_has_key
from .employee_tools.configuration import _provider_model as _provider_model
from .employee_tools.configuration import _read_env_file as _read_env_file
from .employee_tools.policy import _check_write_gate as _check_write_gate
from .employee_tools.employee_tool_ports import (
    Configuration,
    CursorPorts,
    DispatchPorts,
    EmployeeFiles,
    ModelCatalog,
    Payload,
    ProviderPorts,
    QualityPorts,
    ReleasePorts,
    StatusPorts,
    Tool,
    TraePorts,
    WorkspacePorts,
)
from .employee_tools.processes import CommandRunner
from .employee_tools.results import _err as _err
from .employee_tools.results import _ok as _ok

if TYPE_CHECKING:
    import httpx
else:
    try:
        import httpx
    except ImportError:
        httpx = None
_FHD_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _FHD_ROOT / "scripts"
_VENV_PYTHON = str(_FHD_ROOT / ".venv" / "bin" / "python")
_PYTHON = _VENV_PYTHON if os.path.isfile(_VENV_PYTHON) else sys.executable
_EMPLOYEES_DIR = _FHD_ROOT / "mods" / "_employees"
_DUTY_ROSTER = _FHD_ROOT / "config" / "duty_roster.json"
_DEFAULT_API_BASE = os.environ.get("XCAGI_EMPLOYEE_API_BASE", "http://127.0.0.1:5102")
_DEFAULT_TIMEOUT = 120
_CODE_WRITE_TOOLS_LAZY: frozenset[str] | None = None
_LLM_SECRET_KEYS = frozenset(
    k for k in _LLM_ENV_KEYS if "API_KEY" in k or "PAT" in k or "SECRET" in k
)


async def _run_cmd(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> Payload:
    """执行命令并返回结构化结果。"""
    return await CommandRunner(asyncio.create_subprocess_exec, dict(os.environ)).run(
        args, cwd=cwd, timeout=timeout, env=env
    )


async def _run_python_script(script: str | Path, *extra_args: str, **kw: Any) -> Payload:
    """用项目 venv python 跑一个脚本。"""
    return await _run_cmd([_PYTHON, str(script), *extra_args], **kw)


async def _api_call(method: str, path: str, *, api_base: str | None = None, **kw: Any) -> Payload:
    if httpx is None:
        return {"ok": False, "error": "httpx 未安装"}
    from app.application.tool_execution_deadline import build_http_request

    base = (api_base or _DEFAULT_API_BASE).rstrip("/")
    url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
    return await build_http_request(httpx.AsyncClient)(method, url, **kw)


def _quality() -> QualityPorts:
    return QualityPorts(_FHD_ROOT, _SCRIPTS, _PYTHON, _run_cmd, _run_python_script)


def _release() -> ReleasePorts:
    return ReleasePorts(_FHD_ROOT, _run_cmd)


def _workspace() -> WorkspacePorts:
    return WorkspacePorts(_FHD_ROOT, _run_cmd)


def _status() -> StatusPorts:
    return StatusPorts(_DEFAULT_API_BASE, _api_call)


def _employees() -> EmployeeFiles:
    return EmployeeFiles(_EMPLOYEES_DIR, _DUTY_ROSTER)


def _configuration() -> Configuration:
    return Configuration(_FHD_ROOT, _PROVIDER_PROFILES, _LLM_ENV_KEYS, _LLM_SECRET_KEYS)


def _providers() -> ProviderPorts:
    return ProviderPorts(_PROVIDER_PROFILES, httpx.AsyncClient if httpx is not None else None)


def _usage() -> ModelCatalog:
    return ModelCatalog(_MODEL_PRICES)


def _cursor_usage() -> CursorPorts:
    return CursorPorts(Path.home(), shutil.which, subprocess.run, adapters.http_get)


def _trae_usage() -> TraePorts:
    return TraePorts(Path.home(), adapters.http_get)


def _code_write_tools() -> frozenset[str]:
    global _CODE_WRITE_TOOLS_LAZY
    if _CODE_WRITE_TOOLS_LAZY is None:
        try:
            from app.application.employee_runtime.tool_scope import CODE_WRITE_TOOLS

            _CODE_WRITE_TOOLS_LAZY = CODE_WRITE_TOOLS
        except ImportError:
            _CODE_WRITE_TOOLS_LAZY = frozenset({"patch_file", "write_file"})
    return _CODE_WRITE_TOOLS_LAZY


def get_employee_tools(employee_id: str) -> list[str]:
    """返回某员工注册的专属工具名列表。"""
    return list(EMPLOYEE_TOOLS.get(employee_id, []))


def list_all_tool_names() -> list[str]:
    """返回全部已注册工具名。"""
    return sorted(TOOL_REGISTRY)


async def handle_specialized(employee_id: str, payload: Payload, ctx: Payload) -> Payload:
    """专属工具调度入口。

    payload 形如：
        {"handler": "specialized", "tool": "run_pytest", "params": {...}}
    或：
        {"handler": "specialized", "tool": "list_tools"}
    """
    ports = DispatchPorts(TOOL_REGISTRY, get_employee_tools, _code_write_tools, _check_write_gate)
    return await dispatch.handle_specialized(ports, employee_id, payload, ctx)


tool_run_pytest = dispatch.bind_tool(quality.run_pytest, _quality)
tool_run_ruff_check = dispatch.bind_tool(quality.run_ruff_check, _quality)
tool_run_ruff_format = dispatch.bind_tool(quality.run_ruff_format, _quality)
tool_run_mypy = dispatch.bind_tool(quality.run_mypy, _quality)
tool_check_coverage = dispatch.bind_tool(quality.check_coverage, _quality)
tool_count_type_debt = dispatch.bind_tool(quality.count_type_debt, _quality)
tool_count_raw_sql = dispatch.bind_tool(quality.count_raw_sql, _quality)
tool_run_arch_fitness = dispatch.bind_tool(quality.run_arch_fitness, _quality)
tool_verify_version_anchors = dispatch.bind_tool(quality.verify_version_anchors, _quality)
tool_verify_employee_contract = dispatch.bind_tool(quality.verify_employee_contract, _quality)
tool_mutation_kill_report = dispatch.bind_tool(quality.mutation_kill_report, _quality)
tool_git_status = dispatch.bind_tool(release.git_status, _release)
tool_git_log = dispatch.bind_tool(release.git_log, _release)
tool_git_diff = dispatch.bind_tool(release.git_diff, _release)
tool_git_branch = dispatch.bind_tool(release.git_branch, _release)
tool_pack_release = dispatch.bind_tool(release.pack_release, _release)
tool_list_deploy_scripts = dispatch.bind_tool(release.list_deploy_scripts, _release)
tool_trigger_gh_workflow = dispatch.bind_tool(release.trigger_gh_workflow, _release)
tool_nginx_test = dispatch.bind_tool(release.nginx_test, _release)
tool_api_health = dispatch.bind_tool(status.api_health, _status)
tool_mod_loading_status = dispatch.bind_tool(status.mod_loading_status, _status)
tool_disk_usage = dispatch.bind_tool(release.disk_usage, _release)
tool_tail_logs = dispatch.bind_tool(workspace.tail_logs, _workspace)
tool_performance_status = dispatch.bind_tool(status.performance_status, _status)
tool_list_mods = dispatch.bind_tool(status.list_mods, _status)
tool_list_employee_packs = dispatch.bind_tool(employees.list_employee_packs, _employees)
tool_validate_employee_pack = dispatch.bind_tool(employees.validate_employee_pack, _employees)
tool_duty_graph_health = dispatch.bind_tool(status.duty_graph_health, _status)
tool_list_docs = dispatch.bind_tool(workspace.list_docs, _workspace)
tool_read_file = dispatch.bind_tool(workspace.read_file, _workspace)
tool_list_scripts = dispatch.bind_tool(workspace.list_scripts, _workspace)
tool_list_employees = dispatch.bind_tool(employees.list_employees, _employees)
tool_employee_status = dispatch.bind_tool(status.employee_status, _status)
tool_list_action_items = dispatch.bind_tool(status.list_action_items, _status)
tool_employee_autonomy_dashboard = dispatch.bind_tool(status.employee_autonomy_dashboard, _status)
tool_list_workbench_sessions = dispatch.bind_tool(workspace.list_workbench_sessions, _workspace)
tool_sandbox_python = dispatch.bind_tool(quality.sandbox_python, _quality)
tool_check_transactions = dispatch.bind_tool(status.check_transactions, _status)
tool_list_invoices = dispatch.bind_tool(status.list_invoices, _status)
tool_list_enterprise_mods = dispatch.bind_tool(status.list_enterprise_mods, _status)
tool_list_users = dispatch.bind_tool(status.list_users, _status)
tool_frontend_lint = dispatch.bind_tool(quality.frontend_lint, _quality)
tool_frontend_typecheck = dispatch.bind_tool(quality.frontend_typecheck, _quality)
tool_frontend_test = dispatch.bind_tool(quality.frontend_test, _quality)
tool_android_gradle_build = dispatch.bind_tool(quality.android_gradle_build, _quality)
tool_write_file = dispatch.bind_tool(workspace.write_file, _workspace)
tool_patch_file = dispatch.bind_tool(workspace.patch_file, _workspace)
tool_read_llm_env_config = dispatch.bind_tool(configuration.read_llm_env_config, _configuration)
tool_list_configured_providers = dispatch.bind_tool(
    configuration.list_configured_providers, _configuration
)
tool_test_llm_key_health = dispatch.bind_tool(providers.test_llm_key_health, _providers)
tool_query_provider_usage = dispatch.bind_tool(providers.query_provider_usage, _providers)
tool_compare_model_prices = dispatch.bind_tool(usage.compare_model_prices, _usage)
tool_list_vlm_models = dispatch.bind_tool(usage.list_vlm_models, _usage)
tool_get_vlm_route = dispatch.bind_tool(usage.get_vlm_route, _usage)
tool_query_local_token_usage = dispatch.bind_tool(usage.query_local_token_usage, _usage)
tool_query_cursor_usage = dispatch.bind_tool(cursor_usage.query_cursor_usage, _cursor_usage)
tool_query_codex_usage = dispatch.bind_tool(codex_usage.query_codex_usage, lambda: Path.home())
tool_query_trae_usage = dispatch.bind_tool(trae_usage.query_trae_usage, _trae_usage)
TOOL_REGISTRY: dict[str, Tool] = {
    "run_pytest": tool_run_pytest,
    "run_ruff_check": tool_run_ruff_check,
    "run_ruff_format": tool_run_ruff_format,
    "run_mypy": tool_run_mypy,
    "check_coverage": tool_check_coverage,
    "count_type_debt": tool_count_type_debt,
    "count_raw_sql": tool_count_raw_sql,
    "run_arch_fitness": tool_run_arch_fitness,
    "verify_version_anchors": tool_verify_version_anchors,
    "verify_employee_contract": tool_verify_employee_contract,
    "mutation_kill_report": tool_mutation_kill_report,
    "git_status": tool_git_status,
    "git_log": tool_git_log,
    "git_diff": tool_git_diff,
    "git_branch": tool_git_branch,
    "pack_release": tool_pack_release,
    "list_deploy_scripts": tool_list_deploy_scripts,
    "trigger_gh_workflow": tool_trigger_gh_workflow,
    "nginx_test": tool_nginx_test,
    "api_health": tool_api_health,
    "mod_loading_status": tool_mod_loading_status,
    "disk_usage": tool_disk_usage,
    "tail_logs": tool_tail_logs,
    "performance_status": tool_performance_status,
    "list_mods": tool_list_mods,
    "list_employee_packs": tool_list_employee_packs,
    "validate_employee_pack": tool_validate_employee_pack,
    "duty_graph_health": tool_duty_graph_health,
    "list_docs": tool_list_docs,
    "read_file": tool_read_file,
    "list_scripts": tool_list_scripts,
    "list_employees": tool_list_employees,
    "employee_status": tool_employee_status,
    "list_action_items": tool_list_action_items,
    "employee_autonomy_dashboard": tool_employee_autonomy_dashboard,
    "list_workbench_sessions": tool_list_workbench_sessions,
    "sandbox_python": tool_sandbox_python,
    "check_transactions": tool_check_transactions,
    "list_invoices": tool_list_invoices,
    "list_enterprise_mods": tool_list_enterprise_mods,
    "list_users": tool_list_users,
    "frontend_lint": tool_frontend_lint,
    "frontend_typecheck": tool_frontend_typecheck,
    "frontend_test": tool_frontend_test,
    "android_gradle_build": tool_android_gradle_build,
    "patch_file": tool_patch_file,
    "write_file": tool_write_file,
    "read_llm_env_config": tool_read_llm_env_config,
    "list_configured_providers": tool_list_configured_providers,
    "test_llm_key_health": tool_test_llm_key_health,
    "query_provider_usage": tool_query_provider_usage,
    "compare_model_prices": tool_compare_model_prices,
    "list_vlm_models": tool_list_vlm_models,
    "get_vlm_route": tool_get_vlm_route,
    "query_local_token_usage": tool_query_local_token_usage,
    "query_cursor_usage": tool_query_cursor_usage,
    "query_codex_usage": tool_query_codex_usage,
    "query_trae_usage": tool_query_trae_usage,
}
