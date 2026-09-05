# isort: skip_file
# ruff: noqa: E402, F401
"""XC AGI 在线市场 API：认证、注册、登录、公开联系表单。"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from modstore_server import account_level_service
from modstore_server.auth_service import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_user_by_id,
    hash_password,
    record_successful_login,
    register_user,
    verify_password,
)
from modstore_server.contact_company_match import build_company_match_payload
from modstore_server.digest_identity import (
    normalize_digest_identity_code,
    verify_digest_identity,
)
from modstore_server.digest_identity_peer_api import call_upstream_digest_verify
from modstore_server.email_service import (
    assert_email_outbound_configured,
    find_user_by_email,
    generate_verification_code,
    send_verification_email,
)
from modstore_server.enterprise_entitlements import (
    normalize_enterprise_entitlement_mod_ids,
)
from modstore_server.java_me_profile import fetch_java_user_overlay
from modstore_server.market_shared import (
    _get_current_user,
    _optional_current_user,
    _public_contact_client_key,
    _public_contact_company_match_rate_allow,
    _public_contact_rate_allow,
    _require_admin,
    _workbench_company_match_rate_allow,
)
from modstore_server.models import (
    CatalogItem,
    LandingContactSubmission,
    User,
    VerificationCode,
    get_session_factory,
)
from modstore_server.public_contact_payloads import (
    CONTACT_PRIVACY_URL,
    CONTACT_PRIVACY_VERSION,
    PublicContactDTO,
)
from modstore_server.public_contact_payloads import (
    format_contact_audit_code as _format_contact_audit_code,
)
from modstore_server.public_contact_payloads import (
    landing_submission_payload as _landing_submission_payload,
)
from modstore_server.public_contact_payloads import (
    normalize_contact_tracking_fields,
)
from modstore_server.public_contact_payloads import normalize_desktop_os as _norm_os
from modstore_server.public_contact_payloads import (
    parse_contact_audit_code,
)
from modstore_server.user_avatar_service import (
    _MIME_BY_SUFFIX,
    avatar_path_column,
    avatar_version_column,
    delete_user_avatar_files,
    public_avatar_url_for_user,
    resolve_avatar_file,
    save_user_avatar,
)

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)


from modstore_server.market_auth_api_part01 import (
    _fhd_cs_bridge_base as _fhd_cs_bridge_base,
    _cs_bridge_mod_id as _cs_bridge_mod_id,
    _default_cs_intake_webhook_url as _default_cs_intake_webhook_url,
    _default_landing_funnel_webhook_url as _default_landing_funnel_webhook_url,
    _resolve_market_user_id_by_email as _resolve_market_user_id_by_email,
    _notify_cs_intake_webhook as _notify_cs_intake_webhook,
    _require_internal_api_key as _require_internal_api_key,
    api_public_contact_submit as api_public_contact_submit,
    api_public_contact_company_match as api_public_contact_company_match,
    api_workbench_company_match as api_workbench_company_match,
    api_internal_payment_summary as api_internal_payment_summary,
    api_internal_cs_intake_latest as api_internal_cs_intake_latest,
    api_internal_contact_by_audit_code as api_internal_contact_by_audit_code,
    EnsureEnterpriseProfileDTO as EnsureEnterpriseProfileDTO,
    api_internal_cs_intake_ensure_enterprise_profile as api_internal_cs_intake_ensure_enterprise_profile,
    api_internal_cs_intake_enterprise_account as api_internal_cs_intake_enterprise_account,
    IssueEnterprisePasswordDTO as IssueEnterprisePasswordDTO,
    api_internal_cs_intake_issue_enterprise_password as api_internal_cs_intake_issue_enterprise_password,
    LinkCrmDTO as LinkCrmDTO,
    api_internal_contact_link_crm as api_internal_contact_link_crm,
    RegisterDTO as RegisterDTO,
    LoginDTO as LoginDTO,
    SendCodeDTO as SendCodeDTO,
    LoginWithCodeDTO as LoginWithCodeDTO,
    RefreshTokenDTO as RefreshTokenDTO,
    ResetPasswordDTO as ResetPasswordDTO,
    AdminResetUserPasswordDTO as AdminResetUserPasswordDTO,
    ProfileUpdateDTO as ProfileUpdateDTO,
    PasswordChangeDTO as PasswordChangeDTO,
    _normalize_email as _normalize_email,
    _delete_unused_verification_code as _delete_unused_verification_code,
    _background_send_verification_email as _background_send_verification_email,
    _verify_and_consume_verification_code as _verify_and_consume_verification_code,
)


from modstore_server.market_auth_api_part02 import (
    api_register as api_register,
    api_login as api_login,
    InternalSsoIssueTokenDTO as InternalSsoIssueTokenDTO,
    api_internal_sso_issue_token as api_internal_sso_issue_token,
    api_me as api_me,
    api_upload_avatar as api_upload_avatar,
    api_delete_avatar as api_delete_avatar,
    api_avatar_file as api_avatar_file,
    api_send_code as api_send_code,
    api_send_register_code as api_send_register_code,
    api_login_with_code as api_login_with_code,
    api_send_reset_password_code as api_send_reset_password_code,
    api_reset_password as api_reset_password,
    api_update_profile as api_update_profile,
    api_change_password as api_change_password,
    api_admin_reset_user_password as api_admin_reset_user_password,
    api_refresh_token as api_refresh_token,
    SendPhoneCodeDTO as SendPhoneCodeDTO,
    LoginWithPhoneCodeDTO as LoginWithPhoneCodeDTO,
    api_send_phone_code as api_send_phone_code,
    api_login_with_phone_code as api_login_with_phone_code,
    VerifyAdminDigestCodeDTO as VerifyAdminDigestCodeDTO,
    normalize_admin_digest_code as normalize_admin_digest_code,
    api_verify_admin_digest_code as api_verify_admin_digest_code,
    AccountDeleteDTO as AccountDeleteDTO,
    api_account_delete as api_account_delete,
    api_account_export as api_account_export,
    api_admin_status as api_admin_status,
)

from modstore_server.browser_handoff_api import router as browser_handoff_router

router.include_router(browser_handoff_router)
