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
import shutil
import sys
from pathlib import Path
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


from app.mod_sdk.employee_specialized_tools_part01 import (
    _api_call as _api_call,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    _err as _err,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    _ok as _ok,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    _run_cmd as _run_cmd,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    _run_python_script as _run_python_script,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_api_health as tool_api_health,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_check_coverage as tool_check_coverage,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_count_raw_sql as tool_count_raw_sql,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_count_type_debt as tool_count_type_debt,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_disk_usage as tool_disk_usage,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_duty_graph_health as tool_duty_graph_health,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_employee_autonomy_dashboard as tool_employee_autonomy_dashboard,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_employee_status as tool_employee_status,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_git_branch as tool_git_branch,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_git_diff as tool_git_diff,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_git_log as tool_git_log,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_git_status as tool_git_status,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_list_action_items as tool_list_action_items,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_list_deploy_scripts as tool_list_deploy_scripts,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_list_docs as tool_list_docs,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_list_employee_packs as tool_list_employee_packs,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_list_employees as tool_list_employees,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_list_mods as tool_list_mods,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_list_scripts as tool_list_scripts,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_mod_loading_status as tool_mod_loading_status,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_mutation_kill_report as tool_mutation_kill_report,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_nginx_test as tool_nginx_test,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_pack_release as tool_pack_release,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_performance_status as tool_performance_status,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_read_file as tool_read_file,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_run_arch_fitness as tool_run_arch_fitness,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_run_mypy as tool_run_mypy,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_run_pytest as tool_run_pytest,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_run_ruff_check as tool_run_ruff_check,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_run_ruff_format as tool_run_ruff_format,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_tail_logs as tool_tail_logs,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_trigger_gh_workflow as tool_trigger_gh_workflow,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_validate_employee_pack as tool_validate_employee_pack,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_verify_employee_contract as tool_verify_employee_contract,
)
from app.mod_sdk.employee_specialized_tools_part01 import (
    tool_verify_version_anchors as tool_verify_version_anchors,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    _check_write_gate as _check_write_gate,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    _code_write_tools as _code_write_tools,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    _detect_provider_name as _detect_provider_name,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    _mask_secret as _mask_secret,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    _provider_base_url as _provider_base_url,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    _provider_has_key as _provider_has_key,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    _provider_model as _provider_model,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    _read_env_file as _read_env_file,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_android_gradle_build as tool_android_gradle_build,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_check_transactions as tool_check_transactions,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_frontend_lint as tool_frontend_lint,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_frontend_test as tool_frontend_test,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_frontend_typecheck as tool_frontend_typecheck,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_list_configured_providers as tool_list_configured_providers,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_list_enterprise_mods as tool_list_enterprise_mods,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_list_invoices as tool_list_invoices,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_list_users as tool_list_users,
)

# ---------------------------------------------------------------------------
# Craft 工具（制作车间）
# ---------------------------------------------------------------------------
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_list_workbench_sessions as tool_list_workbench_sessions,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_patch_file as tool_patch_file,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_read_llm_env_config as tool_read_llm_env_config,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_sandbox_python as tool_sandbox_python,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_test_llm_key_health as tool_test_llm_key_health,
)
from app.mod_sdk.employee_specialized_tools_part02 import (
    tool_write_file as tool_write_file,
)
from app.mod_sdk.employee_specialized_tools_part03 import (
    tool_compare_model_prices as tool_compare_model_prices,
)
from app.mod_sdk.employee_specialized_tools_part03 import (
    tool_get_vlm_route as tool_get_vlm_route,
)
from app.mod_sdk.employee_specialized_tools_part03 import (
    tool_list_vlm_models as tool_list_vlm_models,
)
from app.mod_sdk.employee_specialized_tools_part03 import (
    tool_query_codex_usage as tool_query_codex_usage,
)
from app.mod_sdk.employee_specialized_tools_part03 import (
    tool_query_cursor_usage as tool_query_cursor_usage,
)
from app.mod_sdk.employee_specialized_tools_part03 import (
    tool_query_local_token_usage as tool_query_local_token_usage,
)
from app.mod_sdk.employee_specialized_tools_part03 import (
    tool_query_provider_usage as tool_query_provider_usage,
)
from app.mod_sdk.employee_specialized_tools_part04 import (
    get_employee_tools as get_employee_tools,
)
from app.mod_sdk.employee_specialized_tools_part04 import (
    handle_specialized as handle_specialized,
)
from app.mod_sdk.employee_specialized_tools_part04 import (
    list_all_tool_names as list_all_tool_names,
)
from app.mod_sdk.employee_specialized_tools_part04 import (
    tool_query_trae_usage as tool_query_trae_usage,
)

# ruff: noqa: F401

_CODE_WRITE_TOOLS_LAZY: frozenset[str] | None = None

_PROVIDER_PROFILES: list[dict[str, Any]] = [{'name': 'b.ai', 'env_keys': ['OPENAI_API_KEY'], 'base_url_env': 'OPENAI_BASE_URL', 'base_url_default': 'https://api.b.ai/v1', 'model_env': 'OPENAI_MODEL', 'default_model': 'MiniMax-M3', 'ping_model': 'MiniMax-M3', 'billing_endpoints': ['/dashboard/billing/credit_grants', '/dashboard/billing/subscription'], 'detect': lambda env: 'b.ai' in env.get('OPENAI_BASE_URL', '')}, {'name': 'openai', 'env_keys': ['OPENAI_API_KEY'], 'base_url_env': 'OPENAI_BASE_URL', 'base_url_default': 'https://api.openai.com/v1', 'model_env': 'OPENAI_MODEL', 'default_model': 'gpt-4o-mini', 'ping_model': 'gpt-4o-mini', 'billing_endpoints': ['/dashboard/billing/credit_grants'], 'detect': lambda env: env.get('OPENAI_BASE_URL', '') in ('', 'https://api.openai.com/v1')}, {'name': 'deepseek', 'env_keys': ['DEEPSEEK_API_KEY'], 'base_url_env': 'DEEPSEEK_BASE_URL', 'base_url_default': 'https://api.deepseek.com/v1', 'model_env': 'DEEPSEEK_MODEL', 'default_model': 'deepseek-chat', 'ping_model': 'deepseek-chat', 'billing_endpoints': ['/user/balance']}, {'name': 'qwen', 'env_keys': ['DASHSCOPE_API_KEY', 'QWEN_API_KEY'], 'base_url_env': 'DASHSCOPE_BASE_URL', 'base_url_default': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'model_env': 'QWEN_MODEL', 'default_model': 'qwen-plus', 'ping_model': 'qwen-turbo', 'billing_endpoints': []}, {'name': 'zhipu', 'env_keys': ['ZHIPU_API_KEY', 'GLM_API_KEY'], 'base_url_env': 'ZHIPU_BASE_URL', 'base_url_default': 'https://open.bigmodel.cn/api/paas/v4', 'model_env': 'GLM_MODEL', 'default_model': 'glm-4-plus', 'ping_model': 'glm-4-flash', 'billing_endpoints': []}, {'name': 'moonshot', 'env_keys': ['MOONSHOT_API_KEY', 'KIMI_API_KEY'], 'base_url_env': 'MOONSHOT_BASE_URL', 'base_url_default': 'https://api.moonshot.cn/v1', 'model_env': 'MOONSHOT_MODEL', 'default_model': 'moonshot-v1-8k', 'ping_model': 'moonshot-v1-8k', 'billing_endpoints': ['/users/me/balance']}, {'name': 'siliconflow', 'env_keys': ['SILICONFLOW_API_KEY'], 'base_url_env': 'SILICONFLOW_BASE_URL', 'base_url_default': 'https://api.siliconflow.cn/v1', 'model_env': 'SILICONFLOW_MODEL', 'default_model': 'deepseek-ai/DeepSeek-V3', 'ping_model': 'Qwen/Qwen2.5-7B-Instruct', 'billing_endpoints': ['/user/info']}, {'name': 'openrouter', 'env_keys': ['OPENROUTER_API_KEY'], 'base_url_env': 'OPENROUTER_BASE_URL', 'base_url_default': 'https://openrouter.ai/api/v1', 'model_env': 'OPENROUTER_MODEL', 'default_model': 'openai/gpt-4o-mini', 'ping_model': 'openai/gpt-4o-mini', 'billing_endpoints': ['/credits']}, {'name': 'volcengine', 'env_keys': ['VOLC_API_KEY', 'ARK_API_KEY'], 'base_url_env': 'VOLC_BASE_URL', 'base_url_default': 'https://ark.cn-beijing.volces.com/api/v3', 'model_env': 'VOLC_MODEL', 'default_model': 'doubao-pro-32k', 'ping_model': 'doubao-lite-4k', 'billing_endpoints': []}, {'name': 'ollama', 'env_keys': [], 'base_url_env': 'OLLAMA_BASE_URL', 'base_url_default': 'http://localhost:11434/v1', 'model_env': 'OLLAMA_MODEL', 'default_model': 'llama3.2', 'ping_model': 'llama3.2', 'billing_endpoints': ['/api/tags'], 'no_auth': True}, {'name': 'minimax', 'env_keys': ['MINIMAX_TOKEN_PLAN_API_KEY', 'MINIMAX_CODING_PLAN_API_KEY', 'MINIMAX_API_KEY'], 'base_url_env': 'MINIMAX_BASE_URL', 'base_url_default': 'https://api.minimaxi.com', 'model_env': 'MINIMAX_MODEL', 'default_model': 'MiniMax-M2.7', 'ping_model': 'MiniMax-M2.7', 'billing_endpoints': ['https://www.minimaxi.com/v1/token_plan/remains']}, {'name': 'mimo', 'env_keys': ['MIMO_API_KEY', 'XIAOMI_API_KEY', 'XIAOMI_MIMO_API_KEY'], 'base_url_env': 'MIMO_BASE_URL', 'base_url_default': 'https://token-plan-cn.xiaomimimo.com/v1', 'model_env': 'MIMO_MODEL', 'default_model': 'mimo-v2.5-pro', 'ping_model': 'mimo-v2.5-pro', 'billing_endpoints': []}]

_LLM_ENV_KEYS: tuple[str, ...] = tuple(dict.fromkeys([k for p in _PROVIDER_PROFILES for k in p['env_keys']] + [p['base_url_env'] for p in _PROVIDER_PROFILES if p.get('base_url_env')] + [p['model_env'] for p in _PROVIDER_PROFILES if p.get('model_env')] + ['XCAGI_LLM_PROVIDER', 'LLM_PROVIDER', 'LLM_MODE', 'FHD_LLM_MODE', 'XCAUTO_API_KEY', 'XCAUTO_PAT', 'XIUCI_API_KEY', 'XCAGI_EMPLOYEE_LLM_MODEL', 'XCAGI_EMPLOYEE_VLM_MODEL', 'XCAGI_EMPLOYEE_VLM_PROVIDER', 'FHD_TEMPLATE_VLM_ENRICH']))

_LLM_SECRET_KEYS: frozenset[str] = frozenset(k for k in _LLM_ENV_KEYS if 'API_KEY' in k or 'PAT' in k or 'SECRET' in k)

_MODEL_PRICES: list[dict[str, Any]] = [{'model': 'DeepSeek-V3', 'provider': 'DeepSeek', 'input_per_1m': 0.27, 'output_per_1m': 1.1, 'context': '64K', 'note': '国产最便宜之一'}, {'model': 'DeepSeek-R1', 'provider': 'DeepSeek', 'input_per_1m': 0.55, 'output_per_1m': 2.19, 'context': '64K', 'note': '推理模型'}, {'model': 'MiniMax-M3', 'provider': 'b.ai', 'input_per_1m': 0.4, 'output_per_1m': 1.5, 'context': '1M', 'note': '当前在用'}, {'model': 'MiniMax-Text-01', 'provider': 'MiniMax', 'input_per_1m': 0.2, 'output_per_1m': 0.8, 'context': '1M', 'note': '便宜'}, {'model': 'gpt-4o', 'provider': 'OpenAI', 'input_per_1m': 2.5, 'output_per_1m': 10.0, 'context': '128K', 'note': '贵'}, {'model': 'gpt-4o-mini', 'provider': 'OpenAI', 'input_per_1m': 0.15, 'output_per_1m': 0.6, 'context': '128K', 'note': '性价比高'}, {'model': 'claude-3.5-sonnet', 'provider': 'Anthropic', 'input_per_1m': 3.0, 'output_per_1m': 15.0, 'context': '200K', 'note': '最贵'}, {'model': 'qwen-max', 'provider': 'qwen', 'input_per_1m': 1.4, 'output_per_1m': 5.6, 'context': '32K', 'note': ''}, {'model': 'qwen-plus', 'provider': 'qwen', 'input_per_1m': 0.14, 'output_per_1m': 0.56, 'context': '128K', 'note': '便宜'}, {'model': 'qwen-turbo', 'provider': 'qwen', 'input_per_1m': 0.05, 'output_per_1m': 0.2, 'context': '1M', 'note': '最便宜之一'}, {'model': 'glm-4-plus', 'provider': 'zhipu', 'input_per_1m': 0.7, 'output_per_1m': 0.7, 'context': '128K', 'note': ''}, {'model': 'glm-4-flash', 'provider': 'zhipu', 'input_per_1m': 0.0, 'output_per_1m': 0.0, 'context': '128K', 'note': '免费！'}, {'model': 'moonshot-v1-8k', 'provider': 'moonshot', 'input_per_1m': 1.68, 'output_per_1m': 1.68, 'context': '8K', 'note': ''}, {'model': 'moonshot-v1-32k', 'provider': 'moonshot', 'input_per_1m': 3.36, 'output_per_1m': 3.36, 'context': '32K', 'note': ''}, {'model': 'deepseek-ai/DeepSeek-V3', 'provider': 'siliconflow', 'input_per_1m': 0.27, 'output_per_1m': 1.1, 'context': '64K', 'note': '聚合代理'}, {'model': 'Qwen/Qwen2.5-7B-Instruct', 'provider': 'siliconflow', 'input_per_1m': 0.0, 'output_per_1m': 0.0, 'context': '32K', 'note': '免费！'}, {'model': 'openai/gpt-4o-mini', 'provider': 'openrouter', 'input_per_1m': 0.15, 'output_per_1m': 0.6, 'context': '128K', 'note': '聚合代理'}, {'model': 'doubao-pro-32k', 'provider': 'volcengine', 'input_per_1m': 0.11, 'output_per_1m': 0.28, 'context': '32K', 'note': '便宜'}, {'model': 'doubao-lite-4k', 'provider': 'volcengine', 'input_per_1m': 0.003, 'output_per_1m': 0.007, 'context': '4K', 'note': '极便宜'}, {'model': 'llama3.2', 'provider': 'ollama', 'input_per_1m': 0.0, 'output_per_1m': 0.0, 'context': '128K', 'note': '本地免费！'}, {'model': 'qwen2.5:7b', 'provider': 'ollama', 'input_per_1m': 0.0, 'output_per_1m': 0.0, 'context': '32K', 'note': '本地免费！'}, {'model': 'mimo-v2.5-pro', 'provider': 'mimo', 'input_per_1m': 0.0, 'output_per_1m': 0.0, 'context': '128K', 'note': 'Token Plan 订阅期内免费'}]

TOOL_REGISTRY: dict[str, Any] = {'run_pytest': tool_run_pytest, 'run_ruff_check': tool_run_ruff_check, 'run_ruff_format': tool_run_ruff_format, 'run_mypy': tool_run_mypy, 'check_coverage': tool_check_coverage, 'count_type_debt': tool_count_type_debt, 'count_raw_sql': tool_count_raw_sql, 'run_arch_fitness': tool_run_arch_fitness, 'verify_version_anchors': tool_verify_version_anchors, 'verify_employee_contract': tool_verify_employee_contract, 'mutation_kill_report': tool_mutation_kill_report, 'git_status': tool_git_status, 'git_log': tool_git_log, 'git_diff': tool_git_diff, 'git_branch': tool_git_branch, 'pack_release': tool_pack_release, 'list_deploy_scripts': tool_list_deploy_scripts, 'trigger_gh_workflow': tool_trigger_gh_workflow, 'nginx_test': tool_nginx_test, 'api_health': tool_api_health, 'mod_loading_status': tool_mod_loading_status, 'disk_usage': tool_disk_usage, 'tail_logs': tool_tail_logs, 'performance_status': tool_performance_status, 'list_mods': tool_list_mods, 'list_employee_packs': tool_list_employee_packs, 'validate_employee_pack': tool_validate_employee_pack, 'duty_graph_health': tool_duty_graph_health, 'list_docs': tool_list_docs, 'read_file': tool_read_file, 'list_scripts': tool_list_scripts, 'list_employees': tool_list_employees, 'employee_status': tool_employee_status, 'list_action_items': tool_list_action_items, 'employee_autonomy_dashboard': tool_employee_autonomy_dashboard, 'list_workbench_sessions': tool_list_workbench_sessions, 'sandbox_python': tool_sandbox_python, 'check_transactions': tool_check_transactions, 'list_invoices': tool_list_invoices, 'list_enterprise_mods': tool_list_enterprise_mods, 'list_users': tool_list_users, 'frontend_lint': tool_frontend_lint, 'frontend_typecheck': tool_frontend_typecheck, 'frontend_test': tool_frontend_test, 'android_gradle_build': tool_android_gradle_build, 'patch_file': tool_patch_file, 'write_file': tool_write_file, 'read_llm_env_config': tool_read_llm_env_config, 'list_configured_providers': tool_list_configured_providers, 'test_llm_key_health': tool_test_llm_key_health, 'query_provider_usage': tool_query_provider_usage, 'compare_model_prices': tool_compare_model_prices, 'list_vlm_models': tool_list_vlm_models, 'get_vlm_route': tool_get_vlm_route, 'query_local_token_usage': tool_query_local_token_usage, 'query_cursor_usage': tool_query_cursor_usage, 'query_codex_usage': tool_query_codex_usage, 'query_trae_usage': tool_query_trae_usage}

EMPLOYEE_TOOLS: dict[str, list[str]] = {'site-content-editor': ['read_file', 'list_docs', 'git_status', 'git_diff'], 'seo-sitemap-curator': ['read_file', 'list_docs', 'api_health', 'git_status'], 'marketing-site-builder': ['list_docs', 'read_file', 'list_scripts', 'git_status'], 'flask-entry-keeper': ['read_file', 'api_health', 'git_diff', 'run_ruff_check'], 'market-frontend-dev': ['frontend_lint', 'frontend_typecheck', 'frontend_test', 'git_diff'], 'workbench-ux-stylist': ['frontend_lint', 'frontend_test', 'read_file', 'list_docs'], 'user-customer-service-officer': ['list_employees', 'employee_status', 'list_action_items', 'list_users'], 'intake-dispatcher': ['list_employees', 'list_workbench_sessions', 'list_action_items'], 'fhd-core-maintainer': ['run_pytest', 'run_ruff_check', 'run_mypy', 'check_coverage', 'count_type_debt', 'count_raw_sql', 'verify_version_anchors', 'git_diff', 'patch_file', 'write_file'], 'vibe-coding-maintainer': ['run_pytest', 'run_ruff_check', 'git_status', 'git_diff', 'read_file'], 'mods-and-eskill-curator': ['list_mods', 'list_employee_packs', 'validate_employee_pack', 'mod_loading_status'], 'change-request-auditor': ['git_diff', 'git_log', 'run_ruff_check', 'run_mypy', 'verify_employee_contract'], 'daily-orchestrator': ['list_employees', 'employee_status', 'duty_graph_health', 'list_action_items', 'employee_autonomy_dashboard'], 'task-router-officer': ['list_employees', 'employee_status', 'list_action_items'], 'enterprise-adoption-officer': ['list_users', 'list_enterprise_mods', 'list_mods'], 'delivery-receipt-officer': ['git_log', 'git_status', 'list_action_items', 'api_health'], 'mobile-android-release-officer': ['android_gradle_build', 'git_status', 'git_log', 'list_scripts'], 'mobile-ios-release-officer': ['git_status', 'git_log', 'list_scripts', 'read_file'], 'modstore-backend-api': ['api_health', 'run_pytest', 'run_ruff_check', 'git_diff', 'performance_status'], 'employee-pack-curator': ['list_employee_packs', 'validate_employee_pack', 'list_mods', 'verify_employee_contract'], 'java-payment-bridge-officer': ['api_health', 'check_transactions', 'list_invoices', 'read_file'], 'payment-billing-reconciler': ['check_transactions', 'list_invoices', 'list_users', 'read_file'], 'nginx-config-engineer': ['nginx_test', 'api_health', 'read_file', 'git_diff'], 'push-update-context-officer': ['list_deploy_scripts', 'git_log', 'api_health', 'read_file'], 'deploy-release-officer': ['pack_release', 'list_deploy_scripts', 'trigger_gh_workflow', 'git_status', 'git_log', 'api_health'], 'security-secrets-guard': ['git_diff', 'read_file', 'list_scripts', 'git_status'], 'log-monitor-incident': ['tail_logs', 'api_health', 'performance_status', 'disk_usage'], 'retention-officer': ['disk_usage', 'tail_logs', 'list_scripts', 'git_status'], 'dbops-engineer': ['api_health', 'performance_status', 'read_file', 'tail_logs'], 'legacy-archive-curator': ['disk_usage', 'list_scripts', 'git_status', 'read_file'], 'llm-ops-engineer': ['read_llm_env_config', 'list_configured_providers', 'test_llm_key_health', 'query_provider_usage', 'compare_model_prices', 'list_vlm_models', 'get_vlm_route', 'query_local_token_usage', 'query_cursor_usage', 'query_codex_usage', 'query_trae_usage'], 'test-qa-runner': ['run_pytest', 'run_ruff_check', 'run_ruff_format', 'run_mypy', 'check_coverage', 'run_arch_fitness', 'frontend_test'], 'doc-knowledge-curator': ['list_docs', 'read_file', 'verify_version_anchors', 'git_status'], 'employee-interview-assistant': ['list_employees', 'list_employee_packs', 'validate_employee_pack', 'employee_status'], 'employee-pack-quality-interviewer': ['validate_employee_pack', 'list_employee_packs', 'verify_employee_contract', 'list_mods'], 'intent-analyst': ['list_workbench_sessions', 'list_employees', 'list_action_items'], 'employee-planner': ['list_employees', 'list_workbench_sessions', 'read_file', 'list_docs'], 'artifact-generator': ['sandbox_python', 'read_file', 'list_scripts', 'git_diff'], 'quality-validator': ['run_ruff_check', 'run_mypy', 'run_arch_fitness', 'verify_employee_contract'], 'miniapp-builder': ['frontend_lint', 'frontend_typecheck', 'list_scripts', 'read_file'], 'script-binder': ['read_file', 'list_scripts', 'sandbox_python', 'git_diff'], 'workflow-automator': ['list_scripts', 'read_file', 'api_health', 'list_action_items'], 'pack-registrar': ['list_employee_packs', 'validate_employee_pack', 'list_mods', 'git_status'], 'sandbox-tester': ['sandbox_python', 'run_pytest', 'frontend_test', 'read_file'], 'code-validator': ['run_ruff_check', 'run_ruff_format', 'run_mypy', 'run_arch_fitness'], 'self-checker': ['run_pytest', 'run_ruff_check', 'verify_version_anchors', 'check_coverage'], 'host-checker': ['api_health', 'disk_usage', 'nginx_test', 'mod_loading_status', 'performance_status'], 'hex-quality-assessor': ['run_pytest', 'run_ruff_check', 'run_mypy', 'check_coverage', 'count_type_debt', 'count_raw_sql', 'run_arch_fitness', 'mutation_kill_report'], 'ecosystem-partner-onboard-officer': ['list_users', 'list_enterprise_mods', 'list_mods', 'list_action_items'], 'ecosystem-joint-catalog-officer': ['list_mods', 'list_enterprise_mods', 'list_employee_packs', 'validate_employee_pack'], 'ecosystem-delivery-reporter': ['git_log', 'list_action_items', 'api_health', 'list_employees'], 'ecosystem-investor-portal-officer': ['list_users', 'list_invoices', 'check_transactions', 'api_health'], 'ecosystem-revenue-share-reconciler': ['check_transactions', 'list_invoices', 'list_users', 'read_file']}
