"""Legacy authentication HTTP contracts and explicit component assembly."""

from __future__ import annotations

import logging
import os
import time
from typing import cast as cast

from fastapi import APIRouter, Request, Response
from fastapi import Body as Body
from fastapi import Depends as Depends
from fastapi import File as File
from fastapi import Query as Query
from fastapi import UploadFile as UploadFile
from fastapi.background import BackgroundTasks as BackgroundTasks

import app.domain.app_pure.enterprise_registration_response as registration_response
from app.db.models.user import User
from app.infrastructure.auth.dependencies import (
    get_logged_in_user,
    require_permission,
    resolve_session_user,
    session_id_from_request,
)
from app.utils.operational_errors import INFRA_TRANSIENT, RECOVERABLE_ERRORS

from .account_profile import AccountProfile
from .account_profile import public_user as _user_public_dict
from .account_recovery import AccountRecovery, optional_local_reset_code
from .account_recovery import normalize_email as _normalize_auth_email
from .account_security import AccountSecurity
from .administration_routes import AdministrationRoutes
from .credential_login import CredentialLogin
from .credential_routes import CredentialRoutes
from .federated_login import FederatedLogin
from .federated_routes import FederatedRoutes
from .ports import JsonObject
from .profile_routes import ProfileRoutes
from .recovery_routes import RecoveryRoutes
from .registration import Registration, open_registration_allowed
from .registration import market_user_email as _market_user_email_from_raw
from .security_routes import SecurityRoutes
from .session_access import SessionAccess
from .session_access import account_profile_fields as _account_profile_fields
from .session_cookies import SessionCookies
from .session_routes import SessionRoutes
from .user_administration import UserAdministration

logger = logging.getLogger(__name__)
router = APIRouter(tags=["legacy-auth"], deprecated=True)
_require_admin = require_permission("admin.manage_users")


def _sessions() -> SessionAccess:
    from app.application import (
        auth_app_service,
        desktop_admin_gate,
        session_account_meta,
        tenant_rbac_policy,
        tenant_subscription_app_service,
    )
    from app.enterprise import mod_entitlements
    from app.fastapi_routes import market_account
    from app.mod_sdk import product_skus
    from app.security import web_jwt

    return SessionAccess(
        resolve_user=lambda request: resolve_session_user(request),
        session_id=lambda request: session_id_from_request(request),
        backend=lambda: auth_app_service.get_auth_app_service(),
        desktop_gate=lambda sid: desktop_admin_gate.assert_desktop_allows_session_id(sid),
        load_meta=lambda sid: session_account_meta.load_session_account_meta(sid),
        enrich_meta=lambda sid, user: session_account_meta.enrich_session_meta_with_tenant(
            sid, user
        ),
        session_meta=lambda request, user: _session_meta_for_response(request, user),
        public_user=lambda user: _user_public_dict(user),
        profile_fields=lambda user, meta: _account_profile_fields(user, meta),
        owner_permission=lambda user: tenant_rbac_policy.owner_permission_for_user(user),
        product_sku=lambda: product_skus.resolve_product_sku(),
        market_token=lambda sid: market_account.resolve_valid_market_access_token_fast(sid),
        sync_entitlements=lambda sid: mod_entitlements.sync_entitlements_for_session(sid),
        cached_entitlements=lambda: mod_entitlements.get_cached_entitled_client_mod_ids(),
        subscription=lambda uid: tenant_subscription_app_service.subscription_status_for_user(uid),
        refresh_tokens=lambda token: web_jwt.refresh_web_access_token(token),
        clear_market_token=lambda sid: market_account.clear_session_market_token(sid),
        clear_entitlements=lambda: mod_entitlements.clear_session_entitlements(),
        remove_cookie=lambda response: SessionCookies(os.environ).remove(response),
        infra_errors=lambda: INFRA_TRANSIENT,
        logger=logger,
    )


def _security() -> AccountSecurity:
    from app.application import account_security, auth_app_service
    from app.db import session

    return AccountSecurity(
        resolve_user=lambda request: resolve_session_user(request),
        database=lambda: session.get_db(),
        backend=lambda: auth_app_service.get_auth_app_service(),
        generate_secret=lambda: account_security.generate_totp_secret(),
        provisioning_uri=lambda secret, username: account_security.provisioning_uri(
            secret, username
        ),
        verify_totp=lambda secret, code: account_security.verify_totp(secret, code),
    )


def _recovery() -> AccountRecovery:
    from app.application import auth_app_service
    from app.db import session
    from app.fastapi_routes import market_account

    return AccountRecovery(
        database=lambda: session.get_db(),
        backend=lambda: auth_app_service.get_auth_app_service(),
        normalize_email=lambda email: _normalize_auth_email(email),
        find_users=lambda email: _find_local_users_by_email(email),
        sync_passwords=lambda email, password: _sync_local_password_for_email(email, password),
        send_local_code=lambda email: optional_local_reset_code(
            auth_app_service.get_auth_app_service(), email
        ),
        send_market_code=lambda email: market_account.send_market_reset_password_code(email),
        reset_market_password=lambda email, code, password: (
            market_account.reset_market_password_with_code(email, code, password)
        ),
        recoverable_errors=lambda: RECOVERABLE_ERRORS,
    )


def _registration() -> Registration:
    import app.application as application
    from app.application import (
        account_registration,
        auth_app_service,
        enterprise_login_flow,
        session_account_meta,
    )
    from app.db import session
    from app.fastapi_routes import market_account
    from app.mod_sdk import product_skus
    from app.utils import time as utc_clock
    from app.utils.security import password_hash

    return Registration(
        backend=lambda: auth_app_service.get_auth_app_service(),
        directory=lambda: application.get_user_app_service(),
        database=lambda: session.get_db(),
        product_sku=lambda: product_skus.resolve_product_sku(),
        register_market=lambda username, password, email, code: market_account.register_market_user(
            username, password, email, code
        ),
        login_market=lambda username, password: market_account.login_market_with_password(
            username, password
        ),
        save_market_token=lambda sid, token, refresh: market_account.save_session_market_token(
            sid, token, refresh
        ),
        pending_registration=lambda result: registration_response.pending_registration_payload(
            result
        ),
        market_email=lambda raw: _market_user_email_from_raw(raw),
        jit_create=lambda username, password, email: _jit_create_local_user_for_enterprise(
            username, password, email
        ),
        open_allowed=lambda sku: _open_registration_allowed(sku),
        enrich_result=lambda *, result, username, session_id, sku, company_brand="": (
            _enrich_register_with_tenant(
                result=result,
                username=username,
                session_id=session_id,
                sku=sku,
                company_brand=company_brand,
            )
        ),
        bind_tenant=lambda uid, brand, username: enterprise_login_flow.bind_tenant_for_login(
            user_id=uid, company_brand=brand, username=username
        ),
        normalize_kind=lambda raw, default: session_account_meta.normalize_account_kind(
            raw, default=default
        ),
        persist_meta=lambda sid, kind, brand, tenant: (
            session_account_meta.persist_session_account_meta(
                sid, account_kind=kind, company_brand=brand, tenant_id=tenant
            )
        ),
        apply_profile=lambda username, tier, industry, budget: (
            account_registration.apply_account_profile_on_register(
                username, tier=tier, industry_id=industry, budget_range=budget
            )
        ),
        hash_password=lambda password: password_hash.generate_password_hash(password),
        utc_now=lambda: utc_clock.utc_now_naive(),
        attach_cookie=lambda response, sid: _attach_session_cookie(response, sid),
        infra_errors=lambda: INFRA_TRANSIENT,
        logger=logger,
    )


def _credentials() -> CredentialLogin:
    from app.application import auth_app_service, enterprise_login_flow, session_account_meta
    from app.fastapi_routes import market_account
    from app.mod_sdk import product_skus
    from app.security import web_jwt
    from app.utils import metrics

    return CredentialLogin(
        backend=lambda: auth_app_service.get_auth_app_service(),
        product_sku=lambda: product_skus.resolve_product_sku(),
        normalize_kind=lambda raw, default: session_account_meta.normalize_account_kind(
            raw, default=default
        ),
        run_login=enterprise_login_flow.run_market_first_login,
        login_market=lambda username, password: market_account.login_market_with_password(
            username, password
        ),
        login_phone=lambda phone, code: market_account.login_market_with_phone_code(phone, code),
        jit_create=lambda username, password, email: _jit_create_local_user_for_enterprise(
            username, password, email
        ),
        market_email=lambda raw: _market_user_email_from_raw(raw),
        issue_tokens=lambda uid, username, kind, sid: web_jwt.issue_web_tokens(
            user_id=uid, username=username, account_kind=kind, session_id=sid
        ),
        attach_cookie=lambda response, sid: _attach_session_cookie(response, sid),
        clock=lambda: time.perf_counter(),
        observe_login=lambda method, duration: metrics.auth_login_duration_seconds.labels(
            auth_method=method
        ).observe(duration),
        infra_errors=lambda: INFRA_TRANSIENT,
        logger=logger,
    )


def _federated() -> FederatedLogin:
    from app.application import auth_app_service, enterprise_login_flow, session_account_meta
    from app.infrastructure.auth import oidc_provider
    from app.mod_sdk import product_skus
    from app.security import auth_qr_login

    return FederatedLogin(
        backend=lambda: auth_app_service.get_auth_app_service(),
        product_sku=lambda: product_skus.resolve_product_sku(),
        normalize_kind=lambda raw, default: session_account_meta.normalize_account_kind(
            raw, default=default
        ),
        enabled=lambda: oidc_provider.oidc_enabled(),
        frontend_path=lambda: oidc_provider.frontend_redirect_path(),
        sign_state=lambda return_to: oidc_provider.sign_oidc_state(return_to=return_to),
        verify_state=lambda state: oidc_provider.verify_oidc_state(state),
        authorize_url=lambda state: oidc_provider.build_authorize_url(state=state),
        exchange=lambda code: oidc_provider.exchange_oidc_authorization(code),
        finalize=enterprise_login_flow.finalize_auth_after_oidc,
        issue_qr=auth_qr_login.issue_auth_qr,
        poll_qr=lambda qid, secret: auth_qr_login.poll_auth_qr(qid, secret),
        consume_qr=lambda qid, secret: auth_qr_login.consume_confirmed_qr(qid, secret),
        attach_cookie=lambda response, sid: _attach_session_cookie(response, sid),
        infra_errors=lambda: INFRA_TRANSIENT,
        logger=logger,
    )


def _profile() -> AccountProfile:
    from app.application import (
        session_account_meta,
        tenant_subscription_app_service,
        user_app_service,
    )
    from app.db import session
    from app.fastapi_routes import market_account
    from app.utils.path_io import user_avatar_storage
    from app.utils.security.secure_filename import secure_filename

    return AccountProfile(
        directory=lambda: user_app_service.get_user_app_service(),
        database=lambda: session.get_db(),
        host_database=lambda: session.get_host_db(),
        session_id=lambda request: session_id_from_request(request),
        public_user=lambda user: _user_public_dict(user),
        load_meta=lambda sid: session_account_meta.load_session_account_meta(sid),
        market_token=lambda sid: market_account.resolve_valid_market_access_token(sid),
        write_market_brand=lambda authorization, brand: market_account._proxy_json(
            "PUT",
            "/api/auth/profile",
            json_body={"company": brand},
            authorization=authorization,
            return_error_payload=True,
        ),
        sync_tenant_name=lambda uid, brand, db: (
            tenant_subscription_app_service.sync_tenant_display_name(
                user_id=uid, company_brand=brand, db=db
            )
        ),
        safe_filename=secure_filename,
        save_avatar=lambda uid, content, ext: user_avatar_storage.save_user_avatar_file(
            uid, content, ext
        ),
        avatar_file=lambda uid: user_avatar_storage.avatar_file_for_user(uid),
        avatar_media_type=lambda path: user_avatar_storage.media_type_for_path(path),
        avatar_api_path=user_avatar_storage.AVATAR_API_PATH,
        max_avatar_bytes=user_avatar_storage.MAX_AVATAR_BYTES,
        recoverable_errors=lambda: RECOVERABLE_ERRORS,
        logger=logger,
    )


def _users() -> UserAdministration:
    import app.application as application
    from app.application import auth_app_service

    return UserAdministration(
        directory=lambda: application.get_user_app_service(),
        backend=lambda: auth_app_service.get_auth_app_service(),
    )


def _session_meta_for_response(request: Request, user: User | None = None) -> JsonObject:
    return _sessions().metadata(request, user)


def _find_local_users_by_email(email: str) -> list[User]:
    return _recovery().find_local_users(email)


def _sync_local_password_for_email(email: str, new_password: str) -> int:
    return _recovery().sync_local_passwords(email, new_password)


def _jit_create_local_user_for_enterprise(username: str, password: str, email: str = "") -> bool:
    return _registration().create_local_user(username, password, email)


def _enrich_register_with_tenant(
    *, result: JsonObject, username: str, session_id: str | None, sku: str, company_brand: str = ""
) -> JsonObject:
    return _registration().enrich_tenant(
        result=result,
        username=username,
        session_id=session_id,
        sku=sku,
        company_brand=company_brand,
    )


def _open_registration_allowed(sku: str) -> bool:
    return open_registration_allowed(sku, os.environ)


def _attach_session_cookie(response: Response, session_id: str | None) -> Response:
    return SessionCookies(os.environ).attach(response, session_id)


# Public handlers are also mounted directly by compatibility consumers.
# Keep their runtime annotation accepted by FastAPI; components own the precise union.


# Domain owners register their endpoints. Separate lifecycle sections keep the
# established order while each factory continues resolving compatibility hooks at call time.

_session_routes = SessionRoutes(sessions=lambda: _sessions())
_security_routes = SecurityRoutes(
    security=lambda: _security(), authenticated_user=get_logged_in_user
)
_recovery_routes = RecoveryRoutes(recovery=lambda: _recovery())
_credential_routes = CredentialRoutes(
    registration=lambda: _registration(), credentials=lambda: _credentials()
)
_federated_routes = FederatedRoutes(federated=lambda: _federated())
_profile_routes = ProfileRoutes(profile=lambda: _profile(), authenticated_user=get_logged_in_user)
_administration_routes = AdministrationRoutes(users=lambda: _users(), require_admin=_require_admin)

router.include_router(_session_routes.identity)
router.include_router(_security_routes.mfa)
router.include_router(_session_routes.tokens)
router.include_router(_recovery_routes.router)
router.include_router(_credential_routes.router)
router.include_router(_federated_routes.router)
router.include_router(_profile_routes.router)
router.include_router(_session_routes.logout)
router.include_router(_security_routes.password)
router.include_router(_administration_routes.router)

auth_me = _session_routes.auth_me
auth_token_refresh = _session_routes.auth_token_refresh
auth_session_validate = _session_routes.auth_session_validate
runtime_product_sku = _session_routes.runtime_product_sku
auth_subscription_status = _session_routes.auth_subscription_status
auth_logout = _session_routes.auth_logout
auth_mfa_setup = _security_routes.auth_mfa_setup
auth_mfa_enable = _security_routes.auth_mfa_enable
auth_mfa_disable = _security_routes.auth_mfa_disable
auth_password_change = _security_routes.auth_password_change
auth_forgot_account = _recovery_routes.auth_forgot_account
auth_forgot_password_send_code = _recovery_routes.auth_forgot_password_send_code
auth_forgot_password_reset = _recovery_routes.auth_forgot_password_reset
auth_register = _credential_routes.auth_register
auth_login = _credential_routes.auth_login
auth_login_with_phone_code = _credential_routes.auth_login_with_phone_code
auth_oidc_status = _federated_routes.auth_oidc_status
auth_oidc_start = _federated_routes.auth_oidc_start
auth_oidc_callback = _federated_routes.auth_oidc_callback
auth_qr_issue = _federated_routes.auth_qr_issue
auth_qr_status = _federated_routes.auth_qr_status
auth_profile_get = _profile_routes.auth_profile_get
auth_profile_patch = _profile_routes.auth_profile_patch
auth_profile_avatar_upload = _profile_routes.auth_profile_avatar_upload
auth_profile_avatar_get = _profile_routes.auth_profile_avatar_get
auth_update_company_brand = _profile_routes.auth_update_company_brand
users_list = _administration_routes.users_list
users_get = _administration_routes.users_get
users_create = _administration_routes.users_create
users_update = _administration_routes.users_update
users_delete = _administration_routes.users_delete
users_reset_password = _administration_routes.users_reset_password
