"""Bridge XCAGI local UI to the Xiuci market account APIs.

Public adapters assemble explicit component dependencies at call time so existing
integrations can continue patching this module's transport and credential ports.
"""

from __future__ import annotations

import json as json
import logging
import os as os
import re
import time
import uuid
from collections.abc import Mapping as Mapping
from hashlib import sha256
from typing import Any

import httpx
from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse as JSONResponse

from app.application import market_account_live as _market_account_live
from app.application import market_auth_payloads as _market_payloads
from app.application.market_auth_payloads import (
    market_identity_from_payloads as _market_identity_from_payloads,
)
from app.application.market_auth_payloads import (
    market_lifecycle_from_payloads as _market_lifecycle_from_payloads,
)
from app.application.market_auth_payloads import (
    market_user_id_from_auth_payload as _market_user_id_from_auth_payload,
)
from app.application.market_auth_payloads import truthy_identity_flag as _truthy_identity_flag
from app.utils.operational_errors import RECOVERABLE_ERRORS as RECOVERABLE_ERRORS

from .market_bridge import bindings, http_transport
from .market_bridge.account_views import AccountViews
from .market_bridge.account_views import _merge_live_overview_fields as _merge_live_overview_fields
from .market_bridge.auth_payloads import AuthPayloads
from .market_bridge.auth_payloads import _demo_market_login_payload as _demo_market_login_payload
from .market_bridge.auth_payloads import _is_local_market_base as _is_local_market_base
from .market_bridge.auth_payloads import (
    _refresh_token_from_auth_response as _refresh_token_from_auth_response,
)
from .market_bridge.auth_payloads import _token_from_auth_response as _token_from_auth_response
from .market_bridge.authentication import Authentication
from .market_bridge.diagnostics import MarketDiagnostics
from .market_bridge.enterprise import EnterpriseAccounts
from .market_bridge.enterprise import _dedupe_mod_ids as _dedupe_mod_ids
from .market_bridge.http_transport import MarketHTTP
from .market_bridge.http_transport import _auth_header as _auth_header
from .market_bridge.http_transport import _body_snippet as _body_snippet
from .market_bridge.http_transport import _normalize_bearer_token as _normalize_bearer_token
from .market_bridge.http_transport import _proxy_error_http_status as _proxy_error_http_status
from .market_bridge.identity_routes import IdentityRoutes
from .market_bridge.membership import Membership
from .market_bridge.oidc import OIDCBridge
from .market_bridge.oidc import _oidc_identity_from_profile as _oidc_identity_from_profile
from .market_bridge.payments import Payments
from .market_bridge.payments import _checkout_body_has_signature as _checkout_body_has_signature
from .market_bridge.payments import (
    _checkout_sign_body_from_request as _checkout_sign_body_from_request,
)
from .market_bridge.request_identity import RequestIdentity
from .market_bridge.request_identity import session_id_from_request as session_id_from_request
from .market_bridge.session_tokens import SessionTokens, SQLSessionTokens
from .market_bridge.settings import _account_overview_cache_ttl as _account_overview_cache_ttl
from .market_bridge.settings import _market_api_base_url as _market_api_base_url
from .market_bridge.settings import _market_base_url as _market_base_url
from .market_bridge.settings import _market_http_retries as _market_http_retries
from .market_bridge.settings import _market_http_timeout as _market_http_timeout
from .market_bridge.settings import _market_internal_api_key as _market_internal_api_key
from .market_bridge.settings import _market_validate_fast_timeout as _market_validate_fast_timeout
from .market_bridge.token_lifecycle import TokenLifecycle
from .market_browser_handoff import router as browser_handoff_router

router = APIRouter(prefix="/api/market", tags=["market-account"])
logger = logging.getLogger(__name__)
_MARKET_SESSION_TOKENS: dict[str, str] = {}
_MARKET_SESSION_REFRESH_TOKENS: dict[str, str] = {}
_ACCOUNT_OVERVIEW_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_bootstrap_overview_needs_live_merge = _market_account_live.bootstrap_overview_needs_live_merge
_user_blob_from_market_payload = _market_payloads.user_blob_from_market_payload


def _http_transport() -> MarketHTTP:
    return MarketHTTP(
        client=lambda timeout: httpx.AsyncClient(timeout=timeout, trust_env=False),
        api_base_url=_market_api_base_url,
        base_url=_market_base_url,
        auth_header=_auth_header,
        timeout=_market_http_timeout,
        attempts=_market_http_retries,
        error_message=_error_message,
        transport_error=_transport_error_message,
        body_snippet=_body_snippet,
        logger=logger,
    )


def _session_tokens() -> SessionTokens:
    return SessionTokens(
        _MARKET_SESSION_TOKENS,
        _MARKET_SESSION_REFRESH_TOKENS,
        SQLSessionTokens(bindings.database, bindings.session_model),
        logger,
    )


def _request_identity() -> RequestIdentity:
    return RequestIdentity(
        session_id=session_id_from_request,
        access_token=session_market_token,
        refresh_token=session_market_refresh_token,
        latest_token=latest_session_market_token,
        user_id=_user_id_from_session,
        current_user=bindings.current_user,
        normalize=_normalize_bearer_token,
        auth_header=_auth_header,
        resolve_token=resolve_valid_market_access_token,
        save=save_session_market_token,
        fallback_auth=_authorization_from_request,
        base_url=_market_base_url,
        sync_entitlements=bindings.sync_entitlements,
        proxy=_proxy_json,
        logger=logger,
    )


def _token_lifecycle() -> TokenLifecycle:
    return TokenLifecycle(
        access_token=session_market_token,
        refresh_token=session_market_refresh_token,
        latest_token=latest_session_market_token,
        user_id=_user_id_from_session,
        normalize=_normalize_bearer_token,
        access_from_payload=_token_from_auth_response,
        refresh_from_payload=_refresh_token_from_auth_response,
        save=save_session_market_token,
        proxy=_proxy_json,
        refresh_session=refresh_session_market_token,
        is_demo=bindings.is_demo_token,
        proxy_status=_proxy_error_http_status,
        fast_timeout=_market_validate_fast_timeout,
        logger=logger,
    )


def _auth_payloads() -> AuthPayloads:
    return AuthPayloads(
        proxy=_proxy_json,
        base_url=_market_base_url,
        error_message=_error_message,
        access_token=_token_from_auth_response,
        refresh_token=_refresh_token_from_auth_response,
        identity=_market_identity_from_payloads,
        lifecycle=_market_lifecycle_from_payloads,
        logger=logger,
    )


def _authentication() -> Authentication:
    return Authentication(
        proxy=_proxy_json,
        base_url=_market_base_url,
        error_message=_error_message,
        normalize_auth=_normalize_market_auth_payload,
        user_id=_market_user_id_from_auth_payload,
        try_demo=bindings.try_demo_login,
        is_local_base=_is_local_market_base,
        demo_payload=_demo_market_login_payload,
    )


def _identity_routes() -> IdentityRoutes:
    return IdentityRoutes(
        register_user=register_market_user,
        password_login=login_market_with_password,
        phone_login=login_market_with_phone_code,
        send_phone_code=send_market_phone_code,
        send_register_code=send_market_register_code,
        bind_session=bind_market_auth_to_session,
        base_url=_market_base_url,
    )


def _enterprise_accounts() -> EnterpriseAccounts:
    return EnterpriseAccounts(
        proxy=_proxy_json,
        base_url=_market_base_url,
        internal_key=_market_internal_api_key,
        error_message=_error_message,
        truthy=_truthy_identity_flag,
        dedupe=_dedupe_mod_ids,
        industry_seed=bindings.industry_seed,
        industry_alias=bindings.industry_alias,
        deliveries=bindings.deliveries,
        session_meta=bindings.session_meta,
        claim_user_id=bindings.claim_user_id,
        resolve_token=resolve_valid_market_access_token,
        ensure_profile=ensure_market_enterprise_profile,
        industry_mods=enterprise_mod_ids_for_industry,
        logger=logger,
    )


def _oidc_bridge() -> OIDCBridge:
    return OIDCBridge(
        proxy=_proxy_json,
        base_url=_market_base_url,
        profile_identity=_oidc_identity_from_profile,
        normalize_token=_normalize_bearer_token,
        identity=_market_identity_from_payloads,
        internal_key=_market_internal_api_key,
        normalize_auth=_normalize_market_auth_payload,
    )


def _account_views() -> AccountViews:
    return AccountViews(
        proxy=_proxy_json,
        base_url=_market_base_url,
        resolved_auth=_authorization_from_request_resolved,
        cache=_ACCOUNT_OVERVIEW_CACHE,
        clock=time.monotonic,
        cache_ttl=_account_overview_cache_ttl,
        cache_key=_overview_cache_key,
        degraded=_degraded_account_overview,
        legacy_overview=_legacy_account_overview,
        merge_live=_merge_live_overview_fields,
        needs_live_merge=_market_account_live.bootstrap_overview_needs_live_merge,
        refresh_wallet=_market_account_live.refresh_overview_wallet,
        degraded_catalog=_market_account_live.degraded_llm_catalog,
        error_message=_error_message,
        logger=logger,
    )


def _membership() -> Membership:
    return Membership(proxy=_proxy_json, logger=logger)


def _payments() -> Payments:
    return Payments(
        proxy=_proxy_json,
        error_message=_error_message,
        base_url=_market_base_url,
        request_auth=_market_auth_from_request,
        resolved_auth=_authorization_from_request_resolved,
        checkout_auth=_resolve_market_authorization_for_checkout,
        sign_body=_checkout_sign_body_from_request,
    )


def _diagnostics() -> MarketDiagnostics:
    return MarketDiagnostics(
        proxy=_proxy_json,
        base_url=_market_base_url,
        register_open=_register_without_verification,
        access_token=_token_from_auth_response,
        error_message=_error_message,
        new_id=uuid.uuid4,
    )


def bind_market_auth_to_session(request: Request, market_result: dict[str, Any]) -> tuple[str, str]:
    return _request_identity().bind(request, market_result)


def save_session_market_token(
    session_id: str, token: str, refresh_token: str | None = None
) -> None:
    return _session_tokens().save(session_id, token, refresh_token)


def clear_session_market_token(session_id: str) -> None:
    return _session_tokens().clear(session_id)


def session_market_token(session_id: str) -> str:
    return _session_tokens().read(session_id, "access")


def session_market_refresh_token(session_id: str) -> str:
    return _session_tokens().read(session_id, "refresh")


def latest_session_market_refresh_token() -> str:
    return _session_tokens().latest("refresh")


def latest_session_market_token(user_id: int | None = None) -> str:
    return _session_tokens().latest("access", user_id)


def _user_id_from_session(session_id: str) -> int | None:
    return _session_tokens().owner(session_id)


@router.get("/session-handoff")
async def market_session_handoff(request: Request):
    """Return credentials only to their verified local session, for API calls.

    Browser navigation uses POST /browser-handoff. Anonymous, mismatched and
    unavailable sessions must never borrow another session's credentials.
    """
    return await _request_identity().handoff(request)


def _authorization_from_request(request: Request, body: dict[str, Any]) -> str:
    return _request_identity().authorization(request, body)


async def _authorization_from_request_resolved(request: Request, body: dict[str, Any]) -> str:
    return await _request_identity().resolved_authorization(request, body)


def _error_message(payload: Any, status_code: int) -> str:
    return http_transport.error_message(payload, status_code, base_url=_market_base_url())


def _overview_cache_key(authorization: str) -> str:
    return sha256(_auth_header(authorization).encode("utf-8")).hexdigest()


def _transport_error_message(exc: Exception) -> tuple[str, int]:
    return http_transport.transport_error(exc, base_url=_market_base_url())


async def _proxy_json(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    authorization: str = "",
    extra_headers: dict[str, str] | None = None,
    return_error_payload: bool = False,
    sensitive: bool = False,
    timeout: float | None = None,
    retries: int | None = None,
):
    return await _http_transport().request(
        method,
        path,
        json_body=json_body,
        authorization=authorization,
        extra_headers=extra_headers,
        return_error_payload=return_error_payload,
        sensitive=sensitive,
        timeout=timeout,
        retries=retries,
    )


async def fetch_market_membership_tier(market_token: str) -> str | None:
    return await _membership().tier(market_token)


@router.get("/membership-plans")
async def market_membership_plans():
    """会员套餐列表（代理市场公开接口 ``GET /api/payment/plans``）。

    供 ModelPaymentView 读取，替代前端硬编码；市场不可达时返回空列表，前端用本地 FALLBACK。
    """
    return await _membership().plans()


async def refresh_session_market_token(session_id: str) -> str:
    return await _token_lifecycle().refresh(session_id)


async def resolve_valid_market_access_token(session_id: str) -> str:
    return await _token_lifecycle().resolve(session_id)


async def resolve_valid_market_access_token_fast(session_id: str) -> str:
    return await _token_lifecycle().resolve(session_id, fast=True)


def _looks_like_verification_required(payload: Any) -> bool:
    """Classify a market response without changing registration behavior."""
    msg = _error_message(payload, 400)
    return bool(re.search("验证码|verification|code", msg, re.I))


async def _register_without_verification(username: str, password: str, email: str):
    return await _diagnostics().register_diagnostic(username, password, email)


async def send_market_reset_password_code(email: str) -> dict[str, Any]:
    return await _authentication().send_reset_code(email)


async def send_market_register_code(email: str) -> dict[str, Any]:
    return await _authentication().send_register_code(email)


async def reset_market_password_with_code(
    email: str, code: str, new_password: str
) -> dict[str, Any]:
    return await _authentication().reset_password(email, code, new_password)


async def register_market_user(
    username: str, password: str, email: str, verification_code: str = ""
) -> dict[str, Any]:
    return await _authentication().register(username, password, email, verification_code)


@router.post("/register")
async def market_register(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    """Register a Xiuci market account through the configured market server."""
    return await _identity_routes().register(request, body)


@router.post("/login")
async def market_login(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    """Login to Xiuci market (username/password) and bind JWT to the current FHD session.

    Prefer ``POST /api/auth/login`` for the desktop app; this route remains for
    settings/tools that only need market credentials. Token-only bind: ``POST /account-sync``.
    """
    return await _identity_routes().login(request, body)


async def _normalize_market_auth_payload(
    payload: Any, *, market_base: str | None = None
) -> dict[str, Any]:
    return await _auth_payloads().normalize(payload, market_base=market_base)


async def login_market_with_password(username: str, password: str) -> dict[str, Any]:
    return await _authentication().password_login(username, password)


async def login_market_with_phone_code(phone: str, code: str) -> dict[str, Any]:
    return await _authentication().phone_login(phone, code)


async def ensure_market_enterprise_profile(
    market_user_id: int | str | None,
    *,
    username: str = "",
    company: str = "",
    mod_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    return await _enterprise_accounts().ensure(
        market_user_id, username=username, company=company, mod_ids=mod_ids
    )


def enterprise_mod_ids_for_industry(industry_id: str) -> list[str]:
    return _enterprise_accounts().mod_ids(industry_id)


async def grant_market_enterprise_entitlements_for_session(
    session_id: str, industry_id: str
) -> dict[str, Any]:
    return await _enterprise_accounts().grant(session_id, industry_id)


async def login_market_for_oidc_profile(
    profile: dict[str, Any], *, oidc_access_token: str = ""
) -> dict[str, Any]:
    return await _oidc_bridge().login(profile, oidc_access_token=oidc_access_token)


async def send_market_phone_code(phone: str) -> dict[str, Any]:
    return await _authentication().send_phone_code(phone)


@router.post("/send-phone-code")
async def market_send_phone_code(body: dict[str, Any] = Body(default_factory=dict)):
    return await _identity_routes().phone_code(body)


@router.post("/send-register-code")
async def market_send_register_code(body: dict[str, Any] = Body(default_factory=dict)):
    return await _identity_routes().registration_code(body)


@router.post("/login-with-phone-code")
async def market_login_with_phone_code_route(body: dict[str, Any] = Body(default_factory=dict)):
    return await _identity_routes().phone_login_route(body)


@router.post("/account-sync")
async def market_account_sync(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    return await _request_identity().sync(request, body)


def _degraded_account_overview(message: str) -> dict[str, Any]:
    return _account_views().degraded_overview(message)


@router.post("/account-overview")
async def market_account_overview(
    request: Request, body: dict[str, Any] = Body(default_factory=dict)
):
    return await _account_views().overview(request, body)


async def _market_llm_catalog_impl(request: Request, body: dict[str, Any]):
    return await _account_views().catalog(request, body)


@router.post("/llm-catalog")
async def market_llm_catalog_post(
    request: Request, body: dict[str, Any] = Body(default_factory=dict)
):
    return await _market_llm_catalog_impl(request, body)


@router.get("/llm-catalog")
async def market_llm_catalog_get(request: Request, refresh: bool = False):
    return await _market_llm_catalog_impl(request, {"refresh": refresh})


async def _legacy_account_overview(authorization: str) -> dict[str, Any]:
    return await _account_views().legacy(authorization)


def _market_auth_from_request(request: Request) -> str:
    return _request_identity().market_auth(request)


@router.get("/payment/plans")
async def market_payment_plans(request: Request):
    """修茈市场套餐（含微信/支付宝统一收银，Java SoT）。"""
    return await _payments().plans(request)


@router.post("/payment/checkout")
async def market_payment_checkout(
    request: Request, body: dict[str, Any] = Body(default_factory=dict)
):
    return await _payments().checkout(request, body)


async def _resolve_market_authorization_for_checkout(
    request: Request, body: dict[str, Any]
) -> tuple[str, dict[str, Any] | None]:
    return (await _authorization_from_request_resolved(request, body), None)


@router.post("/payment/direct-checkout")
async def market_payment_direct_checkout(
    request: Request, body: dict[str, Any] = Body(default_factory=dict)
):
    return await _payments().direct_checkout(request, body)


@router.get("/payment/orders")
async def market_payment_orders(
    request: Request, status: str | None = None, limit: int = 50, offset: int = 0
):
    return await _payments().orders(request, status, limit, offset)


@router.get("/payment/query/{out_trade_no}")
async def market_payment_query(request: Request, out_trade_no: str):
    return await _payments().query(request, out_trade_no)


@router.get("/wallet/overview")
async def market_wallet_overview(request: Request):
    return await _payments().wallet(request)


@router.get("/status")
async def market_status():
    """Check whether the local backend can reach the configured Xiuci market server."""
    return await _diagnostics().status()


@router.post("/dev-create-account")
async def market_dev_create_account(body: dict[str, Any] = Body(default_factory=dict)):
    """Create a market account via server-side open API and verify login/overview connectivity."""
    return await _diagnostics().create_account(body)


router.include_router(browser_handoff_router)
