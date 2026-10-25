"""XCmax admin HTTP composition and stable patchable entry points."""

from __future__ import annotations

import asyncio as asyncio
import json as json
import logging
import os
import time as time
import urllib.request
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from fastapi import APIRouter, Request

from app.fastapi_routes.mac_control_proxy import router as mac_control_router
from app.fastapi_routes.xcmax_admin_auth import (
    admin_approver_from_session as _admin_approver_from_session,
)
from app.fastapi_routes.xcmax_admin_auth import (
    require_market_admin_session as _require_market_admin_session,
)
from app.fastapi_routes.xcmax_admin_core_modules import CORE_MODULES as CORE_MODULES
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .admin_control.autonomy import AutonomyAdmin
from .admin_control.backends import (
    load_market_transport,
    open_sync_store,
    refresh_impersonation_entitlements,
)
from .admin_control.catalog import ModuleCatalog
from .admin_control.customer_tickets import CustomerTickets
from .admin_control.deployment import Deployment
from .admin_control.digest import DigestReader
from .admin_control.employee_backend import CanonicalEmployeeBackend, employee_identity
from .admin_control.employee_execution import EmployeeExecution
from .admin_control.employee_run import EmployeeRunner
from .admin_control.employees import LocalEmployees
from .admin_control.entitlements import AccountEntitlements
from .admin_control.health import RemoteHealth
from .admin_control.impersonation import Impersonation
from .admin_control.maintenance import SelfMaintenance
from .admin_control.market_accounts import MarketAccounts
from .admin_control.market_gateway import MarketGateway
from .admin_control.operations import Operations
from .admin_control.port_contracts import ErrorPolicy, JsonObject, LocalProxy, MarketProxy
from .admin_control.profile_store import profile_repository
from .admin_control.profiles import UserProfiles
from .admin_control.routes import register_routes
from .admin_control.synchronization import Synchronization
from .admin_control.usage_sources import UsageSources
from .admin_control.usage_summary import UsageSummary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/xcmax", tags=["xcmax-admin"])
router.include_router(mac_control_router)
REMOTE_HOST = os.environ.get("XCMAX_REMOTE_HOST", "119.27.178.147")
REMOTE_PORT = int(os.environ.get("XCMAX_REMOTE_PORT", "9999"))
_DEFAULT_URLOPEN = urllib.request.urlopen
_VALID_TIERS = {"personal", "enterprise", "admin"}
SYNC_POLL_INTERVAL_S = float(os.environ.get("XCMAX_SYNC_POLL_S", "10"))
_errors = ErrorPolicy(lambda: RECOVERABLE_ERRORS, logger)

_autonomy = AutonomyAdmin(
    errors=_errors,
    gate=lambda request: _require_market_admin_session(request),
    approver=lambda request: _admin_approver_from_session(request),
    duty_health=lambda request: _remote_duty_health(request),
)
autonomy_audit_log = _autonomy.autonomy_audit_log
admin_pending_autonomy_actions = _autonomy.admin_pending_autonomy_actions
admin_resume_autonomy_action = _autonomy.admin_resume_autonomy_action
admin_reject_autonomy_action = _autonomy.admin_reject_autonomy_action
admin_autonomy_health = _autonomy.admin_autonomy_health
admin_autonomy_overview = _autonomy.admin_autonomy_overview
admin_autonomy_deploy_events = _autonomy.admin_autonomy_deploy_events
admin_autonomy_operating_metrics = _autonomy.admin_autonomy_operating_metrics
admin_autonomy_github_items = _autonomy.admin_autonomy_github_items
admin_autonomy_cross_tier_gate = _autonomy.admin_autonomy_cross_tier_gate
admin_autonomy_audit_cross_tier = _autonomy.admin_autonomy_audit_cross_tier
admin_force_self_maintenance_run = _autonomy.admin_force_self_maintenance_run

_market_gateway = MarketGateway(
    transport=load_market_transport,
    errors=_errors,
    gate=lambda request: _require_market_admin_session(request),
    proxy=lambda request, method, path, **kwargs: _market_admin_proxy(
        request, method, path, **kwargs
    ),
    maintenance=lambda request, method, path, **kwargs: _self_maintenance_local_or_proxy(
        request, method, path, **kwargs
    ),
)
_market_admin_proxy: MarketProxy = _market_gateway._market_admin_proxy
_xcmax_market_proxy_impl = _market_gateway._xcmax_market_proxy_impl

_digest = DigestReader(
    errors=_errors,
    digest_nonempty=lambda payload: _digest_payload_nonempty(payload),
    digest_record_id=lambda path: _digest_record_id_from_path(path),
    remote_digest=lambda path: _fetch_remote_xcmax_daily_digests(path),
    is_daily_digest_artifacts_path=lambda path: _is_daily_digest_artifacts_path(path),
    is_daily_digest_detail_path=lambda path: _is_daily_digest_detail_path(path),
    is_daily_digest_list_path=lambda path: _is_daily_digest_list_path(path),
    proxy=lambda request, method, path, **kwargs: _market_admin_proxy(
        request, method, path, **kwargs
    ),
    gate=lambda request: _require_market_admin_session(request),
    inject_digest_base=lambda payload, base: _inject_digest_api_base(payload, base),
    read_digest=lambda request, method, path, **kwargs: _digest_local_or_proxy(
        request, method, path, **kwargs
    ),
)
_is_daily_digest_list_path: Callable[[str], bool] = _digest._is_daily_digest_list_path
_is_daily_digest_detail_path: Callable[[str], bool] = _digest._is_daily_digest_detail_path
_is_daily_digest_artifacts_path: Callable[[str], bool] = _digest._is_daily_digest_artifacts_path
_digest_record_id_from_path: Callable[[str], int] = _digest._digest_record_id_from_path
_fetch_remote_xcmax_daily_digests: Callable[[str], Awaitable[JsonObject | None]] = (
    _digest._fetch_remote_xcmax_daily_digests
)
_digest_payload_nonempty: Callable[[object], bool] = _digest._digest_payload_nonempty
_digest_local_or_proxy: LocalProxy = _digest._digest_local_or_proxy
_inject_digest_api_base: Callable[[JsonObject, str], JsonObject] = _digest._inject_digest_api_base
get_digest_identity = _digest.get_digest_identity
list_daily_digests = _digest.list_daily_digests
get_daily_digest = _digest.get_daily_digest
get_daily_digest_artifacts = _digest.get_daily_digest_artifacts
list_action_items = _digest.list_action_items
action_items_stats = _digest.action_items_stats
start_digest_vibe_prep_session = _digest.start_digest_vibe_prep_session
start_digest_line_execute = _digest.start_digest_line_execute
get_digest_vibe_prep_session = _digest.get_digest_vibe_prep_session
start_all_hands_report_session = _digest.start_all_hands_report_session
get_all_hands_report_session = _digest.get_all_hands_report_session

_maintenance = SelfMaintenance(
    errors=_errors,
    proxy=lambda request, method, path, **kwargs: _market_admin_proxy(
        request, method, path, **kwargs
    ),
)
_self_maintenance_local_or_proxy: LocalProxy = _maintenance._self_maintenance_local_or_proxy
local_self_maintenance_status = _maintenance.local_self_maintenance_status
local_self_maintenance_governance_review = _maintenance.local_self_maintenance_governance_review

_catalog = ModuleCatalog(
    errors=_errors,
    release_train_snapshot=lambda: _release_train_snapshot(),
    core_modules=lambda: CORE_MODULES,
    collect_employee_pack_modules=lambda: _collect_employee_pack_modules(),
    collect_mod_modules=lambda: _collect_mod_modules(),
    config_root=lambda: Path(__file__).resolve().parents[2],
)
_release_train_snapshot: Callable[[], JsonObject] = _catalog._release_train_snapshot
get_release_train = _catalog.get_release_train
_collect_mod_modules: Callable[[], list[JsonObject]] = _catalog._collect_mod_modules
_collect_employee_pack_modules: Callable[[], list[JsonObject]] = (
    _catalog._collect_employee_pack_modules
)
list_modules = _catalog.list_modules

_profiles = UserProfiles(
    repository=profile_repository,
    errors=_errors,
    valid_tiers=lambda: _VALID_TIERS,
    gate=lambda request: _require_market_admin_session(request),
)
admin_set_user_profile = _profiles.admin_set_user_profile
admin_list_user_profiles = _profiles.admin_list_user_profiles

_entitlements = AccountEntitlements(
    errors=_errors,
    remote_host=lambda: REMOTE_HOST,
    remote_port=lambda: REMOTE_PORT,
    valid_tiers=lambda: _VALID_TIERS,
    clean_strings=lambda value: _clean_string_list(value),
    gate=lambda request: _require_market_admin_session(request),
    truthy=lambda value: _truthy(value),
)
_clean_string_list: Callable[[object], list[str]] = _entitlements._clean_string_list
_truthy: Callable[[object], bool] = _entitlements._truthy
admin_force_push_user_entitlements = _entitlements.admin_force_push_user_entitlements
sync_current_entitlements = _entitlements.sync_current_entitlements

_impersonation = Impersonation(
    refresh_entitlements=refresh_impersonation_entitlements,
    errors=_errors,
    gate=lambda request: _require_market_admin_session(request),
)
admin_start_impersonate = _impersonation.admin_start_impersonate
admin_activate_enterprise_impersonation = _impersonation.admin_activate_enterprise_impersonation
admin_end_impersonate = _impersonation.admin_end_impersonate

_employee_execution = EmployeeExecution(
    identity=employee_identity,
    run=EmployeeRunner(CanonicalEmployeeBackend()).run,
    errors=_errors,
)
local_employee_execute = _employee_execution.local_employee_execute
local_employee_runs = _employee_execution.local_employee_runs

_employees = LocalEmployees(
    errors=_errors,
)
local_duty_graph_health = _employees.local_duty_graph_health
local_employee_cron_jobs = _employees.local_employee_cron_jobs
local_employee_cron_job_run = _employees.local_employee_cron_job_run
local_employee_status = _employees.local_employee_status
local_employee_manifest = _employees.local_employee_manifest

_deployment = Deployment(
    errors=_errors,
    gate=lambda request: _require_market_admin_session(request),
)
admin_deploy_check = _deployment.admin_deploy_check
admin_deploy_push = _deployment.admin_deploy_push
admin_deploy_job = _deployment.admin_deploy_job

_health = RemoteHealth(
    errors=_errors,
    remote_host=lambda: REMOTE_HOST,
    remote_port=lambda: REMOTE_PORT,
    default_urlopen=lambda: _DEFAULT_URLOPEN,
    probe_remote_health_sync=lambda: _probe_remote_health_sync(),
)
_probe_remote_health_sync: Callable[[], JsonObject] = _health._probe_remote_health_sync
remote_status = _health.remote_status

_operations = Operations(
    errors=_errors,
    proxy=lambda request, method, path, **kwargs: _market_admin_proxy(
        request, method, path, **kwargs
    ),
    duty_health=lambda request: _remote_duty_health(request),
    gate=lambda request: _require_market_admin_session(request),
)
_remote_duty_health: Callable[[Request], Awaitable[JsonObject]] = _operations._remote_duty_health
ops_duty_health = _operations.ops_duty_health
ops_dispatch = _operations.ops_dispatch
ops_jobs = _operations.ops_jobs
ops_job_detail = _operations.ops_job_detail
ops_duty_runs = _operations.ops_duty_runs
ops_duty_run_detail = _operations.ops_duty_run_detail
ops_closure_status = _operations.ops_closure_status
ops_runtime_inventory = _operations.ops_runtime_inventory
ops_staffing_onboard = _operations.ops_staffing_onboard
ops_staffing_install_local = _operations.ops_staffing_install_local
ops_staffing_close_gap = _operations.ops_staffing_close_gap

_synchronization = Synchronization(
    store=open_sync_store,
    errors=_errors,
    poll_interval=lambda: SYNC_POLL_INTERVAL_S,
    remote_host=lambda: REMOTE_HOST,
    remote_port=lambda: REMOTE_PORT,
    stream=lambda request, since_cursor: _sync_sse_generator(request, since_cursor),
)
_sync_sse_generator: Callable[[Request, int], AsyncIterator[str]] = (
    _synchronization._sync_sse_generator
)
sync_status = _synchronization.sync_status
sync_push = _synchronization.sync_push
sync_changes = _synchronization.sync_changes
sync_receive = _synchronization.sync_receive
sync_pull = _synchronization.sync_pull
list_conflicts = _synchronization.list_conflicts
resolve_conflict = _synchronization.resolve_conflict
sync_stream = _synchronization.sync_stream

_customer_tickets = CustomerTickets(
    errors=_errors,
    proxy=lambda request, method, path, **kwargs: _market_admin_proxy(
        request, method, path, **kwargs
    ),
    gate=lambda request: _require_market_admin_session(request),
)

_usage_sources = UsageSources(
    errors=_errors,
    to_float=lambda value: _to_float(value),
    to_int=lambda value: _to_int(value),
)
_to_int: Callable[[object], int] = _usage_sources._to_int
_to_float: Callable[[object], float] = _usage_sources._to_float
_collect_local_ledger: Callable[[], JsonObject] = _usage_sources._collect_local_ledger
_collect_cursor_usage: Callable[[], JsonObject] = _usage_sources._collect_cursor_usage
_collect_codex_usage: Callable[[], JsonObject] = _usage_sources._collect_codex_usage
_collect_trae_usage: Callable[[], JsonObject] = _usage_sources._collect_trae_usage
_collect_mimo_usage: Callable[[], JsonObject] = _usage_sources._collect_mimo_usage

_usage_summary = UsageSummary(
    errors=_errors,
    to_int=lambda value: _to_int(value),
    collect_codex_usage=lambda: _collect_codex_usage(),
    collect_cursor_usage=lambda: _collect_cursor_usage(),
    collect_local_ledger=lambda: _collect_local_ledger(),
    collect_mimo_usage=lambda: _collect_mimo_usage(),
    collect_trae_usage=lambda: _collect_trae_usage(),
    estimate_cost=lambda key, data: _estimate_cost_usd(key, data),
    build_token_usage_summary=lambda: _build_token_usage_summary(),
)
_estimate_cost_usd: Callable[[str, JsonObject], float] = _usage_summary._estimate_cost_usd
_build_token_usage_summary: Callable[[], JsonObject] = _usage_summary._build_token_usage_summary
admin_token_usage = _usage_summary.admin_token_usage

_market_accounts = MarketAccounts(
    errors=_errors,
    proxy=lambda request, method, path, **kwargs: _market_admin_proxy(
        request, method, path, **kwargs
    ),
    gate=lambda request: _require_market_admin_session(request),
)
admin_list_market_users = _market_accounts.admin_list_market_users
admin_create_market_user = _market_accounts.admin_create_market_user
admin_list_assignable_mods = _market_accounts.admin_list_assignable_mods
admin_list_wallets = _market_accounts.admin_list_wallets
admin_list_orders = _market_accounts.admin_list_orders
admin_list_commerce_orders = _market_accounts.admin_list_commerce_orders
admin_mutate_commerce_order = _market_accounts.admin_mutate_commerce_order
admin_list_pending_commerce_refunds = _market_accounts.admin_list_pending_commerce_refunds
admin_review_commerce_refund = _market_accounts.admin_review_commerce_refund
admin_list_update_install_receipts = _market_accounts.admin_list_update_install_receipts
admin_credit_user_wallet = _market_accounts.admin_credit_user_wallet
admin_list_user_mods = _market_accounts.admin_list_user_mods
admin_bind_user_mod = _market_accounts.admin_bind_user_mod
admin_unbind_user_mod = _market_accounts.admin_unbind_user_mod
admin_set_user_admin = _market_accounts.admin_set_user_admin
admin_set_user_enterprise = _market_accounts.admin_set_user_enterprise

register_routes(
    router,
    autonomy=_autonomy,
    market_gateway=_market_gateway,
    digest=_digest,
    maintenance=_maintenance,
    catalog=_catalog,
    profiles=_profiles,
    entitlements=_entitlements,
    impersonation=_impersonation,
    employee_execution=_employee_execution,
    employees=_employees,
    deployment=_deployment,
    health=_health,
    operations=_operations,
    synchronization=_synchronization,
    customer_tickets=_customer_tickets,
    usage_sources=_usage_sources,
    usage_summary=_usage_summary,
    market_accounts=_market_accounts,
)


def _register_market_proxy_method(method: str) -> None:

    async def endpoint(request: Request, subpath: str):
        return await _xcmax_market_proxy_impl(request, subpath)

    endpoint.__name__ = f"xcmax_market_proxy_{method.lower()}"
    endpoint.__qualname__ = endpoint.__name__
    router.add_api_route(
        "/market-proxy/{subpath:path}", endpoint, methods=[method], response_model=None
    )


for _market_proxy_method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
    _register_market_proxy_method(_market_proxy_method)
