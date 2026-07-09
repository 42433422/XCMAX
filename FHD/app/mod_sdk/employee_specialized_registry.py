"""Registry."""

from __future__ import annotations

from typing import Any

from app.mod_sdk.employee_specialized_git_deploy import (
    tool_android_gradle_build,
    tool_api_health,
    tool_check_transactions,
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
    tool_nginx_test,
    tool_pack_release,
    tool_performance_status,
    tool_read_file,
    tool_sandbox_python,
    tool_tail_logs,
    tool_trigger_gh_workflow,
    tool_validate_employee_pack,
)
from app.mod_sdk.employee_specialized_llm_ops import (
    tool_compare_model_prices,
    tool_list_configured_providers,
    tool_query_codex_usage,
    tool_query_cursor_usage,
    tool_query_local_token_usage,
    tool_query_provider_usage,
    tool_query_trae_usage,
    tool_read_llm_env_config,
    tool_test_llm_key_health,
)
from app.mod_sdk.employee_specialized_quality import (
    tool_check_coverage,
    tool_count_raw_sql,
    tool_count_type_debt,
    tool_mutation_kill_report,
    tool_run_arch_fitness,
    tool_run_mypy,
    tool_run_pytest,
    tool_run_ruff_check,
    tool_run_ruff_format,
    tool_verify_employee_contract,
    tool_verify_version_anchors,
)
from app.mod_sdk.employee_specialized_runtime import _err, _facade_attr, _ok
from app.mod_sdk.employee_specialized_write_gate import (
    _check_write_gate,
    _code_write_tools,
    tool_patch_file,
    tool_write_file,
)

TOOL_REGISTRY: dict[str, Any] = {
    # quality
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
    # git
    "git_status": tool_git_status,
    "git_log": tool_git_log,
    "git_diff": tool_git_diff,
    "git_branch": tool_git_branch,
    # deploy
    "pack_release": tool_pack_release,
    "list_deploy_scripts": tool_list_deploy_scripts,
    "trigger_gh_workflow": tool_trigger_gh_workflow,
    # infra
    "nginx_test": tool_nginx_test,
    "api_health": tool_api_health,
    "mod_loading_status": tool_mod_loading_status,
    "disk_usage": tool_disk_usage,
    "tail_logs": tool_tail_logs,
    "performance_status": tool_performance_status,
    # mod
    "list_mods": tool_list_mods,
    "list_employee_packs": tool_list_employee_packs,
    "validate_employee_pack": tool_validate_employee_pack,
    "duty_graph_health": tool_duty_graph_health,
    # doc
    "list_docs": tool_list_docs,
    "read_file": tool_read_file,
    "list_scripts": tool_list_scripts,
    # platform
    "list_employees": tool_list_employees,
    "employee_status": tool_employee_status,
    "list_action_items": tool_list_action_items,
    "employee_autonomy_dashboard": tool_employee_autonomy_dashboard,
    # craft
    "list_workbench_sessions": tool_list_workbench_sessions,
    "sandbox_python": tool_sandbox_python,
    # payment
    "check_transactions": tool_check_transactions,
    "list_invoices": tool_list_invoices,
    # ecosystem
    "list_enterprise_mods": tool_list_enterprise_mods,
    "list_users": tool_list_users,
    # frontend
    "frontend_lint": tool_frontend_lint,
    "frontend_typecheck": tool_frontend_typecheck,
    "frontend_test": tool_frontend_test,
    # mobile
    "android_gradle_build": tool_android_gradle_build,
    # code-write（受 scope_globs + write_approval gate 约束）
    "patch_file": tool_patch_file,
    "write_file": tool_write_file,
    # llm-ops（llm-ops-engineer 专属，支持 11 家 provider）
    "read_llm_env_config": tool_read_llm_env_config,
    "list_configured_providers": tool_list_configured_providers,
    "test_llm_key_health": tool_test_llm_key_health,
    "query_provider_usage": tool_query_provider_usage,
    "compare_model_prices": tool_compare_model_prices,
    "query_local_token_usage": tool_query_local_token_usage,
    "query_cursor_usage": tool_query_cursor_usage,
    "query_codex_usage": tool_query_codex_usage,
    "query_trae_usage": tool_query_trae_usage,
}


# ---------------------------------------------------------------------------
# 52 个编制员工的专属工具注册
# ---------------------------------------------------------------------------

EMPLOYEE_TOOLS: dict[str, list[str]] = {
    # --- site-and-marketing ---
    "site-content-editor": ["read_file", "list_docs", "git_status", "git_diff"],
    "seo-sitemap-curator": ["read_file", "list_docs", "api_health", "git_status"],
    "marketing-site-builder": ["list_docs", "read_file", "list_scripts", "git_status"],
    "flask-entry-keeper": ["read_file", "api_health", "git_diff", "run_ruff_check"],
    # --- modstore-frontend ---
    "market-frontend-dev": ["frontend_lint", "frontend_typecheck", "frontend_test", "git_diff"],
    "workbench-ux-stylist": ["frontend_lint", "frontend_test", "read_file", "list_docs"],
    # --- platform-core ---
    "user-customer-service-officer": [
        "list_employees",
        "employee_status",
        "list_action_items",
        "list_users",
    ],
    "intake-dispatcher": ["list_employees", "list_workbench_sessions", "list_action_items"],
    "fhd-core-maintainer": [
        "run_pytest",
        "run_ruff_check",
        "run_mypy",
        "check_coverage",
        "count_type_debt",
        "count_raw_sql",
        "verify_version_anchors",
        "git_diff",
        "patch_file",
        "write_file",
    ],
    "vibe-coding-maintainer": [
        "run_pytest",
        "run_ruff_check",
        "git_status",
        "git_diff",
        "read_file",
    ],
    "mods-and-eskill-curator": [
        "list_mods",
        "list_employee_packs",
        "validate_employee_pack",
        "mod_loading_status",
    ],
    "change-request-auditor": [
        "git_diff",
        "git_log",
        "run_ruff_check",
        "run_mypy",
        "verify_employee_contract",
    ],
    "daily-orchestrator": [
        "list_employees",
        "employee_status",
        "duty_graph_health",
        "list_action_items",
        "employee_autonomy_dashboard",
    ],
    "task-router-officer": ["list_employees", "employee_status", "list_action_items"],
    "enterprise-adoption-officer": ["list_users", "list_enterprise_mods", "list_mods"],
    "delivery-receipt-officer": ["git_log", "git_status", "list_action_items", "api_health"],
    "mobile-android-release-officer": [
        "android_gradle_build",
        "git_status",
        "git_log",
        "list_scripts",
    ],
    "mobile-ios-release-officer": ["git_status", "git_log", "list_scripts", "read_file"],
    # --- modstore-backend ---
    "modstore-backend-api": [
        "api_health",
        "run_pytest",
        "run_ruff_check",
        "git_diff",
        "performance_status",
    ],
    "employee-pack-curator": [
        "list_employee_packs",
        "validate_employee_pack",
        "list_mods",
        "verify_employee_contract",
    ],
    "java-payment-bridge-officer": [
        "api_health",
        "check_transactions",
        "list_invoices",
        "read_file",
    ],
    "payment-billing-reconciler": [
        "check_transactions",
        "list_invoices",
        "list_users",
        "read_file",
    ],
    # --- server-and-ops ---
    "nginx-config-engineer": ["nginx_test", "api_health", "read_file", "git_diff"],
    "push-update-context-officer": ["list_deploy_scripts", "git_log", "api_health", "read_file"],
    "deploy-release-officer": [
        "pack_release",
        "list_deploy_scripts",
        "trigger_gh_workflow",
        "git_status",
        "git_log",
        "api_health",
    ],
    "security-secrets-guard": ["git_diff", "read_file", "list_scripts", "git_status"],
    "log-monitor-incident": ["tail_logs", "api_health", "performance_status", "disk_usage"],
    "retention-officer": ["disk_usage", "tail_logs", "list_scripts", "git_status"],
    "dbops-engineer": ["api_health", "performance_status", "read_file", "tail_logs"],
    "legacy-archive-curator": ["disk_usage", "list_scripts", "git_status", "read_file"],
    "llm-ops-engineer": [
        "read_llm_env_config",
        "list_configured_providers",
        "test_llm_key_health",
        "query_provider_usage",
        "compare_model_prices",
        "query_local_token_usage",
        "query_cursor_usage",
        "query_codex_usage",
        "query_trae_usage",
    ],
    # --- quality-and-docs ---
    "test-qa-runner": [
        "run_pytest",
        "run_ruff_check",
        "run_ruff_format",
        "run_mypy",
        "check_coverage",
        "run_arch_fitness",
        "frontend_test",
    ],
    "doc-knowledge-curator": ["list_docs", "read_file", "verify_version_anchors", "git_status"],
    "employee-interview-assistant": [
        "list_employees",
        "list_employee_packs",
        "validate_employee_pack",
        "employee_status",
    ],
    "employee-pack-quality-interviewer": [
        "validate_employee_pack",
        "list_employee_packs",
        "verify_employee_contract",
        "list_mods",
    ],
    # --- craft-workshop ---
    "intent-analyst": ["list_workbench_sessions", "list_employees", "list_action_items"],
    "employee-planner": ["list_employees", "list_workbench_sessions", "read_file", "list_docs"],
    "artifact-generator": ["sandbox_python", "read_file", "list_scripts", "git_diff"],
    "quality-validator": [
        "run_ruff_check",
        "run_mypy",
        "run_arch_fitness",
        "verify_employee_contract",
    ],
    "miniapp-builder": ["frontend_lint", "frontend_typecheck", "list_scripts", "read_file"],
    "script-binder": ["read_file", "list_scripts", "sandbox_python", "git_diff"],
    "workflow-automator": ["list_scripts", "read_file", "api_health", "list_action_items"],
    "pack-registrar": ["list_employee_packs", "validate_employee_pack", "list_mods", "git_status"],
    "sandbox-tester": ["sandbox_python", "run_pytest", "frontend_test", "read_file"],
    "code-validator": ["run_ruff_check", "run_ruff_format", "run_mypy", "run_arch_fitness"],
    "self-checker": ["run_pytest", "run_ruff_check", "verify_version_anchors", "check_coverage"],
    "host-checker": [
        "api_health",
        "disk_usage",
        "nginx_test",
        "mod_loading_status",
        "performance_status",
    ],
    "hex-quality-assessor": [
        "run_pytest",
        "run_ruff_check",
        "run_mypy",
        "check_coverage",
        "count_type_debt",
        "count_raw_sql",
        "run_arch_fitness",
        "mutation_kill_report",
    ],
    # --- partner-ecosystem ---
    "ecosystem-partner-onboard-officer": [
        "list_users",
        "list_enterprise_mods",
        "list_mods",
        "list_action_items",
    ],
    "ecosystem-joint-catalog-officer": [
        "list_mods",
        "list_enterprise_mods",
        "list_employee_packs",
        "validate_employee_pack",
    ],
    "ecosystem-delivery-reporter": ["git_log", "list_action_items", "api_health", "list_employees"],
    "ecosystem-investor-portal-officer": [
        "list_users",
        "list_invoices",
        "check_transactions",
        "api_health",
    ],
    "ecosystem-revenue-share-reconciler": [
        "check_transactions",
        "list_invoices",
        "list_users",
        "read_file",
    ],
}


def get_employee_tools(employee_id: str) -> list[str]:
    """返回某员工注册的专属工具名列表。"""
    return list(EMPLOYEE_TOOLS.get(employee_id, []))


def list_all_tool_names() -> list[str]:
    """返回全部已注册工具名。"""
    return sorted(TOOL_REGISTRY.keys())


# ---------------------------------------------------------------------------
# 专属工具调度入口（executor 拦截 specialized handler 时调用）
# ---------------------------------------------------------------------------


async def handle_specialized(
    employee_id: str, payload: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """专属工具调度入口。

    payload 形如：
        {"handler": "specialized", "tool": "run_pytest", "params": {...}}
    或：
        {"handler": "specialized", "tool": "list_tools"}
    """
    tool_name = str(payload.get("tool") or "").strip()
    if not tool_name:
        # 未指定 tool → 返回该员工可用的工具清单
        available = get_employee_tools(employee_id)
        return _facade_attr("_ok", _ok)(
            f"员工 {employee_id} 可用 {len(available)} 个专属工具",
            employee_id=employee_id,
            available_tools=available,
            handler="specialized",
        )

    allowed = get_employee_tools(employee_id)
    if tool_name not in allowed:
        return _facade_attr("_err", _err)(
            f"工具 {tool_name!r} 不在员工 {employee_id} 的专属工具清单中。可用: {allowed}",
            employee_id=employee_id,
            available_tools=allowed,
        )

    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None or not callable(fn):
        return _facade_attr("_err", _err)(f"工具 {tool_name!r} 未实现")

    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return _facade_attr("_err", _err)("params 必须为对象")

    # 代码修改工具走 workspace_guard + write_approval gate（纵深防御）
    if tool_name in _facade_attr("_code_write_tools", _code_write_tools)():
        gate_verdict = await _facade_attr("_check_write_gate", _check_write_gate)(employee_id, tool_name, params, ctx)
        if not gate_verdict.get("ok", True):
            return _facade_attr("_err", _err)(
                f"写操作被 gate 拦截: {gate_verdict.get('reason', '')}",
                blocked=True,
                gate_result=gate_verdict,
                pending_approval=bool(gate_verdict.get("pending_approval")),
                approval_request_ids=list(gate_verdict.get("approval_request_ids") or []),
            )

    try:
        result = await fn(params, ctx)
    except Exception as exc:  # noqa: BLE001  工具调度边界：任何异常都转为结构化结果
        return _facade_attr("_err", _err)(f"工具 {tool_name!r} 执行异常: {exc!r}")

    if not isinstance(result, dict):
        return _facade_attr("_ok", _ok)(f"工具 {tool_name!r} 完成", raw=result)

    result.setdefault("tool", tool_name)
    result.setdefault("employee_id", employee_id)
    result.setdefault("handler", "specialized")
    return result
