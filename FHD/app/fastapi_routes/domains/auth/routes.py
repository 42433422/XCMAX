"""Migrated from legacy_auth.py (v10)."""

from __future__ import annotations

import logging
import os
from typing import Any, Literal, cast

from fastapi import APIRouter, Body, Depends, File, Query, Request, Response, UploadFile
from fastapi.background import BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse

import app.application.enterprise_registration_response as registration_response
from app.http.error_codes import (
    ACCOUNT_DISABLED,
    CREATE_FAILED,
    INVALID_FILE,
    INVALID_INPUT,
    INVALID_ROLE,
    INVALID_SESSION,
    LOCAL_LOGIN_AFTER_REGISTER,
    LOGIN_AFTER_REGISTER,
    MARKET_NOT_BOUND,
    MARKET_REGISTER_FAILED,
    MARKET_RESET_FAILED,
    MISSING_PASSWORD,
    NO_SESSION,
    NOT_FOUND,
    QR_NOT_FOUND,
    REGISTRATION_DISABLED,
    SAVE_FAILED,
    SELF_DELETE,
    SEND_CODE_FAILED,
    UNAUTHORIZED,
    UPDATE_FAILED,
    WEAK_PASSWORD,
    error_envelope,
)
from app.infrastructure.auth.dependencies import (
    get_logged_in_user,
    require_permission,
    resolve_session_user,
    session_id_from_request,
)
from app.utils.operational_errors import INFRA_TRANSIENT, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-auth"], deprecated=True)

_require_admin = require_permission("admin.manage_users")


from app.fastapi_routes.domains.auth.routes_part01 import (
    _account_profile_fields as _account_profile_fields,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    _attach_session_cookie as _attach_session_cookie,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    _enrich_register_with_tenant as _enrich_register_with_tenant,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    _find_local_users_by_email as _find_local_users_by_email,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    _jit_create_local_user_for_enterprise as _jit_create_local_user_for_enterprise,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    _market_user_email_from_raw as _market_user_email_from_raw,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    _normalize_auth_email as _normalize_auth_email,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    _open_registration_allowed as _open_registration_allowed,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    _session_meta_for_response as _session_meta_for_response,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    _sync_local_password_for_email as _sync_local_password_for_email,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    _user_public_dict as _user_public_dict,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    auth_forgot_account as auth_forgot_account,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    auth_forgot_password_reset as auth_forgot_password_reset,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    auth_forgot_password_send_code as auth_forgot_password_send_code,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    auth_me as auth_me,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    auth_mfa_disable as auth_mfa_disable,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    auth_mfa_enable as auth_mfa_enable,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    auth_mfa_setup as auth_mfa_setup,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    auth_session_validate as auth_session_validate,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    auth_subscription_status as auth_subscription_status,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    auth_token_refresh as auth_token_refresh,
)
from app.fastapi_routes.domains.auth.routes_part01 import (
    runtime_product_sku as runtime_product_sku,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_login as auth_login,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_login_with_phone_code as auth_login_with_phone_code,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_logout as auth_logout,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_oidc_callback as auth_oidc_callback,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_oidc_start as auth_oidc_start,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_oidc_status as auth_oidc_status,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_password_change as auth_password_change,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_profile_avatar_get as auth_profile_avatar_get,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_profile_avatar_upload as auth_profile_avatar_upload,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_profile_get as auth_profile_get,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_profile_patch as auth_profile_patch,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_qr_issue as auth_qr_issue,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_qr_status as auth_qr_status,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_register as auth_register,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    auth_update_company_brand as auth_update_company_brand,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    users_create as users_create,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    users_delete as users_delete,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    users_get as users_get,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    users_list as users_list,
)
from app.fastapi_routes.domains.auth.routes_part02 import (
    users_update as users_update,
)
from app.fastapi_routes.domains.auth.routes_part03 import (
    users_reset_password as users_reset_password,
)
# ruff: noqa: F401
