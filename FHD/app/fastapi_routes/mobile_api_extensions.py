"""移动端 API 扩展：代理列表、设备注册、QR 配对。

本模块为路由处理入口，纯计算辅助函数与模型已按业务领域拆分至
``mobile_extensions`` 子包。为保证向后兼容（测试 patch / 直接调用），
所有公共符号均在此重新导出。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

# ── 测试 patch / mext 代理用 re-export（子路由经 mext 回引本模块符号）──
from app.application.ai_group_chat_service import AiGroupChatService as AiGroupChatService
from app.application.claude_super_employee_service import (
    ClaudeSuperEmployeeService as ClaudeSuperEmployeeService,
)
from app.application.codex_super_employee_service import (
    CodexSuperEmployeeService as CodexSuperEmployeeService,
)
from app.application.cursor_super_employee_service import (
    CursorSuperEmployeeService as CursorSuperEmployeeService,
)
from app.application.execution_scope import factory_context as factory_context
from app.application.facades.mobile_relay_facade import MobileRelayService as MobileRelayService
from app.application.trae_super_employee_service import (
    TraeSuperEmployeeService as TraeSuperEmployeeService,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _admin_employee_match_keys as _admin_employee_match_keys,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _apply_market_profile as _apply_market_profile,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _compact_text as _compact_text,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _enrich_workflow_employees as _enrich_workflow_employees,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _index_market_ai_employee_profiles as _index_market_ai_employee_profiles,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _load_admin_duty_records as _load_admin_duty_records,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _load_market_ai_employee_profile_index as _load_market_ai_employee_profile_index,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _mobile_request_user_id as _mobile_request_user_id,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _mobile_session_meta as _mobile_session_meta,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _require_mobile_admin as _require_mobile_admin,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _require_mobile_admin_or_enterprise as _require_mobile_admin_or_enterprise,
)
from app.fastapi_routes.mobile_extensions.constants import (
    ADMIN_MOBILE_FEATURES as ADMIN_MOBILE_FEATURES,
)
from app.fastapi_routes.mobile_extensions.cs_helpers import (
    _mobile_cs_source_id as _mobile_cs_source_id,
)
from app.fastapi_routes.mobile_extensions.cs_helpers import (
    _mobile_cs_source_name as _mobile_cs_source_name,
)
from app.fastapi_routes.mobile_extensions.cs_helpers import (
    _safe_user_id as _safe_user_id,
)
from app.fastapi_routes.mobile_extensions.cs_helpers import (
    _safe_user_text as _safe_user_text,
)

# ── 子模块导入 ──
from app.fastapi_routes.mobile_extensions.models import (
    AiCircleCommentBody as AiCircleCommentBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    AiCirclePostBody as AiCirclePostBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    AiGroupCreateBody as AiGroupCreateBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    AiGroupMemberBody as AiGroupMemberBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    AiGroupMessageBody as AiGroupMessageBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    AuthQrConfirmBody as AuthQrConfirmBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    ClaudeSuperEmployeeMobileMessageBody as ClaudeSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    CodexSuperEmployeeMobileMessageBody as CodexSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    CursorSuperEmployeeMobileMessageBody as CursorSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    DeviceRegisterBody as DeviceRegisterBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    MobileServiceBridgeRespondBody as MobileServiceBridgeRespondBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    OidcExchangeBody as OidcExchangeBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    PairingExchangeBody as PairingExchangeBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    PairingIssueBody as PairingIssueBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    PairingLookupBody as PairingLookupBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    RelayDesktopCompleteBody as RelayDesktopCompleteBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    RelayDesktopPollBody as RelayDesktopPollBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    RelayDesktopRegisterBody as RelayDesktopRegisterBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    RelayMobileBindAccountBody as RelayMobileBindAccountBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    RelayTaskCreateBody as RelayTaskCreateBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    SyncAckBody as SyncAckBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    SyncPullBody as SyncPullBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    SyncPushBody as SyncPushBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    SyncPushItem as SyncPushItem,
)
from app.fastapi_routes.mobile_extensions.models import (
    TraeSuperEmployeeMobileMessageBody as TraeSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.pairing_helpers import (
    _enrich_pairing_payload as _enrich_pairing_payload,
)
from app.fastapi_routes.mobile_extensions.pairing_helpers import (
    _guess_lan_ipv4 as _guess_lan_ipv4,
)
from app.fastapi_routes.mobile_extensions.pairing_helpers import (
    _host_is_private_or_loopback as _host_is_private_or_loopback,
)
from app.fastapi_routes.mobile_extensions.pairing_helpers import (
    _pairing_issue_port as _pairing_issue_port,
)
from app.fastapi_routes.mobile_extensions.pairing_helpers import (
    _pairing_reachable_port as _pairing_reachable_port,
)
from app.fastapi_routes.mobile_extensions.relay_helpers import (
    _mobile_user_identity as _mobile_user_identity,
)
from app.fastapi_routes.mobile_extensions.relay_helpers import (
    _mobile_user_public_dict as _mobile_user_public_dict,
)
from app.fastapi_routes.mobile_extensions.relay_helpers import (
    _relay_admin_fallback_user as _relay_admin_fallback_user,
)
from app.fastapi_routes.mobile_extensions.relay_helpers import (
    _relay_mobile_auth_payload as _relay_mobile_auth_payload,
)
from app.security.mobile_pairing import consume_by_shortcode as consume_by_shortcode
from app.security.mobile_pairing import consume_pairing_nonce as consume_pairing_nonce
from app.security.mobile_pairing import issue_pairing_nonce as issue_pairing_nonce
from app.security.mobile_pairing import lookup_by_shortcode as lookup_by_shortcode
from app.utils.operational_errors import RECOVERABLE_ERRORS

OPERATIONAL_ERRORS = RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

extension_router = APIRouter(tags=["mobile-api-ext"])

# ── 共享 helper（实现见 mobile_extensions.core_helpers）──
from app.fastapi_routes.mobile_extensions.business_routes import (  # noqa: E402, I001
    _employee_ssot_payload as _employee_ssot_payload,
)
from app.fastapi_routes.mobile_extensions.business_routes import (
    business_router as business_router,
)
from app.fastapi_routes.mobile_extensions.business_routes import (
    mobile_approval_list as mobile_approval_list,
)
from app.fastapi_routes.mobile_extensions.business_routes import (
    mobile_customers as mobile_customers,
)
from app.fastapi_routes.mobile_extensions.business_routes import (
    mobile_employee_ssot as mobile_employee_ssot,
)
from app.fastapi_routes.mobile_extensions.business_routes import (
    mobile_shipments as mobile_shipments,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (  # noqa: E402
    _admin_duty_mod_item as _admin_duty_mod_item,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _admin_duty_records_from_roster as _admin_duty_records_from_roster,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _admin_employee_items as _admin_employee_items,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _admin_employee_manifest as _admin_employee_manifest,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _admin_roster_area_labels as _admin_roster_area_labels,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _admin_roster_ids_by_department_order as _admin_roster_ids_by_department_order,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _ai_circle_employee_profiles as _ai_circle_employee_profiles,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _ai_circle_user as _ai_circle_user,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _ai_conversation_changes as _ai_conversation_changes,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _approval_items as _approval_items,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _cached_desktop_relay_for_account_binding as _cached_desktop_relay_for_account_binding,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _ensure_mobile_device_table as _ensure_mobile_device_table,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _ensure_outbox_table as _ensure_outbox_table,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _mobile_bridge_request_statuses as _mobile_bridge_request_statuses,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _mobile_market_authorization as _mobile_market_authorization,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _mobile_mod_items as _mobile_mod_items,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _mobile_session_id_from_request as _mobile_session_id_from_request,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _mobile_unauthorized_response as _mobile_unauthorized_response,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _pairing_issue_host as _pairing_issue_host,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _persist_mobile_cs_request as _persist_mobile_cs_request,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _register_desktop_relay_for_pairing as _register_desktop_relay_for_pairing,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _resolve_mobile_relay_user as _resolve_mobile_relay_user,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _safe_mobile_sync_items as _safe_mobile_sync_items,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _shipment_items as _shipment_items,
)
from app.fastapi_routes.mobile_extensions.core_helpers import (
    _upsert_admin_duty_mod_item as _upsert_admin_duty_mod_item,
)

extension_router.include_router(business_router)

# ── 子路由模块（实现见 mobile_extensions.*）──
from app.fastapi_routes.mobile_extensions.device_notify_routes import (  # noqa: E402, I001
    device_notify_router as device_notify_router,
    mobile_device_register as mobile_device_register,
    mobile_device_unregister as mobile_device_unregister,
    mobile_notifications_pending as mobile_notifications_pending,
    mobile_lan_android_update as mobile_lan_android_update,
    mobile_lan_android_update_notify as mobile_lan_android_update_notify,
    _lan_releases_root as _lan_releases_root,
    _lan_public_base_url as _lan_public_base_url,
    _is_loopback_request as _is_loopback_request,
)
extension_router.include_router(device_notify_router)

from app.fastapi_routes.mobile_extensions.relay_pairing_routes import (  # noqa: E402, I001
    relay_pairing_router as relay_pairing_router,
    mobile_pairing_issue as mobile_pairing_issue,
    mobile_pairing_lookup as mobile_pairing_lookup,
    mobile_pairing_exchange as mobile_pairing_exchange,
    mobile_service_bridge_requests as mobile_service_bridge_requests,
    mobile_service_bridge_request_respond as mobile_service_bridge_request_respond,
    mobile_relay_desktop_register as mobile_relay_desktop_register,
    mobile_relay_bind_account as mobile_relay_bind_account,
    mobile_relay_desktops as mobile_relay_desktops,
    mobile_relay_create_task as mobile_relay_create_task,
    mobile_relay_task_status as mobile_relay_task_status,
    mobile_relay_task_cancel as mobile_relay_task_cancel,
    mobile_relay_desktop_poll as mobile_relay_desktop_poll,
    mobile_relay_desktop_complete as mobile_relay_desktop_complete,
)
extension_router.include_router(relay_pairing_router)

from app.fastapi_routes.mobile_extensions.admin_mobile_routes import (  # noqa: E402, I001
    admin_mobile_router as admin_mobile_router,
    mobile_admin_employees as mobile_admin_employees,
    mobile_admin_features as mobile_admin_features,
    mobile_im_cs_inbox as mobile_im_cs_inbox,
    mobile_im_cs_inbox_messages as mobile_im_cs_inbox_messages,
    mobile_im_cs_inbox_reply as mobile_im_cs_inbox_reply,
    mobile_admin_home as mobile_admin_home,
)
extension_router.include_router(admin_mobile_router)

from app.fastapi_routes.mobile_extensions.super_employee_routes import (  # noqa: E402, I001
    super_employee_router as super_employee_router,
    mobile_admin_codex_super_employee_messages as mobile_admin_codex_super_employee_messages,
    mobile_admin_codex_super_employee_invoke as mobile_admin_codex_super_employee_invoke,
    mobile_admin_claude_super_employee_messages as mobile_admin_claude_super_employee_messages,
    mobile_admin_claude_super_employee_invoke as mobile_admin_claude_super_employee_invoke,
    mobile_admin_cursor_super_employee_messages as mobile_admin_cursor_super_employee_messages,
    mobile_admin_cursor_super_employee_invoke as mobile_admin_cursor_super_employee_invoke,
    mobile_admin_trae_super_employee_messages as mobile_admin_trae_super_employee_messages,
    mobile_admin_trae_super_employee_invoke as mobile_admin_trae_super_employee_invoke,
    mobile_admin_factory_workspaces as mobile_admin_factory_workspaces,
    mobile_admin_codex_super_employee_stream as mobile_admin_codex_super_employee_stream,
    mobile_admin_claude_super_employee_stream as mobile_admin_claude_super_employee_stream,
    mobile_admin_cursor_super_employee_stream as mobile_admin_cursor_super_employee_stream,
    mobile_admin_trae_super_employee_stream as mobile_admin_trae_super_employee_stream,
    _super_employee_service_for_tool as _super_employee_service_for_tool,
    _stream_super_employee_invoke as _stream_super_employee_invoke,
)
extension_router.include_router(super_employee_router)

from app.fastapi_routes.mobile_extensions.ai_group_routes import (  # noqa: E402, I001
    ai_group_router as ai_group_router,
    mobile_git_branches as mobile_git_branches,
    mobile_ai_groups_list as mobile_ai_groups_list,
    mobile_ai_group_candidates as mobile_ai_group_candidates,
    mobile_ai_groups_create as mobile_ai_groups_create,
    mobile_ai_group_messages as mobile_ai_group_messages,
    mobile_ai_group_post as mobile_ai_group_post,
    mobile_ai_group_add_member as mobile_ai_group_add_member,
    mobile_ai_group_remove_member as mobile_ai_group_remove_member,
    mobile_ai_group_toggle_pin as mobile_ai_group_toggle_pin,
    mobile_ai_group_mark_unread as mobile_ai_group_mark_unread,
    mobile_ai_group_mark_read as mobile_ai_group_mark_read,
    mobile_ai_group_toggle_followed as mobile_ai_group_toggle_followed,
    mobile_ai_group_toggle_hidden as mobile_ai_group_toggle_hidden,
    mobile_ai_group_delete as mobile_ai_group_delete,
    mobile_conversation_toggle_pin as mobile_conversation_toggle_pin,
    mobile_conversation_mark_unread as mobile_conversation_mark_unread,
    mobile_conversation_mark_read as mobile_conversation_mark_read,
    mobile_conversation_toggle_followed as mobile_conversation_toggle_followed,
    mobile_conversation_toggle_hidden as mobile_conversation_toggle_hidden,
    mobile_conversation_delete as mobile_conversation_delete,
    _mobile_group_uid as _mobile_group_uid,
    _mobile_group_mode as _mobile_group_mode,
    _clean_mobile_git_branch as _clean_mobile_git_branch,
    _mobile_branch_context_from_body as _mobile_branch_context_from_body,
    _mobile_git_repo_root as _mobile_git_repo_root,
    _git_no_prompt_env as _git_no_prompt_env,
    _mobile_git_branches_from_repo as _mobile_git_branches_from_repo,
    _mobile_git_branches_from_remote as _mobile_git_branches_from_remote,
    _sort_mobile_git_branches as _sort_mobile_git_branches,
    _conversation_state_uid as _conversation_state_uid,
)
extension_router.include_router(ai_group_router)

from app.fastapi_routes.mobile_extensions.sync_home_routes import (  # noqa: E402, I001
    sync_home_router as sync_home_router,
    mobile_ai_circle_posts as mobile_ai_circle_posts,
    mobile_ai_circle_create_post as mobile_ai_circle_create_post,
    mobile_ai_circle_toggle_like as mobile_ai_circle_toggle_like,
    mobile_ai_circle_add_comment as mobile_ai_circle_add_comment,
    mobile_mods_summary as mobile_mods_summary,
    mobile_platform_shell as mobile_platform_shell,
    mobile_onboarding_industries as mobile_onboarding_industries,
    mobile_industry_baseline as mobile_industry_baseline,
    mobile_select_onboarding_industry as mobile_select_onboarding_industry,
    mobile_install_host_foundation as mobile_install_host_foundation,
    mobile_install_industry_seed as mobile_install_industry_seed,
    mobile_install_mod as mobile_install_mod,
    mobile_install_customer_delivery_seed as mobile_install_customer_delivery_seed,
    mobile_home as mobile_home,
    mobile_nav_menu as mobile_nav_menu,
    mobile_sync_status as mobile_sync_status,
    mobile_sync_pull as mobile_sync_pull,
    mobile_sync_push as mobile_sync_push,
    mobile_sync_ack as mobile_sync_ack,
    mobile_sync_conflicts as mobile_sync_conflicts,
    _mobile_sync_runtime_contract as _mobile_sync_runtime_contract,
    _mobile_sync_circle_posts as _mobile_sync_circle_posts,
)
extension_router.include_router(sync_home_router)

from app.fastapi_routes.mobile_extensions.auth_payment_routes import (  # noqa: E402, I001
    auth_payment_router as auth_payment_router,
    mobile_auth_qr_confirm as mobile_auth_qr_confirm,
    mobile_auth_oidc_exchange as mobile_auth_oidc_exchange,
    get_mobile_fixed_contacts as get_mobile_fixed_contacts,
    get_cs_info as get_cs_info,
    post_cs_message as post_cs_message,
    get_cs_messages as get_cs_messages,
    mobile_payment_plans as mobile_payment_plans,
    mobile_payment_checkout as mobile_payment_checkout,
    mobile_payment_query as mobile_payment_query,
    mobile_wallet_balance as mobile_wallet_balance,
    _normalize_mobile_payment_channel as _normalize_mobile_payment_channel,
    _mobile_checkout_sign_body as _mobile_checkout_sign_body,
)
extension_router.include_router(auth_payment_router)
# ── 员工任务中心 / 员工 chat SSE（实现见 mobile_extensions.employee_routes）──
from app.fastapi_routes.mobile_extensions.employee_routes import (  # noqa: E402, I001
    _chunk_employee_reply as _chunk_employee_reply,
    _extract_employee_failure_text as _extract_employee_failure_text,
    _extract_employee_reply_text as _extract_employee_reply_text,
    _modstore_admin_proxy as _modstore_admin_proxy,
    _modstore_admin_token as _modstore_admin_token,
    _modstore_platform_base as _modstore_platform_base,
    _sse_line as _sse_line,
    employee_router as employee_router,
    mobile_admin_employee_pending_question_answer as mobile_admin_employee_pending_question_answer,
    mobile_admin_employee_pending_questions as mobile_admin_employee_pending_questions,
    mobile_employee_chat_stream as mobile_employee_chat_stream,
)

extension_router.include_router(employee_router)

