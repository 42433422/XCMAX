"""Bridge XCAGI local UI to the Xiuci market account APIs."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections.abc import Mapping
from hashlib import sha256
from typing import Any

import httpx
from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app.application import market_account_live as _market_account_live
from app.application.market_auth_payloads import (
    market_identity_from_payloads as _market_identity_from_payloads,
)
from app.application.market_auth_payloads import (
    market_lifecycle_from_payloads as _market_lifecycle_from_payloads,
)
from app.application.market_auth_payloads import (
    market_user_id_from_auth_payload as _market_user_id_from_auth_payload,
)
from app.application.market_auth_payloads import (
    truthy_identity_flag as _truthy_identity_flag,
)
from app.application.market_auth_payloads import (
    user_blob_from_market_payload as _user_blob_from_market_payload,  # noqa: F401
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

router = APIRouter(prefix="/api/market", tags=["market-account"])
logger = logging.getLogger(__name__)
_MARKET_SESSION_TOKENS: dict[str, str] = {}
_MARKET_SESSION_REFRESH_TOKENS: dict[str, str] = {}
_ACCOUNT_OVERVIEW_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_bootstrap_overview_needs_live_merge = _market_account_live.bootstrap_overview_needs_live_merge


from app.fastapi_routes.market_account_part01 import (
    _account_overview_cache_ttl as _account_overview_cache_ttl,
)
from app.fastapi_routes.market_account_part01 import (
    _auth_header as _auth_header,
)
from app.fastapi_routes.market_account_part01 import (
    _authorization_from_request as _authorization_from_request,
)
from app.fastapi_routes.market_account_part01 import (
    _authorization_from_request_resolved as _authorization_from_request_resolved,
)
from app.fastapi_routes.market_account_part01 import (
    _body_snippet as _body_snippet,
)
from app.fastapi_routes.market_account_part01 import (
    _error_message as _error_message,
)
from app.fastapi_routes.market_account_part01 import (
    _market_base_url as _market_base_url,
)
from app.fastapi_routes.market_account_part01 import (
    _market_http_retries as _market_http_retries,
)
from app.fastapi_routes.market_account_part01 import (
    _market_http_timeout as _market_http_timeout,
)
from app.fastapi_routes.market_account_part01 import (
    _normalize_bearer_token as _normalize_bearer_token,
)
from app.fastapi_routes.market_account_part01 import (
    _overview_cache_key as _overview_cache_key,
)
from app.fastapi_routes.market_account_part01 import (
    _proxy_error_http_status as _proxy_error_http_status,
)
from app.fastapi_routes.market_account_part01 import (
    _transport_error_message as _transport_error_message,
)
from app.fastapi_routes.market_account_part01 import (
    _user_id_from_session as _user_id_from_session,
)
from app.fastapi_routes.market_account_part01 import (
    bind_market_auth_to_session as bind_market_auth_to_session,
)
from app.fastapi_routes.market_account_part01 import (
    clear_session_market_token as clear_session_market_token,
)
from app.fastapi_routes.market_account_part01 import (
    latest_session_market_refresh_token as latest_session_market_refresh_token,
)
from app.fastapi_routes.market_account_part01 import (
    latest_session_market_token as latest_session_market_token,
)
from app.fastapi_routes.market_account_part01 import (
    market_session_handoff as market_session_handoff,
)
from app.fastapi_routes.market_account_part01 import (
    save_session_market_token as save_session_market_token,
)
from app.fastapi_routes.market_account_part01 import (
    session_id_from_request as session_id_from_request,
)
from app.fastapi_routes.market_account_part01 import (
    session_market_refresh_token as session_market_refresh_token,
)
from app.fastapi_routes.market_account_part01 import (
    session_market_token as session_market_token,
)
from app.fastapi_routes.market_account_part02 import (
    _demo_market_login_payload as _demo_market_login_payload,
)
from app.fastapi_routes.market_account_part02 import (
    _is_local_market_base as _is_local_market_base,
)
from app.fastapi_routes.market_account_part02 import (
    _looks_like_verification_required as _looks_like_verification_required,
)
from app.fastapi_routes.market_account_part02 import (
    _market_validate_fast_timeout as _market_validate_fast_timeout,
)
from app.fastapi_routes.market_account_part02 import (
    _normalize_market_auth_payload as _normalize_market_auth_payload,
)
from app.fastapi_routes.market_account_part02 import (
    _proxy_json as _proxy_json,
)
from app.fastapi_routes.market_account_part02 import (
    _refresh_token_from_auth_response as _refresh_token_from_auth_response,
)
from app.fastapi_routes.market_account_part02 import (
    _register_without_verification as _register_without_verification,
)
from app.fastapi_routes.market_account_part02 import (
    _token_from_auth_response as _token_from_auth_response,
)
from app.fastapi_routes.market_account_part02 import (
    fetch_market_membership_tier as fetch_market_membership_tier,
)
from app.fastapi_routes.market_account_part02 import (
    market_login as market_login,
)
from app.fastapi_routes.market_account_part02 import (
    market_membership_plans as market_membership_plans,
)
from app.fastapi_routes.market_account_part02 import (
    market_register as market_register,
)
from app.fastapi_routes.market_account_part02 import (
    refresh_session_market_token as refresh_session_market_token,
)
from app.fastapi_routes.market_account_part02 import (
    register_market_user as register_market_user,
)
from app.fastapi_routes.market_account_part02 import (
    reset_market_password_with_code as reset_market_password_with_code,
)
from app.fastapi_routes.market_account_part02 import (
    resolve_valid_market_access_token as resolve_valid_market_access_token,
)
from app.fastapi_routes.market_account_part02 import (
    resolve_valid_market_access_token_fast as resolve_valid_market_access_token_fast,
)
from app.fastapi_routes.market_account_part02 import (
    send_market_register_code as send_market_register_code,
)
from app.fastapi_routes.market_account_part02 import (
    send_market_reset_password_code as send_market_reset_password_code,
)
from app.fastapi_routes.market_account_part03 import (
    _dedupe_mod_ids as _dedupe_mod_ids,
)
from app.fastapi_routes.market_account_part03 import (
    _degraded_account_overview as _degraded_account_overview,
)
from app.fastapi_routes.market_account_part03 import (
    _legacy_account_overview as _legacy_account_overview,
)
from app.fastapi_routes.market_account_part03 import (
    _market_auth_from_request as _market_auth_from_request,
)
from app.fastapi_routes.market_account_part03 import (
    _market_internal_api_key as _market_internal_api_key,
)
from app.fastapi_routes.market_account_part03 import (
    _market_llm_catalog_impl as _market_llm_catalog_impl,
)
from app.fastapi_routes.market_account_part03 import (
    _merge_live_overview_fields as _merge_live_overview_fields,
)
from app.fastapi_routes.market_account_part03 import (
    _oidc_identity_from_profile as _oidc_identity_from_profile,
)
from app.fastapi_routes.market_account_part03 import (
    ensure_market_enterprise_profile as ensure_market_enterprise_profile,
)
from app.fastapi_routes.market_account_part03 import (
    enterprise_mod_ids_for_industry as enterprise_mod_ids_for_industry,
)
from app.fastapi_routes.market_account_part03 import (
    grant_market_enterprise_entitlements_for_session as grant_market_enterprise_entitlements_for_session,
)
from app.fastapi_routes.market_account_part03 import (
    login_market_for_oidc_profile as login_market_for_oidc_profile,
)
from app.fastapi_routes.market_account_part03 import (
    login_market_with_password as login_market_with_password,
)
from app.fastapi_routes.market_account_part03 import (
    login_market_with_phone_code as login_market_with_phone_code,
)
from app.fastapi_routes.market_account_part03 import (
    market_account_overview as market_account_overview,
)
from app.fastapi_routes.market_account_part03 import (
    market_account_sync as market_account_sync,
)
from app.fastapi_routes.market_account_part03 import (
    market_llm_catalog_get as market_llm_catalog_get,
)
from app.fastapi_routes.market_account_part03 import (
    market_llm_catalog_post as market_llm_catalog_post,
)
from app.fastapi_routes.market_account_part03 import (
    market_login_with_phone_code_route as market_login_with_phone_code_route,
)
from app.fastapi_routes.market_account_part03 import (
    market_payment_checkout as market_payment_checkout,
)
from app.fastapi_routes.market_account_part03 import (
    market_payment_plans as market_payment_plans,
)
from app.fastapi_routes.market_account_part03 import (
    market_send_phone_code as market_send_phone_code,
)
from app.fastapi_routes.market_account_part03 import (
    market_send_register_code as market_send_register_code,
)
from app.fastapi_routes.market_account_part03 import (
    send_market_phone_code as send_market_phone_code,
)
from app.fastapi_routes.market_account_part04 import (
    _checkout_body_has_signature as _checkout_body_has_signature,
)
from app.fastapi_routes.market_account_part04 import (
    _checkout_sign_body_from_request as _checkout_sign_body_from_request,
)
from app.fastapi_routes.market_account_part04 import (
    _resolve_market_authorization_for_checkout as _resolve_market_authorization_for_checkout,
)
from app.fastapi_routes.market_account_part04 import (
    market_dev_create_account as market_dev_create_account,
)
from app.fastapi_routes.market_account_part04 import (
    market_payment_direct_checkout as market_payment_direct_checkout,
)
from app.fastapi_routes.market_account_part04 import (
    market_payment_orders as market_payment_orders,
)
from app.fastapi_routes.market_account_part04 import (
    market_payment_query as market_payment_query,
)
from app.fastapi_routes.market_account_part04 import (
    market_status as market_status,
)
from app.fastapi_routes.market_account_part04 import (
    market_wallet_overview as market_wallet_overview,
)
# ruff: noqa: F401
