"""AI 员工专属工具调用库（facade — 实现已拆至 sibling 模块）。"""

from __future__ import annotations

import shutil as shutil
import subprocess as subprocess

from app.mod_sdk.employee_specialized_git_deploy import (
    tool_android_gradle_build as tool_android_gradle_build,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_api_health as tool_api_health,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_check_transactions as tool_check_transactions,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_disk_usage as tool_disk_usage,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_duty_graph_health as tool_duty_graph_health,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_employee_autonomy_dashboard as tool_employee_autonomy_dashboard,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_employee_status as tool_employee_status,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_frontend_lint as tool_frontend_lint,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_frontend_test as tool_frontend_test,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_frontend_typecheck as tool_frontend_typecheck,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_git_branch as tool_git_branch,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_git_diff as tool_git_diff,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_git_log as tool_git_log,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_git_status as tool_git_status,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_list_action_items as tool_list_action_items,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_list_deploy_scripts as tool_list_deploy_scripts,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_list_docs as tool_list_docs,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_list_employee_packs as tool_list_employee_packs,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_list_employees as tool_list_employees,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_list_enterprise_mods as tool_list_enterprise_mods,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_list_invoices as tool_list_invoices,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_list_mods as tool_list_mods,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_list_scripts as tool_list_scripts,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_list_users as tool_list_users,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_list_workbench_sessions as tool_list_workbench_sessions,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_mod_loading_status as tool_mod_loading_status,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_nginx_test as tool_nginx_test,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_pack_release as tool_pack_release,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_performance_status as tool_performance_status,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_read_file as tool_read_file,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_sandbox_python as tool_sandbox_python,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_tail_logs as tool_tail_logs,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_trigger_gh_workflow as tool_trigger_gh_workflow,
)
from app.mod_sdk.employee_specialized_git_deploy import (
    tool_validate_employee_pack as tool_validate_employee_pack,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    _LLM_ENV_KEYS as _LLM_ENV_KEYS,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    _LLM_SECRET_KEYS as _LLM_SECRET_KEYS,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    _MODEL_PRICES as _MODEL_PRICES,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    _PROVIDER_PROFILES as _PROVIDER_PROFILES,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    _detect_provider_name as _detect_provider_name,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    _mask_secret as _mask_secret,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    _provider_base_url as _provider_base_url,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    _provider_has_key as _provider_has_key,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    _provider_model as _provider_model,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    _read_env_file as _read_env_file,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    tool_compare_model_prices as tool_compare_model_prices,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    tool_list_configured_providers as tool_list_configured_providers,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    tool_query_codex_usage as tool_query_codex_usage,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    tool_query_cursor_usage as tool_query_cursor_usage,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    tool_query_local_token_usage as tool_query_local_token_usage,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    tool_query_provider_usage as tool_query_provider_usage,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    tool_query_trae_usage as tool_query_trae_usage,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    tool_read_llm_env_config as tool_read_llm_env_config,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    tool_test_llm_key_health as tool_test_llm_key_health,
)
from app.mod_sdk.employee_specialized_quality import (
    tool_check_coverage as tool_check_coverage,
)
from app.mod_sdk.employee_specialized_quality import (
    tool_count_raw_sql as tool_count_raw_sql,
)
from app.mod_sdk.employee_specialized_quality import (
    tool_count_type_debt as tool_count_type_debt,
)
from app.mod_sdk.employee_specialized_quality import (
    tool_mutation_kill_report as tool_mutation_kill_report,
)
from app.mod_sdk.employee_specialized_quality import (
    tool_run_arch_fitness as tool_run_arch_fitness,
)
from app.mod_sdk.employee_specialized_quality import (
    tool_run_mypy as tool_run_mypy,
)
from app.mod_sdk.employee_specialized_quality import (
    tool_run_pytest as tool_run_pytest,
)
from app.mod_sdk.employee_specialized_quality import (
    tool_run_ruff_check as tool_run_ruff_check,
)
from app.mod_sdk.employee_specialized_quality import (
    tool_run_ruff_format as tool_run_ruff_format,
)
from app.mod_sdk.employee_specialized_quality import (
    tool_verify_employee_contract as tool_verify_employee_contract,
)
from app.mod_sdk.employee_specialized_quality import (
    tool_verify_version_anchors as tool_verify_version_anchors,
)
from app.mod_sdk.employee_specialized_registry import (
    EMPLOYEE_TOOLS as EMPLOYEE_TOOLS,
)
from app.mod_sdk.employee_specialized_registry import (
    TOOL_REGISTRY as TOOL_REGISTRY,
)
from app.mod_sdk.employee_specialized_registry import (
    get_employee_tools as get_employee_tools,
)
from app.mod_sdk.employee_specialized_registry import (
    handle_specialized as handle_specialized,
)
from app.mod_sdk.employee_specialized_registry import (
    list_all_tool_names as list_all_tool_names,
)
from app.mod_sdk.employee_specialized_runtime import (
    _DEFAULT_API_BASE as _DEFAULT_API_BASE,
)
from app.mod_sdk.employee_specialized_runtime import (
    _DEFAULT_TIMEOUT as _DEFAULT_TIMEOUT,
)
from app.mod_sdk.employee_specialized_runtime import (
    _DUTY_ROSTER as _DUTY_ROSTER,
)
from app.mod_sdk.employee_specialized_runtime import (
    _EMPLOYEES_DIR as _EMPLOYEES_DIR,
)
from app.mod_sdk.employee_specialized_runtime import (
    _FHD_ROOT as _FHD_ROOT,
)
from app.mod_sdk.employee_specialized_runtime import (
    _PYTHON as _PYTHON,
)
from app.mod_sdk.employee_specialized_runtime import (
    _SCRIPTS as _SCRIPTS,
)
from app.mod_sdk.employee_specialized_runtime import (
    _VENV_PYTHON as _VENV_PYTHON,
)
from app.mod_sdk.employee_specialized_runtime import (
    _api_call as _api_call,
)
from app.mod_sdk.employee_specialized_runtime import (
    _err as _err,
)
from app.mod_sdk.employee_specialized_runtime import (
    _ok as _ok,
)
from app.mod_sdk.employee_specialized_runtime import (
    _run_cmd as _run_cmd,
)
from app.mod_sdk.employee_specialized_runtime import (
    _run_python_script as _run_python_script,
)
from app.mod_sdk.employee_specialized_runtime import (
    httpx as httpx,
)
from app.mod_sdk.employee_specialized_write_gate import (
    _CODE_WRITE_TOOLS_LAZY as _CODE_WRITE_TOOLS_LAZY,
)
from app.mod_sdk.employee_specialized_write_gate import (
    _check_write_gate as _check_write_gate,
)
from app.mod_sdk.employee_specialized_write_gate import (
    _code_write_tools as _code_write_tools,
)
from app.mod_sdk.employee_specialized_write_gate import (
    tool_patch_file as tool_patch_file,
)
from app.mod_sdk.employee_specialized_write_gate import (
    tool_write_file as tool_write_file,
)
