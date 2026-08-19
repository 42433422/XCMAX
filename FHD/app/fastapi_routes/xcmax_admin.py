"""XCmax 服务器后台控制面路由。

提供:
  GET  /api/xcmax/admin/modules      — 本地模块注册表（核心 + Mod + 员工包）
  GET  /api/xcmax/admin/remote-status — 远端服务器连接状态探测
  GET  /api/xcmax/sync/status        — 双向同步健康状态
  POST /api/xcmax/sync/push          — 触发本地 outbox 向服务器推送
  GET  /api/xcmax/sync/changes       — 获取变更日志（支持 since_cursor）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.request
from typing import Any, cast

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.fastapi_routes.xcmax_admin_auth import (
    admin_approver_from_session as _admin_approver_from_session,
)
from app.fastapi_routes.xcmax_admin_auth import (
    require_market_admin_session as _require_market_admin_session,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/xcmax", tags=["xcmax-admin"])

REMOTE_HOST = os.environ.get("XCMAX_REMOTE_HOST", "119.27.178.147")
REMOTE_PORT = int(os.environ.get("XCMAX_REMOTE_PORT", "9999"))
_DEFAULT_URLOPEN = urllib.request.urlopen


from app.fastapi_routes.xcmax_admin_part01 import (
    _digest_local_or_proxy as _digest_local_or_proxy,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    _digest_payload_nonempty as _digest_payload_nonempty,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    _digest_record_id_from_path as _digest_record_id_from_path,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    _fetch_remote_xcmax_daily_digests as _fetch_remote_xcmax_daily_digests,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    _is_daily_digest_artifacts_path as _is_daily_digest_artifacts_path,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    _is_daily_digest_detail_path as _is_daily_digest_detail_path,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    _is_daily_digest_list_path as _is_daily_digest_list_path,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    _market_admin_proxy as _market_admin_proxy,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    _release_train_snapshot as _release_train_snapshot,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    admin_autonomy_audit_cross_tier as admin_autonomy_audit_cross_tier,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    admin_autonomy_cross_tier_gate as admin_autonomy_cross_tier_gate,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    admin_autonomy_deploy_events as admin_autonomy_deploy_events,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    admin_autonomy_github_items as admin_autonomy_github_items,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    admin_autonomy_health as admin_autonomy_health,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    admin_autonomy_operating_metrics as admin_autonomy_operating_metrics,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    admin_autonomy_overview as admin_autonomy_overview,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    admin_force_self_maintenance_run as admin_force_self_maintenance_run,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    admin_pending_autonomy_actions as admin_pending_autonomy_actions,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    admin_reject_autonomy_action as admin_reject_autonomy_action,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    admin_resume_autonomy_action as admin_resume_autonomy_action,
)
from app.fastapi_routes.xcmax_admin_part01 import (
    autonomy_audit_log as autonomy_audit_log,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    _clean_string_list as _clean_string_list,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    _collect_employee_pack_modules as _collect_employee_pack_modules,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    _collect_mod_modules as _collect_mod_modules,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    _remote_duty_health as _remote_duty_health,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    _self_maintenance_local_or_proxy as _self_maintenance_local_or_proxy,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    _truthy as _truthy,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_activate_enterprise_impersonation as admin_activate_enterprise_impersonation,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_bind_user_mod as admin_bind_user_mod,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_create_market_user as admin_create_market_user,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_credit_user_wallet as admin_credit_user_wallet,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_force_push_user_entitlements as admin_force_push_user_entitlements,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_list_assignable_mods as admin_list_assignable_mods,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_list_market_users as admin_list_market_users,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_list_orders as admin_list_orders,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_list_user_mods as admin_list_user_mods,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_list_user_profiles as admin_list_user_profiles,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_list_wallets as admin_list_wallets,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_set_user_admin as admin_set_user_admin,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_set_user_enterprise as admin_set_user_enterprise,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_set_user_profile as admin_set_user_profile,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_start_impersonate as admin_start_impersonate,
)
from app.fastapi_routes.xcmax_admin_part02 import (
    admin_unbind_user_mod as admin_unbind_user_mod,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    _inject_digest_api_base as _inject_digest_api_base,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    _probe_remote_health_sync as _probe_remote_health_sync,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    action_items_stats as action_items_stats,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    admin_deploy_check as admin_deploy_check,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    admin_deploy_job as admin_deploy_job,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    admin_deploy_push as admin_deploy_push,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    admin_end_impersonate as admin_end_impersonate,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    get_all_hands_report_session as get_all_hands_report_session,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    get_daily_digest as get_daily_digest,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    get_daily_digest_artifacts as get_daily_digest_artifacts,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    get_digest_identity as get_digest_identity,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    get_digest_vibe_prep_session as get_digest_vibe_prep_session,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    get_release_train as get_release_train,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    list_action_items as list_action_items,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    list_daily_digests as list_daily_digests,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    list_modules as list_modules,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    local_duty_graph_health as local_duty_graph_health,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    local_employee_cron_job_run as local_employee_cron_job_run,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    local_employee_cron_jobs as local_employee_cron_jobs,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    local_employee_execute as local_employee_execute,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    local_employee_manifest as local_employee_manifest,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    local_employee_runs as local_employee_runs,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    local_employee_status as local_employee_status,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    local_self_maintenance_governance_review as local_self_maintenance_governance_review,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    local_self_maintenance_status as local_self_maintenance_status,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    ops_dispatch as ops_dispatch,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    ops_duty_health as ops_duty_health,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    ops_job_detail as ops_job_detail,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    ops_jobs as ops_jobs,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    remote_status as remote_status,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    start_all_hands_report_session as start_all_hands_report_session,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    start_digest_line_execute as start_digest_line_execute,
)
from app.fastapi_routes.xcmax_admin_part03 import (
    start_digest_vibe_prep_session as start_digest_vibe_prep_session,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    _collect_cursor_usage as _collect_cursor_usage,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    _collect_local_ledger as _collect_local_ledger,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    _register_market_proxy_method as _register_market_proxy_method,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    _sync_sse_generator as _sync_sse_generator,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    _to_float as _to_float,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    _to_int as _to_int,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    _xcmax_market_proxy_impl as _xcmax_market_proxy_impl,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    list_conflicts as list_conflicts,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    ops_closure_status as ops_closure_status,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    ops_duty_run_detail as ops_duty_run_detail,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    ops_duty_runs as ops_duty_runs,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    ops_runtime_inventory as ops_runtime_inventory,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    ops_staffing_close_gap as ops_staffing_close_gap,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    ops_staffing_install_local as ops_staffing_install_local,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    ops_staffing_onboard as ops_staffing_onboard,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    resolve_conflict as resolve_conflict,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    sync_changes as sync_changes,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    sync_current_entitlements as sync_current_entitlements,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    sync_pull as sync_pull,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    sync_push as sync_push,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    sync_receive as sync_receive,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    sync_status as sync_status,
)
from app.fastapi_routes.xcmax_admin_part04 import (
    sync_stream as sync_stream,
)
from app.fastapi_routes.xcmax_admin_part05 import (
    _build_token_usage_summary as _build_token_usage_summary,
)
from app.fastapi_routes.xcmax_admin_part05 import (
    _collect_codex_usage as _collect_codex_usage,
)
from app.fastapi_routes.xcmax_admin_part05 import (
    _collect_mimo_usage as _collect_mimo_usage,
)
from app.fastapi_routes.xcmax_admin_part05 import (
    _collect_trae_usage as _collect_trae_usage,
)
from app.fastapi_routes.xcmax_admin_part05 import (
    _estimate_cost_usd as _estimate_cost_usd,
)
from app.fastapi_routes.xcmax_admin_part05 import (
    admin_token_usage as admin_token_usage,
)

# ruff: noqa: F401

CORE_MODULES = [{'module_id': 'xcmax-admin', 'display_name': '服务器后台', 'route': '/xcmax-admin', 'source': 'core', 'sync_scope': 'system', 'active': True, 'version': '1.0'}, {'module_id': 'chat', 'display_name': '智能对话', 'route': '/', 'source': 'core', 'sync_scope': 'none', 'active': True, 'version': '1.0'}, {'module_id': 'ai-ecosystem', 'display_name': '智能生态', 'route': '/ai-ecosystem', 'source': 'core', 'sync_scope': 'none', 'active': True, 'version': '1.0'}, {'module_id': 'model-payment', 'display_name': '模型服务', 'route': '/model-payment', 'source': 'core', 'sync_scope': 'none', 'active': True, 'version': '1.0'}, {'module_id': 'products', 'display_name': '人员管理', 'route': '/products', 'source': 'core', 'sync_scope': 'personnel,departments', 'active': True, 'version': '1.0'}, {'module_id': 'materials-list', 'display_name': '班次列表', 'route': '/materials-list', 'source': 'core', 'sync_scope': 'materials', 'active': True, 'version': '1.0'}, {'module_id': 'materials', 'display_name': '排班资源', 'route': '/materials', 'source': 'core', 'sync_scope': 'materials', 'active': True, 'version': '1.0'}, {'module_id': 'server-functions', 'display_name': '服务器功能模块', 'route': '/server-functions', 'source': 'core', 'sync_scope': 'server,digest,all_hands', 'active': True, 'version': '1.0'}, {'module_id': 'traditional-mode', 'display_name': '表格模式', 'route': '/traditional-mode', 'source': 'core', 'sync_scope': 'none', 'active': True, 'version': '1.0'}, {'module_id': 'business-docking', 'display_name': '数据对接中心', 'route': '/business-docking', 'source': 'core', 'sync_scope': 'none', 'active': True, 'version': '1.0'}, {'module_id': 'orders', 'display_name': '考勤单管理', 'route': '/orders', 'source': 'core', 'sync_scope': 'orders', 'active': True, 'version': '1.0'}, {'module_id': 'shipment-records', 'display_name': '考勤记录', 'route': '/shipment-records', 'source': 'core', 'sync_scope': 'attendance', 'active': True, 'version': '1.0'}, {'module_id': 'customers', 'display_name': '部门管理', 'route': '/customers', 'source': 'core', 'sync_scope': 'departments', 'active': True, 'version': '1.0'}, {'module_id': 'data-sources', 'display_name': '数据来源', 'route': '/data-sources', 'source': 'core', 'sync_scope': 'none', 'active': True, 'version': '1.0'}, {'module_id': 'print', 'display_name': '考勤表打印', 'route': '/print', 'source': 'core', 'sync_scope': 'templates', 'active': True, 'version': '1.0'}, {'module_id': 'printer-list', 'display_name': '打印机列表', 'route': '/printer-list', 'source': 'core', 'sync_scope': 'none', 'active': True, 'version': '1.0'}, {'module_id': 'template-preview', 'display_name': '模板库', 'route': '/template-preview', 'source': 'core', 'sync_scope': 'templates', 'active': True, 'version': '1.0'}, {'module_id': 'settings', 'display_name': '系统设置', 'route': '/settings', 'source': 'core', 'sync_scope': 'system', 'active': True, 'version': '1.0'}, {'module_id': 'tools', 'display_name': '工具表', 'route': '/tools', 'source': 'core', 'sync_scope': 'none', 'active': True, 'version': '1.0'}, {'module_id': 'approval-hub', 'display_name': '审批中心', 'route': '/approval-hub', 'source': 'core', 'sync_scope': 'approvals', 'active': True, 'version': '1.0'}, {'module_id': 'other-tools', 'display_name': '员工工作流', 'route': '/other-tools', 'source': 'core', 'sync_scope': 'none', 'active': True, 'version': '1.0'}]

_VALID_TIERS = {'personal', 'enterprise', 'admin'}

SYNC_POLL_INTERVAL_S = float(os.environ.get('XCMAX_SYNC_POLL_S', '10'))

for _market_proxy_method in ('GET', 'POST', 'PUT', 'DELETE', 'PATCH'):
    _register_market_proxy_method(_market_proxy_method)
