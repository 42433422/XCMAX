# ruff: noqa: E402
"""Mobile composition root and compatibility exports.

Components receive only the operations they use. Callbacks deliberately resolve
public callbacks at invocation so integrations can replace them after assembly.
"""

from __future__ import annotations

from fastapi import APIRouter as APIRouter

extension_router = APIRouter(tags=["mobile-api-ext"])
# The router exists before loading the owner so either cold-import order works.
import asyncio as asyncio
import json as json
import logging as logging
import os as os
import re as re
import uuid as uuid
from datetime import datetime as datetime
from pathlib import Path as Path
from typing import TYPE_CHECKING as TYPE_CHECKING
from typing import Any as Any
from typing import cast as cast

import httpx
from fastapi import Body as Body
from fastapi import Depends as Depends
from fastapi import HTTPException as HTTPException
from fastapi import Query as Query
from fastapi import Request as Request
from fastapi.responses import JSONResponse as JSONResponse
from fastapi.responses import StreamingResponse as StreamingResponse
from pydantic import BaseModel as BaseModel
from pydantic import Field as Field

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
from app.fastapi_routes.mobile_api import get_mobile_user as get_mobile_user
from app.fastapi_routes.mobile_api import router as _mobile_router
from app.fastapi_routes.mobile_extensions import backends as backends
from app.fastapi_routes.mobile_extensions import ports as contracts
from app.fastapi_routes.mobile_extensions.access import MobileAccess as MobileAccess
from app.fastapi_routes.mobile_extensions.access import MobileAccessPorts as MobileAccessPorts
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _admin_employee_match_keys as _admin_employee_match_keys,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _apply_market_profile as _apply_market_profile,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import _compact_text as _compact_text
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
from app.fastapi_routes.mobile_extensions.cs_helpers import _safe_user_id as _safe_user_id
from app.fastapi_routes.mobile_extensions.cs_helpers import _safe_user_text as _safe_user_text
from app.fastapi_routes.mobile_extensions.employee_catalog import EmployeeCatalog as EmployeeCatalog
from app.fastapi_routes.mobile_extensions.employee_catalog import (
    EmployeeCatalogPorts as EmployeeCatalogPorts,
)
from app.fastapi_routes.mobile_extensions.models import AiCircleCommentBody as AiCircleCommentBody
from app.fastapi_routes.mobile_extensions.models import AiCirclePostBody as AiCirclePostBody
from app.fastapi_routes.mobile_extensions.models import AiGroupCreateBody as AiGroupCreateBody
from app.fastapi_routes.mobile_extensions.models import AiGroupMemberBody as AiGroupMemberBody
from app.fastapi_routes.mobile_extensions.models import AiGroupMessageBody as AiGroupMessageBody
from app.fastapi_routes.mobile_extensions.models import AuthQrConfirmBody as AuthQrConfirmBody
from app.fastapi_routes.mobile_extensions.models import (
    ClaudeSuperEmployeeMobileMessageBody as ClaudeSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    CodexSuperEmployeeMobileMessageBody as CodexSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    CursorSuperEmployeeMobileMessageBody as CursorSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.models import DeviceRegisterBody as DeviceRegisterBody
from app.fastapi_routes.mobile_extensions.models import (
    MobileServiceBridgeRespondBody as MobileServiceBridgeRespondBody,
)
from app.fastapi_routes.mobile_extensions.models import OidcExchangeBody as OidcExchangeBody
from app.fastapi_routes.mobile_extensions.models import PairingExchangeBody as PairingExchangeBody
from app.fastapi_routes.mobile_extensions.models import PairingIssueBody as PairingIssueBody
from app.fastapi_routes.mobile_extensions.models import PairingLookupBody as PairingLookupBody
from app.fastapi_routes.mobile_extensions.models import (
    RelayDesktopCompleteBody as RelayDesktopCompleteBody,
)
from app.fastapi_routes.mobile_extensions.models import RelayDesktopPollBody as RelayDesktopPollBody
from app.fastapi_routes.mobile_extensions.models import (
    RelayDesktopRegisterBody as RelayDesktopRegisterBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    RelayDesktopRenewBody as RelayDesktopRenewBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    RelayMobileBindAccountBody as RelayMobileBindAccountBody,
)
from app.fastapi_routes.mobile_extensions.models import RelayTaskCreateBody as RelayTaskCreateBody
from app.fastapi_routes.mobile_extensions.models import SyncAckBody as SyncAckBody
from app.fastapi_routes.mobile_extensions.models import SyncPullBody as SyncPullBody
from app.fastapi_routes.mobile_extensions.models import SyncPushBody as SyncPushBody
from app.fastapi_routes.mobile_extensions.models import SyncPushItem as SyncPushItem
from app.fastapi_routes.mobile_extensions.models import (
    TraeSuperEmployeeMobileMessageBody as TraeSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.navigation_constants import (
    _ADMIN_NAV_ITEM as _ADMIN_NAV_ITEM,
)
from app.fastapi_routes.mobile_extensions.navigation_constants import (
    _CORE_NAV_ITEMS as _CORE_NAV_ITEMS,
)
from app.fastapi_routes.mobile_extensions.navigation_constants import (
    _ROLE_VISIBLE_KEYS as _ROLE_VISIBLE_KEYS,
)
from app.fastapi_routes.mobile_extensions.pairing_helpers import (
    _enrich_pairing_payload as _enrich_pairing_payload,
)
from app.fastapi_routes.mobile_extensions.pairing_helpers import _guess_lan_ipv4 as _guess_lan_ipv4
from app.fastapi_routes.mobile_extensions.pairing_helpers import (
    _host_is_private_or_loopback as _host_is_private_or_loopback,
)
from app.fastapi_routes.mobile_extensions.pairing_helpers import (
    _pairing_issue_port as _pairing_issue_port,
)
from app.fastapi_routes.mobile_extensions.pairing_helpers import (
    _pairing_reachable_port as _pairing_reachable_port,
)
from app.fastapi_routes.mobile_extensions.read_models import MobileReadModels as MobileReadModels
from app.fastapi_routes.mobile_extensions.read_models import (
    MobileReadModelsPorts as MobileReadModelsPorts,
)
from app.fastapi_routes.mobile_extensions.relay_helpers import (
    _mobile_user_identity as _mobile_user_identity,
)
from app.fastapi_routes.mobile_extensions.relay_helpers import (
    _mobile_user_public_dict as _mobile_user_public_dict,
)
from app.fastapi_routes.mobile_extensions.relay_helpers import (
    _relay_mobile_auth_payload as _relay_mobile_auth_payload,
)
from app.fastapi_routes.mobile_extensions.routes_admin import AdminRoutes as AdminRoutes
from app.fastapi_routes.mobile_extensions.routes_admin import AdminRoutesPorts as AdminRoutesPorts
from app.fastapi_routes.mobile_extensions.routes_ai_groups import GroupRoutes as GroupRoutes
from app.fastapi_routes.mobile_extensions.routes_ai_groups import (
    GroupRoutesPorts as GroupRoutesPorts,
)
from app.fastapi_routes.mobile_extensions.routes_auth import (
    mobile_auth_oidc_exchange as mobile_auth_oidc_exchange,
)
from app.fastapi_routes.mobile_extensions.routes_auth import (
    mobile_auth_qr_confirm as mobile_auth_qr_confirm,
)
from app.fastapi_routes.mobile_extensions.routes_auth import router as _auth_router
from app.fastapi_routes.mobile_extensions.routes_circle import CircleRoutes as CircleRoutes
from app.fastapi_routes.mobile_extensions.routes_circle import (
    CircleRoutesPorts as CircleRoutesPorts,
)
from app.fastapi_routes.mobile_extensions.routes_conversations import (
    _conversation_state_uid as _conversation_state_uid,
)
from app.fastapi_routes.mobile_extensions.routes_conversations import (
    mobile_conversation_delete as mobile_conversation_delete,
)
from app.fastapi_routes.mobile_extensions.routes_conversations import (
    mobile_conversation_mark_read as mobile_conversation_mark_read,
)
from app.fastapi_routes.mobile_extensions.routes_conversations import (
    mobile_conversation_mark_unread as mobile_conversation_mark_unread,
)
from app.fastapi_routes.mobile_extensions.routes_conversations import (
    mobile_conversation_toggle_followed as mobile_conversation_toggle_followed,
)
from app.fastapi_routes.mobile_extensions.routes_conversations import (
    mobile_conversation_toggle_hidden as mobile_conversation_toggle_hidden,
)
from app.fastapi_routes.mobile_extensions.routes_conversations import (
    mobile_conversation_toggle_pin as mobile_conversation_toggle_pin,
)
from app.fastapi_routes.mobile_extensions.routes_conversations import (
    router as _conversations_router,
)
from app.fastapi_routes.mobile_extensions.routes_cs_contacts import ContactRoutes as ContactRoutes
from app.fastapi_routes.mobile_extensions.routes_cs_contacts import (
    ContactRoutesPorts as ContactRoutesPorts,
)
from app.fastapi_routes.mobile_extensions.routes_devices import DeviceRoutes as DeviceRoutes
from app.fastapi_routes.mobile_extensions.routes_devices import (
    DeviceRoutesPorts as DeviceRoutesPorts,
)
from app.fastapi_routes.mobile_extensions.routes_employee_chat import (
    EmployeeChatRoutes as EmployeeChatRoutes,
)
from app.fastapi_routes.mobile_extensions.routes_employee_chat import (
    EmployeeChatRoutesPorts as EmployeeChatRoutesPorts,
)
from app.fastapi_routes.mobile_extensions.routes_pairing import PairingRoutes as PairingRoutes
from app.fastapi_routes.mobile_extensions.routes_pairing import (
    PairingRoutesPorts as PairingRoutesPorts,
)
from app.fastapi_routes.mobile_extensions.routes_payment import PaymentRoutes as PaymentRoutes
from app.fastapi_routes.mobile_extensions.routes_payment import (
    PaymentRoutesPorts as PaymentRoutesPorts,
)
from app.fastapi_routes.mobile_extensions.routes_relay import RelayRoutes as RelayRoutes
from app.fastapi_routes.mobile_extensions.routes_relay import RelayRoutesPorts as RelayRoutesPorts
from app.fastapi_routes.mobile_extensions.routes_super_employee import (
    SuperEmployeeRoutes as SuperEmployeeRoutes,
)
from app.fastapi_routes.mobile_extensions.routes_super_employee import (
    SuperEmployeeRoutesPorts as SuperEmployeeRoutesPorts,
)
from app.fastapi_routes.mobile_extensions.routes_support import SupportRoutes as SupportRoutes
from app.fastapi_routes.mobile_extensions.routes_support import (
    SupportRoutesPorts as SupportRoutesPorts,
)
from app.fastapi_routes.mobile_extensions.routes_sync import SyncRoutes as SyncRoutes
from app.fastapi_routes.mobile_extensions.routes_sync import SyncRoutesPorts as SyncRoutesPorts
from app.fastapi_routes.mobile_extensions.routes_worklists import WorklistRoutes as WorklistRoutes
from app.fastapi_routes.mobile_extensions.routes_worklists import (
    WorklistRoutesPorts as WorklistRoutesPorts,
)
from app.fastapi_routes.mobile_extensions.routes_workspace import WorkspaceRoutes as WorkspaceRoutes
from app.fastapi_routes.mobile_extensions.routes_workspace import (
    WorkspaceRoutesPorts as WorkspaceRoutesPorts,
)
from app.mod_sdk.assistant_ssot import dedicated_cs_label as dedicated_cs_label
from app.security.mobile_pairing import consume_by_shortcode as consume_by_shortcode
from app.security.mobile_pairing import consume_pairing_nonce as consume_pairing_nonce
from app.security.mobile_pairing import issue_pairing_nonce as issue_pairing_nonce
from app.security.mobile_pairing import lookup_by_shortcode as lookup_by_shortcode
from app.utils.device_system.mobile_api import format_mobile_response as format_mobile_response
from app.utils.device_system.mobile_api import paginate_list as paginate_list
from app.utils.operational_errors import RECOVERABLE_ERRORS as RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_access = MobileAccess(
    MobileAccessPorts(
        verify_jwt=backends.verify_jwt,
        mobile_session_id_from_request=contracts.late_callback(
            lambda: _mobile_session_id_from_request
        ),
        auth_header=backends.auth_header,
        latest_market_token=backends.latest_market_token,
        session_market_token=backends.session_market_token,
    )
)
_mobile_session_id_from_request: contracts.MobileSessionIdFromRequestCall = (
    _access._mobile_session_id_from_request
)
_mobile_market_authorization: contracts.MobileMarketAuthorizationCall = (
    _access._mobile_market_authorization
)
_mobile_unauthorized_response: contracts.MobileUnauthorizedResponseCall = (
    _access._mobile_unauthorized_response
)
_pairing_rate_allowed: contracts.PairingRateAllowedCall = _access._pairing_rate_allowed
_ai_circle_user: contracts.AiCircleUserCall = _access._ai_circle_user

_read_models = MobileReadModels(
    MobileReadModelsPorts(
        database=backends.database,
    )
)
_approval_items: contracts.ApprovalItemsCall = _read_models._approval_items
_shipment_items: contracts.ShipmentItemsCall = _read_models._shipment_items
_safe_mobile_sync_items: contracts.SafeMobileSyncItemsCall = _read_models._safe_mobile_sync_items
_ai_conversation_changes: contracts.AiConversationChangesCall = (
    _read_models._ai_conversation_changes
)

_employee_catalog = EmployeeCatalog(
    EmployeeCatalogPorts(
        enrich_workflow_employees=contracts.late_callback(lambda: _enrich_workflow_employees),
        upsert_admin_duty_mod_item=contracts.late_callback(lambda: _upsert_admin_duty_mod_item),
        mod_manager=backends.mod_manager,
        duty_roster=backends.duty_roster,
        compact_text=contracts.late_callback(lambda: _compact_text),
        roster_document=backends.roster_document,
        admin_employee_manifest=contracts.late_callback(lambda: _admin_employee_manifest),
        admin_roster_area_labels=contracts.late_callback(lambda: _admin_roster_area_labels),
        admin_roster_ids_by_department_order=contracts.late_callback(
            lambda: _admin_roster_ids_by_department_order
        ),
        load_admin_duty_records=contracts.late_callback(lambda: _load_admin_duty_records),
        admin_duty_records_from_roster=contracts.late_callback(
            lambda: _admin_duty_records_from_roster
        ),
        admin_employee_match_keys=contracts.late_callback(lambda: _admin_employee_match_keys),
        apply_market_profile=contracts.late_callback(lambda: _apply_market_profile),
        admin_employee_items=contracts.late_callback(lambda: _admin_employee_items),
        admin_duty_mod_item=contracts.late_callback(lambda: _admin_duty_mod_item),
        mobile_mod_items=contracts.late_callback(lambda: _mobile_mod_items),
        installed_employee_ids=backends.installed_employee_ids,
        employee_ssot=backends.employee_ssot,
    )
)
_mobile_mod_items: contracts.MobileModItemsCall = _employee_catalog._mobile_mod_items
_admin_roster_ids_by_department_order: contracts.AdminRosterIdsByDepartmentOrderCall = (
    _employee_catalog._admin_roster_ids_by_department_order
)
_admin_roster_area_labels: contracts.AdminRosterAreaLabelsCall = (
    _employee_catalog._admin_roster_area_labels
)
_admin_employee_manifest: contracts.AdminEmployeeManifestCall = (
    _employee_catalog._admin_employee_manifest
)
_admin_duty_records_from_roster: contracts.AdminDutyRecordsFromRosterCall = (
    _employee_catalog._admin_duty_records_from_roster
)
_admin_employee_items: contracts.AdminEmployeeItemsCall = _employee_catalog._admin_employee_items
_admin_duty_mod_item: contracts.AdminDutyModItemCall = _employee_catalog._admin_duty_mod_item
_upsert_admin_duty_mod_item: contracts.UpsertAdminDutyModItemCall = (
    _employee_catalog._upsert_admin_duty_mod_item
)
_ai_circle_employee_profiles: contracts.AiCircleEmployeeProfilesCall = (
    _employee_catalog._ai_circle_employee_profiles
)
_employee_ssot_payload: contracts.EmployeeSsotPayloadCall = _employee_catalog._employee_ssot_payload

_worklists = WorklistRoutes(
    WorklistRoutesPorts(
        database=backends.database,
        employee_ssot_payload=contracts.late_callback(lambda: _employee_ssot_payload),
    ),
    get_mobile_user,
)
mobile_approval_list = _worklists.mobile_approval_list
mobile_customers = _worklists.mobile_customers
mobile_shipments = _worklists.mobile_shipments
mobile_employee_ssot = _worklists.mobile_employee_ssot
extension_router.include_router(_worklists.router)

_devices = DeviceRoutes(
    DeviceRoutesPorts(
        database=backends.database,
        warning=contracts.late_callback(lambda: logger.warning),
        ensure_mobile_device_table=contracts.late_callback(lambda: _ensure_mobile_device_table),
        now=backends.now,
        ensure_outbox_table=contracts.late_callback(lambda: _ensure_outbox_table),
    ),
    get_mobile_user,
)
_ensure_mobile_device_table: contracts.EnsureMobileDeviceTableCall = (
    _devices._ensure_mobile_device_table
)
_ensure_outbox_table: contracts.EnsureOutboxTableCall = _devices._ensure_outbox_table
mobile_device_register = _devices.mobile_device_register
mobile_device_unregister = _devices.mobile_device_unregister
mobile_notifications_pending = _devices.mobile_notifications_pending
extension_router.include_router(_devices.router)

_pairing = PairingRoutes(
    PairingRoutesPorts(
        host_is_private_or_loopback=contracts.late_callback(lambda: _host_is_private_or_loopback),
        register_relay=backends.register_relay,
        cached_relay=backends.cached_relay,
        guess_lan_ipv4=contracts.late_callback(lambda: _guess_lan_ipv4),
        is_desktop=backends.is_desktop,
        enrich_pairing_payload=contracts.late_callback(lambda: _enrich_pairing_payload),
        mobile_unauthorized_response=contracts.late_callback(lambda: _mobile_unauthorized_response),
        pairing_issue_host=contracts.late_callback(lambda: _pairing_issue_host),
        pairing_issue_port=contracts.late_callback(lambda: _pairing_issue_port),
        pairing_reachable_port=contracts.late_callback(lambda: _pairing_reachable_port),
        register_desktop_relay_for_pairing=contracts.late_callback(
            lambda: _register_desktop_relay_for_pairing
        ),
        trusted_desktop_pairing_request=contracts.late_callback(
            lambda: _trusted_desktop_pairing_request
        ),
        issue_pairing_nonce=contracts.late_callback(lambda: issue_pairing_nonce),
        mobile_user_identity=contracts.late_callback(lambda: _mobile_user_identity),
        pairing_rate_allowed=contracts.late_callback(lambda: _pairing_rate_allowed),
        lookup_by_shortcode=contracts.late_callback(lambda: lookup_by_shortcode),
        cached_desktop_relay_for_account_binding=contracts.late_callback(
            lambda: _cached_desktop_relay_for_account_binding
        ),
        mobile_user_public_dict=contracts.late_callback(lambda: _mobile_user_public_dict),
        relay_mobile_auth_payload=contracts.late_callback(lambda: _relay_mobile_auth_payload),
        consume_by_shortcode=contracts.late_callback(lambda: consume_by_shortcode),
        consume_pairing_nonce=contracts.late_callback(lambda: consume_pairing_nonce),
    ),
    get_mobile_user,
)
_register_desktop_relay_for_pairing: contracts.RegisterDesktopRelayForPairingCall = (
    _pairing._register_desktop_relay_for_pairing
)
_cached_desktop_relay_for_account_binding: contracts.CachedDesktopRelayForAccountBindingCall = (
    _pairing._cached_desktop_relay_for_account_binding
)
_pairing_issue_host: contracts.PairingIssueHostCall = _pairing._pairing_issue_host
_trusted_desktop_pairing_request: contracts.TrustedDesktopPairingRequestCall = (
    _pairing._trusted_desktop_pairing_request
)
mobile_pairing_issue = _pairing.mobile_pairing_issue
mobile_pairing_lookup = _pairing.mobile_pairing_lookup
mobile_pairing_exchange = _pairing.mobile_pairing_exchange
extension_router.include_router(_pairing.router)

_relay = RelayRoutes(
    RelayRoutesPorts(
        pairing_rate_allowed=contracts.late_callback(lambda: _pairing_rate_allowed),
        mobile_relay_service=contracts.late_callback(lambda: MobileRelayService),
        mobile_user_identity=contracts.late_callback(lambda: _mobile_user_identity),
        mobile_user_public_dict=contracts.late_callback(lambda: _mobile_user_public_dict),
        relay_mobile_auth_payload=contracts.late_callback(lambda: _relay_mobile_auth_payload),
    ),
    get_mobile_user,
)
mobile_relay_desktop_register = _relay.mobile_relay_desktop_register
mobile_relay_desktop_renew = _relay.mobile_relay_desktop_renew
mobile_relay_bind_account = _relay.mobile_relay_bind_account
mobile_relay_desktops = _relay.mobile_relay_desktops
mobile_relay_create_task = _relay.mobile_relay_create_task
mobile_relay_task_status = _relay.mobile_relay_task_status
mobile_relay_task_cancel = _relay.mobile_relay_task_cancel
mobile_relay_desktop_poll = _relay.mobile_relay_desktop_poll
mobile_relay_desktop_complete = _relay.mobile_relay_desktop_complete
extension_router.include_router(_relay.router)

_support = SupportRoutes(
    SupportRoutesPorts(
        mobile_cs_source_id=contracts.late_callback(lambda: _mobile_cs_source_id),
        mobile_cs_source_name=contracts.late_callback(lambda: _mobile_cs_source_name),
        safe_user_id=contracts.late_callback(lambda: _safe_user_id),
        safe_user_text=contracts.late_callback(lambda: _safe_user_text),
        database=backends.database,
        mobile_bridge_request_statuses=contracts.late_callback(
            lambda: _mobile_bridge_request_statuses
        ),
        now=backends.now,
        require_mobile_admin=contracts.late_callback(lambda: _require_mobile_admin),
        im_service=backends.im_service,
    ),
    get_mobile_user,
)
_mobile_bridge_request_statuses: contracts.MobileBridgeRequestStatusesCall = (
    _support._mobile_bridge_request_statuses
)
_persist_mobile_cs_request = _support._persist_mobile_cs_request
mobile_service_bridge_requests = _support.mobile_service_bridge_requests
mobile_service_bridge_request_respond = _support.mobile_service_bridge_request_respond
mobile_im_cs_inbox = _support.mobile_im_cs_inbox
mobile_im_cs_inbox_messages = _support.mobile_im_cs_inbox_messages
mobile_im_cs_inbox_reply = _support.mobile_im_cs_inbox_reply
extension_router.include_router(_support.router)

_workspace = WorkspaceRoutes(
    WorkspaceRoutesPorts(
        load_market_ai_employee_profile_index=contracts.late_callback(
            lambda: _load_market_ai_employee_profile_index
        ),
        mobile_mod_items=contracts.late_callback(lambda: _mobile_mod_items),
        platform_shell=backends.platform_shell,
        mobile_unauthorized_response=contracts.late_callback(lambda: _mobile_unauthorized_response),
        industry_catalog=backends.industry_catalog,
        industry_plan=backends.industry_plan,
        mobile_session_id_from_request=contracts.late_callback(
            lambda: _mobile_session_id_from_request
        ),
        select_industry=backends.select_industry,
        grant_entitlements=backends.grant_entitlements,
        install_foundation=backends.install_foundation,
        install_industry_seed=backends.install_industry_seed,
        set_account_industry=backends.set_account_industry,
        install_mod=backends.install_mod,
        install_customer_seed=backends.install_customer_seed,
        sync_database=backends.sync_database,
    ),
    get_mobile_user,
)
mobile_mods_summary = _workspace.mobile_mods_summary
mobile_platform_shell = _workspace.mobile_platform_shell
mobile_onboarding_industries = _workspace.mobile_onboarding_industries
mobile_industry_baseline = _workspace.mobile_industry_baseline
mobile_select_onboarding_industry = _workspace.mobile_select_onboarding_industry
mobile_install_host_foundation = _workspace.mobile_install_host_foundation
mobile_install_industry_seed = _workspace.mobile_install_industry_seed
mobile_install_mod = _workspace.mobile_install_mod
mobile_install_customer_delivery_seed = _workspace.mobile_install_customer_delivery_seed
mobile_home = _workspace.mobile_home
mobile_nav_menu = _workspace.mobile_nav_menu
extension_router.include_router(_workspace.router)

_admin = AdminRoutes(
    AdminRoutesPorts(
        client=lambda timeout: httpx.AsyncClient(timeout=timeout),
        admin_employee_items=contracts.late_callback(lambda: _admin_employee_items),
        load_market_ai_employee_profile_index=contracts.late_callback(
            lambda: _load_market_ai_employee_profile_index
        ),
        mobile_request_user_id=contracts.late_callback(lambda: _mobile_request_user_id),
        require_mobile_admin=contracts.late_callback(lambda: _require_mobile_admin),
        im_service=backends.im_service,
        session_factory=backends.session_factory,
        compact_text=contracts.late_callback(lambda: _compact_text),
        modstore_admin_token=contracts.late_callback(lambda: _modstore_admin_token),
        modstore_platform_base=contracts.late_callback(lambda: _modstore_platform_base),
        modstore_admin_proxy=contracts.late_callback(lambda: _modstore_admin_proxy),
    ),
    get_mobile_user,
)
mobile_admin_employees = _admin.mobile_admin_employees
mobile_admin_features = _admin.mobile_admin_features
mobile_admin_home = _admin.mobile_admin_home
_modstore_platform_base: contracts.ModstorePlatformBaseCall = _admin._modstore_platform_base
_modstore_admin_token: contracts.ModstoreAdminTokenCall = _admin._modstore_admin_token
_modstore_admin_proxy: contracts.ModstoreAdminProxyCall = _admin._modstore_admin_proxy
mobile_admin_employee_pending_questions = _admin.mobile_admin_employee_pending_questions
mobile_admin_employee_pending_question_answer = _admin.mobile_admin_employee_pending_question_answer
extension_router.include_router(_admin.router)

_circle = CircleRoutes(
    CircleRoutesPorts(
        ai_circle_employee_profiles=contracts.late_callback(lambda: _ai_circle_employee_profiles),
        ai_circle_user=contracts.late_callback(lambda: _ai_circle_user),
        list_posts=backends.list_posts,
        sync_circle=backends.sync_circle,
        create_post=backends.create_post,
        toggle_like=backends.toggle_like,
        add_comment=backends.add_comment,
    ),
    get_mobile_user,
)
mobile_ai_circle_posts = _circle.mobile_ai_circle_posts
mobile_ai_circle_create_post = _circle.mobile_ai_circle_create_post
mobile_ai_circle_toggle_like = _circle.mobile_ai_circle_toggle_like
mobile_ai_circle_add_comment = _circle.mobile_ai_circle_add_comment
extension_router.include_router(_circle.router)

_employee_chat = EmployeeChatRoutes(
    EmployeeChatRoutesPorts(
        extract_employee_failure_text=contracts.late_callback(
            lambda: _extract_employee_failure_text
        ),
        chunk_employee_reply=contracts.late_callback(lambda: _chunk_employee_reply),
        extract_employee_reply_text=contracts.late_callback(lambda: _extract_employee_reply_text),
        sse_line=contracts.late_callback(lambda: _sse_line),
        execute_employee=backends.execute_employee,
    ),
    get_mobile_user,
)
_sse_line: contracts.SseLineCall = _employee_chat._sse_line
_chunk_employee_reply: contracts.ChunkEmployeeReplyCall = _employee_chat._chunk_employee_reply
_extract_employee_failure_text: contracts.ExtractEmployeeFailureTextCall = (
    _employee_chat._extract_employee_failure_text
)
_extract_employee_reply_text: contracts.ExtractEmployeeReplyTextCall = (
    _employee_chat._extract_employee_reply_text
)
mobile_employee_chat_stream = _employee_chat.mobile_employee_chat_stream
extension_router.include_router(_employee_chat.router)

_ai_groups = GroupRoutes(
    GroupRoutesPorts(
        mobile_request_user_id=contracts.late_callback(lambda: _mobile_request_user_id),
        mobile_session_meta=contracts.late_callback(lambda: _mobile_session_meta),
        require_mobile_admin_or_enterprise=contracts.late_callback(
            lambda: _require_mobile_admin_or_enterprise
        ),
        ai_group_service=contracts.late_callback(lambda: AiGroupChatService),
        mobile_group_mode=contracts.late_callback(lambda: _mobile_group_mode),
        mobile_group_uid=contracts.late_callback(lambda: _mobile_group_uid),
    ),
    get_mobile_user,
)
_mobile_group_uid: contracts.MobileGroupUidCall = _ai_groups._mobile_group_uid
_mobile_group_mode: contracts.MobileGroupModeCall = _ai_groups._mobile_group_mode
mobile_git_branches = _ai_groups.mobile_git_branches
mobile_ai_groups_list = _ai_groups.mobile_ai_groups_list
mobile_ai_group_candidates = _ai_groups.mobile_ai_group_candidates
mobile_ai_groups_create = _ai_groups.mobile_ai_groups_create
mobile_ai_group_messages = _ai_groups.mobile_ai_group_messages
mobile_ai_group_post = _ai_groups.mobile_ai_group_post
mobile_ai_group_add_member = _ai_groups.mobile_ai_group_add_member
mobile_ai_group_remove_member = _ai_groups.mobile_ai_group_remove_member
mobile_ai_group_toggle_pin = _ai_groups.mobile_ai_group_toggle_pin
mobile_ai_group_mark_unread = _ai_groups.mobile_ai_group_mark_unread
mobile_ai_group_mark_read = _ai_groups.mobile_ai_group_mark_read
mobile_ai_group_toggle_followed = _ai_groups.mobile_ai_group_toggle_followed
mobile_ai_group_toggle_hidden = _ai_groups.mobile_ai_group_toggle_hidden
mobile_ai_group_delete = _ai_groups.mobile_ai_group_delete
extension_router.include_router(_ai_groups.router)

_cs_contacts = ContactRoutes(
    ContactRoutesPorts(
        mobile_group_mode=contracts.late_callback(lambda: _mobile_group_mode),
        fixed_contacts=backends.fixed_contacts,
        mobile_request_user_id=contracts.late_callback(lambda: _mobile_request_user_id),
        im_service=backends.im_service,
        database=backends.database,
        process_cs_message=backends.process_cs_message,
    ),
    get_mobile_user,
)
get_mobile_fixed_contacts = _cs_contacts.get_mobile_fixed_contacts
get_cs_info = _cs_contacts.get_cs_info
post_cs_message = _cs_contacts.post_cs_message
get_cs_messages = _cs_contacts.get_cs_messages
extension_router.include_router(_cs_contacts.router)

_payment = PaymentRoutes(
    PaymentRoutesPorts(
        mobile_market_authorization=contracts.late_callback(lambda: _mobile_market_authorization),
        mobile_unauthorized_response=contracts.late_callback(lambda: _mobile_unauthorized_response),
        market_base_url=backends.market_base_url,
        market_proxy=backends.market_proxy,
        mobile_checkout_sign_body=contracts.late_callback(lambda: _mobile_checkout_sign_body),
        normalize_mobile_payment_channel=contracts.late_callback(
            lambda: _normalize_mobile_payment_channel
        ),
        auth_header=backends.auth_header,
        latest_market_token=backends.latest_market_token,
        resolve_market_token=backends.resolve_market_token,
        session_market_token=backends.session_market_token,
        verify_jwt=backends.verify_jwt,
        request_session_id=backends.request_session_id,
    ),
    get_mobile_user,
)
_normalize_mobile_payment_channel: contracts.NormalizeMobilePaymentChannelCall = (
    _payment._normalize_mobile_payment_channel
)
_mobile_checkout_sign_body: contracts.MobileCheckoutSignBodyCall = (
    _payment._mobile_checkout_sign_body
)
mobile_payment_plans = _payment.mobile_payment_plans
mobile_payment_checkout = _payment.mobile_payment_checkout
mobile_payment_query = _payment.mobile_payment_query
mobile_wallet_balance = _payment.mobile_wallet_balance
extension_router.include_router(_payment.router)

_super_employee = SuperEmployeeRoutes(
    SuperEmployeeRoutesPorts(
        mobile_request_user_id=contracts.late_callback(lambda: _mobile_request_user_id),
        require_mobile_admin=contracts.late_callback(lambda: _require_mobile_admin),
        codex_super_employee_service=contracts.late_callback(lambda: CodexSuperEmployeeService),
        mobile_session_meta=contracts.late_callback(lambda: _mobile_session_meta),
        factory_context=contracts.late_callback(lambda: factory_context),
        claude_super_employee_service=contracts.late_callback(lambda: ClaudeSuperEmployeeService),
        cursor_super_employee_service=contracts.late_callback(lambda: CursorSuperEmployeeService),
        trae_super_employee_service=contracts.late_callback(lambda: TraeSuperEmployeeService),
        stream_super_employee_invoke=contracts.late_callback(lambda: _stream_super_employee_invoke),
        sse_line=contracts.late_callback(lambda: _sse_line),
    ),
    get_mobile_user,
)
mobile_admin_codex_super_employee_messages = (
    _super_employee.mobile_admin_codex_super_employee_messages
)
mobile_admin_codex_super_employee_invoke = _super_employee.mobile_admin_codex_super_employee_invoke
mobile_admin_claude_super_employee_messages = (
    _super_employee.mobile_admin_claude_super_employee_messages
)
mobile_admin_claude_super_employee_invoke = (
    _super_employee.mobile_admin_claude_super_employee_invoke
)
mobile_admin_cursor_super_employee_messages = (
    _super_employee.mobile_admin_cursor_super_employee_messages
)
mobile_admin_cursor_super_employee_invoke = (
    _super_employee.mobile_admin_cursor_super_employee_invoke
)
mobile_admin_trae_super_employee_messages = (
    _super_employee.mobile_admin_trae_super_employee_messages
)
mobile_admin_trae_super_employee_invoke = _super_employee.mobile_admin_trae_super_employee_invoke
mobile_admin_codex_super_employee_stream = _super_employee.mobile_admin_codex_super_employee_stream
mobile_admin_claude_super_employee_stream = (
    _super_employee.mobile_admin_claude_super_employee_stream
)
mobile_admin_cursor_super_employee_stream = (
    _super_employee.mobile_admin_cursor_super_employee_stream
)
mobile_admin_trae_super_employee_stream = _super_employee.mobile_admin_trae_super_employee_stream
_stream_super_employee_invoke: contracts.StreamSuperEmployeeInvokeCall = (
    _super_employee._stream_super_employee_invoke
)
extension_router.include_router(_super_employee.router)

_sync = SyncRoutes(
    SyncRoutesPorts(
        ai_circle_employee_profiles=contracts.late_callback(lambda: _ai_circle_employee_profiles),
        ai_circle_user=contracts.late_callback(lambda: _ai_circle_user),
        list_posts=backends.list_posts,
        sync_circle=backends.sync_circle,
        mobile_sync_runtime_contract=contracts.late_callback(lambda: _mobile_sync_runtime_contract),
        sync_database=backends.sync_database,
        ensure_sync_schema=backends.ensure_sync_schema,
        sync_connection=backends.sync_connection,
        ai_conversation_changes=contracts.late_callback(lambda: _ai_conversation_changes),
        approval_items=contracts.late_callback(lambda: _approval_items),
        mobile_sync_circle_posts=contracts.late_callback(lambda: _mobile_sync_circle_posts),
        safe_mobile_sync_items=contracts.late_callback(lambda: _safe_mobile_sync_items),
        shipment_items=contracts.late_callback(lambda: _shipment_items),
        apply_inbox=backends.apply_inbox,
    ),
    get_mobile_user,
)
_mobile_sync_runtime_contract: contracts.MobileSyncRuntimeContractCall = (
    _sync._mobile_sync_runtime_contract
)
_mobile_sync_circle_posts: contracts.MobileSyncCirclePostsCall = _sync._mobile_sync_circle_posts
mobile_sync_status = _sync.mobile_sync_status
mobile_sync_pull = _sync.mobile_sync_pull
mobile_sync_push = _sync.mobile_sync_push
mobile_sync_ack = _sync.mobile_sync_ack
mobile_sync_conflicts = _sync.mobile_sync_conflicts
extension_router.include_router(_sync.router)

extension_router.include_router(_conversations_router)
extension_router.include_router(_auth_router)

cast(APIRouter, _mobile_router).include_router(extension_router)
