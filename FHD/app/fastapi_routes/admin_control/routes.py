"""Explicit HTTP contract, kept separate from application workflows."""

from collections.abc import Callable, Iterable
from typing import Any

from fastapi import APIRouter, Depends

from app.fastapi_routes.xcmax_sync_peer_auth import require_sync_peer

from .autonomy import AutonomyAdmin
from .catalog import ModuleCatalog
from .customer_tickets import CustomerTickets
from .deployment import Deployment
from .digest import DigestReader
from .employee_execution import EmployeeExecution
from .employees import LocalEmployees
from .entitlements import AccountEntitlements
from .health import RemoteHealth
from .impersonation import Impersonation
from .maintenance import SelfMaintenance
from .market_accounts import MarketAccounts
from .market_gateway import MarketGateway
from .operations import Operations
from .profiles import UserProfiles
from .synchronization import Synchronization
from .usage_sources import UsageSources
from .usage_summary import UsageSummary


def _register(router: APIRouter, routes: Iterable[tuple[str, str, Callable[..., Any]]]) -> None:
    for path, method, endpoint in routes:
        router.add_api_route(path, endpoint, methods=[method], response_model=None)


def register_routes(
    router: APIRouter,
    *,
    autonomy: AutonomyAdmin,
    market_gateway: MarketGateway,
    digest: DigestReader,
    maintenance: SelfMaintenance,
    catalog: ModuleCatalog,
    profiles: UserProfiles,
    entitlements: AccountEntitlements,
    impersonation: Impersonation,
    employee_execution: EmployeeExecution,
    employees: LocalEmployees,
    deployment: Deployment,
    health: RemoteHealth,
    operations: Operations,
    synchronization: Synchronization,
    customer_tickets: CustomerTickets,
    usage_sources: UsageSources,
    usage_summary: UsageSummary,
    market_accounts: MarketAccounts,
) -> None:
    _register(
        router,
        (
            ("/admin/autonomy/audit-log", "GET", autonomy.autonomy_audit_log),
            ("/admin/autonomy/actions/pending", "GET", autonomy.admin_pending_autonomy_actions),
            (
                "/admin/autonomy/actions/{action_id}/resume",
                "POST",
                autonomy.admin_resume_autonomy_action,
            ),
            (
                "/admin/autonomy/actions/{action_id}/reject",
                "POST",
                autonomy.admin_reject_autonomy_action,
            ),
            ("/admin/autonomy/health", "GET", autonomy.admin_autonomy_health),
            ("/admin/autonomy/overview", "GET", autonomy.admin_autonomy_overview),
            ("/admin/autonomy/deploy-events", "GET", autonomy.admin_autonomy_deploy_events),
            ("/admin/autonomy/operating-metrics", "GET", autonomy.admin_autonomy_operating_metrics),
            ("/admin/autonomy/github-items", "GET", autonomy.admin_autonomy_github_items),
            ("/admin/autonomy/cross-tier-gate", "GET", autonomy.admin_autonomy_cross_tier_gate),
            ("/admin/autonomy/audit-cross-tier", "GET", autonomy.admin_autonomy_audit_cross_tier),
            (
                "/admin/autonomy/self-maintenance/run",
                "POST",
                autonomy.admin_force_self_maintenance_run,
            ),
            ("/admin/market/users", "GET", market_accounts.admin_list_market_users),
            ("/admin/market/users", "POST", market_accounts.admin_create_market_user),
            ("/admin/market/assignable-mods", "GET", market_accounts.admin_list_assignable_mods),
            ("/admin/market/wallets", "GET", market_accounts.admin_list_wallets),
            ("/admin/market/orders", "GET", market_accounts.admin_list_orders),
            ("/admin/market/commerce/orders", "GET", market_accounts.admin_list_commerce_orders),
            (
                "/admin/market/commerce/orders/{order_no}/{action}",
                "POST",
                market_accounts.admin_mutate_commerce_order,
            ),
            (
                "/admin/market/commerce/refunds/pending",
                "GET",
                market_accounts.admin_list_pending_commerce_refunds,
            ),
            (
                "/admin/market/commerce/refunds/{refund_id}/review",
                "POST",
                market_accounts.admin_review_commerce_refund,
            ),
            (
                "/admin/customer-deliveries/standard",
                "GET",
                market_accounts.admin_list_standard_customer_deliveries,
            ),
            (
                "/admin/market/entitlement-fast-lane/plans",
                "GET",
                market_accounts.admin_list_entitlement_fast_lane_plans,
            ),
            (
                "/admin/market/entitlement-fast-lane/accounts/{account}",
                "GET",
                market_accounts.admin_get_entitlement_fast_lane_account,
            ),
            (
                "/admin/market/entitlement-fast-lane/actions",
                "POST",
                market_accounts.admin_mutate_entitlement_fast_lane,
            ),
            (
                "/admin/deploy/install-receipts",
                "GET",
                market_accounts.admin_list_update_install_receipts,
            ),
            (
                "/admin/market/users/{user_id}/wallet/credit",
                "POST",
                market_accounts.admin_credit_user_wallet,
            ),
            ("/admin/market/users/{user_id}/mods", "GET", market_accounts.admin_list_user_mods),
            (
                "/admin/market/users/{user_id}/mods/{mod_id}",
                "POST",
                market_accounts.admin_bind_user_mod,
            ),
            (
                "/admin/market/users/{user_id}/mods/{mod_id}",
                "DELETE",
                market_accounts.admin_unbind_user_mod,
            ),
            ("/admin/market/users/{user_id}/admin", "PUT", market_accounts.admin_set_user_admin),
            (
                "/admin/market/users/{user_id}/enterprise",
                "PUT",
                market_accounts.admin_set_user_enterprise,
            ),
            ("/admin/users/{user_id}/profile", "PUT", profiles.admin_set_user_profile),
            ("/admin/users/profiles", "GET", profiles.admin_list_user_profiles),
            (
                "/admin/market/users/{user_id}/entitlements/push",
                "POST",
                entitlements.admin_force_push_user_entitlements,
            ),
            ("/admin/impersonate", "POST", impersonation.admin_start_impersonate),
            (
                "/admin/customer-deliveries/trial",
                "GET",
                market_accounts.admin_list_trial_customer_deliveries,
            ),
            (
                "/admin/impersonate/activate-enterprise",
                "POST",
                impersonation.admin_activate_enterprise_impersonation,
            ),
            ("/admin/impersonate/end", "POST", impersonation.admin_end_impersonate),
            ("/admin/digest-identity", "GET", digest.get_digest_identity),
            ("/release-train", "GET", catalog.get_release_train),
            ("/local/duty-graph/health", "GET", employees.local_duty_graph_health),
            (
                "/local/ops/self-maintenance/status",
                "GET",
                maintenance.local_self_maintenance_status,
            ),
            (
                "/local/ops/self-maintenance/governance-review",
                "POST",
                maintenance.local_self_maintenance_governance_review,
            ),
            ("/local/employee-cron/jobs", "GET", employees.local_employee_cron_jobs),
            (
                "/local/employee-cron/jobs/{job_id}/run",
                "POST",
                employees.local_employee_cron_job_run,
            ),
            ("/local/employees/{employee_id}/status", "GET", employees.local_employee_status),
            (
                "/local/employees/{employee_id}/execute",
                "POST",
                employee_execution.local_employee_execute,
            ),
            ("/local/employees/{employee_id}/runs", "GET", employee_execution.local_employee_runs),
            ("/local/employees/{employee_id}/manifest", "GET", employees.local_employee_manifest),
            ("/admin/modules", "GET", catalog.list_modules),
            ("/admin/daily-digests", "GET", digest.list_daily_digests),
            ("/admin/daily-digests/{record_id}", "GET", digest.get_daily_digest),
            (
                "/admin/daily-digests/{record_id}/artifacts",
                "GET",
                digest.get_daily_digest_artifacts,
            ),
            ("/admin/action-items", "GET", digest.list_action_items),
            ("/admin/action-items/stats", "GET", digest.action_items_stats),
            (
                "/admin/daily-digests/{record_id}/vibe-prep/sessions",
                "POST",
                digest.start_digest_vibe_prep_session,
            ),
            (
                "/admin/daily-digests/{record_id}/line-execute",
                "POST",
                digest.start_digest_line_execute,
            ),
            (
                "/admin/digest-vibe-prep/sessions/{session_id}",
                "GET",
                digest.get_digest_vibe_prep_session,
            ),
            ("/admin/all-hands-report/sessions", "POST", digest.start_all_hands_report_session),
            (
                "/admin/all-hands-report/sessions/{session_id}",
                "GET",
                digest.get_all_hands_report_session,
            ),
            ("/admin/remote-status", "GET", health.remote_status),
            ("/admin/deploy/check", "GET", deployment.admin_deploy_check),
            ("/admin/deploy/push", "POST", deployment.admin_deploy_push),
            ("/admin/deploy/jobs/{job_id}", "GET", deployment.admin_deploy_job),
            ("/ops/duty-health", "GET", operations.ops_duty_health),
            ("/ops/dispatch", "POST", operations.ops_dispatch),
            ("/ops/jobs", "GET", operations.ops_jobs),
            ("/ops/jobs/{job_id}", "GET", operations.ops_job_detail),
            ("/ops/duty-runs", "POST", operations.ops_duty_runs),
            ("/ops/duty-runs/{run_id}", "GET", operations.ops_duty_run_detail),
            ("/ops/closure-status", "GET", operations.ops_closure_status),
            ("/ops/runtime-inventory", "GET", operations.ops_runtime_inventory),
            ("/ops/staffing/onboard", "POST", operations.ops_staffing_onboard),
            ("/ops/staffing/install-local", "POST", operations.ops_staffing_install_local),
            ("/ops/staffing/close-gap", "POST", operations.ops_staffing_close_gap),
            ("/sync/status", "GET", synchronization.sync_status),
            ("/sync/push", "POST", synchronization.sync_push),
            ("/sync/changes", "GET", synchronization.sync_changes),
        ),
    )
    router.add_api_route(
        "/sync/receive",
        synchronization.sync_receive,
        methods=["POST"],
        response_model=None,
        dependencies=[Depends(require_sync_peer)],
    )
    _register(
        router,
        (
            ("/sync/pull", "POST", synchronization.sync_pull),
            ("/sync/entitlements/current", "GET", entitlements.sync_current_entitlements),
            ("/sync/conflicts", "GET", synchronization.list_conflicts),
            ("/sync/conflicts/{inbox_id}/resolve", "POST", synchronization.resolve_conflict),
            ("/sync/stream", "GET", synchronization.sync_stream),
            (
                "/admin/customer-service/tickets",
                "GET",
                customer_tickets.admin_customer_service_tickets,
            ),
            (
                "/admin/customer-service/tickets/{ticket_id}",
                "GET",
                customer_tickets.admin_customer_service_ticket,
            ),
            (
                "/admin/customer-service/tickets/{ticket_id}/close",
                "POST",
                customer_tickets.close_admin_customer_service_ticket,
            ),
            (
                "/admin/customer-service/tickets/{ticket_id}/expected-completion",
                "PATCH",
                customer_tickets.admin_update_customer_ticket_expected_completion,
            ),
            ("/admin/token-usage", "GET", usage_summary.admin_token_usage),
        ),
    )
