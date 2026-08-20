# ruff: noqa: F401, I001
"""AI 员工专属工具调用库。

为 52 个编制员工提供真实的专属工具实现（subprocess / httpx / 文件操作），
而非仅靠 LLM system_prompt 驱动。工具按域分组，每个员工按职责注册 2-4 个工具。

设计原则：
- 真实执行：跑真实命令（pytest/ruff/mypy/git）、调真实内部 API、读写真实文件
- 只读优先：涉及写操作的工具需 payload.confirm=True 二次确认
- 零侵入员工 .py：specialized handler 在 executor 层拦截，不修改 52 个员工文件
- 安全边界：subprocess 限定白名单命令，httpx 只打本机/白名单 host
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

_FHD_ROOT = Path(__file__).resolve().parents[2]  # .../FHD
_SCRIPTS = _FHD_ROOT / "scripts"
_VENV_PYTHON = str(_FHD_ROOT / ".venv" / "bin" / "python")
_PYTHON = _VENV_PYTHON if os.path.isfile(_VENV_PYTHON) else sys.executable
_EMPLOYEES_DIR = _FHD_ROOT / "mods" / "_employees"
_DUTY_ROSTER = _FHD_ROOT / "config" / "duty_roster.json"

# 本机 API base（executor 注入的 ctx 可覆盖）
_DEFAULT_API_BASE = os.environ.get("XCAGI_EMPLOYEE_API_BASE", "http://127.0.0.1:5102")

# subprocess 超时（秒）
_DEFAULT_TIMEOUT = 120


# ---------------------------------------------------------------------------
# 工具结果构造
# ---------------------------------------------------------------------------

# fmt: off
from app.mod_sdk.employee_specialized_tools_part01 import (_api_call as _api_call, _err as _err,
                                                           _ok as _ok, _run_cmd as _run_cmd,
                                                           _run_python_script as _run_python_script,
                                                           tool_api_health as tool_api_health,
                                                           tool_check_coverage as
                                                           tool_check_coverage,
                                                           tool_count_raw_sql as tool_count_raw_sql,
                                                           tool_count_type_debt as
                                                           tool_count_type_debt,
                                                           tool_disk_usage as tool_disk_usage,
                                                           tool_duty_graph_health as
                                                           tool_duty_graph_health,
                                                           tool_employee_autonomy_dashboard as
                                                           tool_employee_autonomy_dashboard,
                                                           tool_employee_status as
                                                           tool_employee_status,
                                                           tool_git_branch as tool_git_branch,
                                                           tool_git_diff as tool_git_diff,
                                                           tool_git_log as tool_git_log,
                                                           tool_git_status as tool_git_status,
                                                           tool_list_action_items as
                                                           tool_list_action_items,
                                                           tool_list_deploy_scripts as
                                                           tool_list_deploy_scripts,
                                                           tool_list_docs as tool_list_docs,
                                                           tool_list_employee_packs as
                                                           tool_list_employee_packs,
                                                           tool_list_employees as
                                                           tool_list_employees,
                                                           tool_list_mods as tool_list_mods,
                                                           tool_list_scripts as tool_list_scripts,
                                                           tool_mod_loading_status as
                                                           tool_mod_loading_status,
                                                           tool_mutation_kill_report as
                                                           tool_mutation_kill_report,
                                                           tool_nginx_test as tool_nginx_test,
                                                           tool_pack_release as tool_pack_release,
                                                           tool_performance_status as
                                                           tool_performance_status,
                                                           tool_read_file as tool_read_file,
                                                           tool_run_arch_fitness as
                                                           tool_run_arch_fitness,
                                                           tool_run_mypy as tool_run_mypy,
                                                           tool_run_pytest as tool_run_pytest,
                                                           tool_run_ruff_check as
                                                           tool_run_ruff_check,
                                                           tool_run_ruff_format as
                                                           tool_run_ruff_format,
                                                           tool_tail_logs as tool_tail_logs,
                                                           tool_trigger_gh_workflow as
                                                           tool_trigger_gh_workflow,
                                                           tool_validate_employee_pack as
                                                           tool_validate_employee_pack,
                                                           tool_verify_employee_contract as
                                                           tool_verify_employee_contract,
                                                           tool_verify_version_anchors as
                                                           tool_verify_version_anchors)
# ---------------------------------------------------------------------------
# Craft 工具（制作车间）
# ---------------------------------------------------------------------------
from app.mod_sdk.employee_specialized_tools_part02 import (_check_write_gate as _check_write_gate,
                                                           _code_write_tools as _code_write_tools,
                                                           _detect_provider_name as
                                                           _detect_provider_name,
                                                           _mask_secret as _mask_secret,
                                                           _provider_base_url as _provider_base_url,
                                                           _provider_has_key as _provider_has_key,
                                                           _provider_model as _provider_model,
                                                           _read_env_file as _read_env_file,
                                                           tool_android_gradle_build as
                                                           tool_android_gradle_build,
                                                           tool_check_transactions as
                                                           tool_check_transactions,
                                                           tool_frontend_lint as tool_frontend_lint,
                                                           tool_frontend_test as tool_frontend_test,
                                                           tool_frontend_typecheck as
                                                           tool_frontend_typecheck,
                                                           tool_list_configured_providers as
                                                           tool_list_configured_providers,
                                                           tool_list_enterprise_mods as
                                                           tool_list_enterprise_mods,
                                                           tool_list_invoices as tool_list_invoices,
                                                           tool_list_users as tool_list_users,
                                                           tool_list_workbench_sessions as
                                                           tool_list_workbench_sessions,
                                                           tool_patch_file as tool_patch_file,
                                                           tool_read_llm_env_config as
                                                           tool_read_llm_env_config,
                                                           tool_sandbox_python as
                                                           tool_sandbox_python,
                                                           tool_test_llm_key_health as
                                                           tool_test_llm_key_health,
                                                           tool_write_file as tool_write_file)
from app.mod_sdk.employee_specialized_tools_part03 import (
    tool_compare_model_prices as tool_compare_model_prices,
    tool_get_vlm_route as tool_get_vlm_route, tool_list_vlm_models as tool_list_vlm_models,
    tool_query_codex_usage as tool_query_codex_usage,
    tool_query_cursor_usage as tool_query_cursor_usage,
    tool_query_local_token_usage as tool_query_local_token_usage,
    tool_query_provider_usage as tool_query_provider_usage)
from app.mod_sdk.employee_specialized_tools_part04 import (get_employee_tools as get_employee_tools,
                                                           handle_specialized as handle_specialized,
                                                           list_all_tool_names as
                                                           list_all_tool_names,
                                                           tool_query_trae_usage as
                                                           tool_query_trae_usage)

# fmt: on

_CODE_WRITE_TOOLS_LAZY: frozenset[str] | None = None

from app.mod_sdk.employee_specialized_tools_provider_catalog import (
    _PROVIDER_PROFILES as _PROVIDER_PROFILES,
    _LLM_ENV_KEYS as _LLM_ENV_KEYS,
    _MODEL_PRICES as _MODEL_PRICES,
)


_LLM_SECRET_KEYS: frozenset[str] = frozenset(
    k for k in _LLM_ENV_KEYS if "API_KEY" in k or "PAT" in k or "SECRET" in k
)


TOOL_REGISTRY: dict[str, Any] = {
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

from app.mod_sdk.employee_specialized_tools_employee_map import (
    EMPLOYEE_TOOLS as EMPLOYEE_TOOLS,
)
