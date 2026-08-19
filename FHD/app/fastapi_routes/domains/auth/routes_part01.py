# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.domains.auth.routes')

def _user_public_dict(user) -> dict[str, _facade().Any]:
    from app.utils.no_email import email_display, is_no_email_address
    from app.utils.path_io.user_avatar_storage import public_avatar_url
    return {'id': user.id, 'username': user.username, 'display_name': user.display_name, 'email': user.email, 'email_display': email_display(user.email), 'no_email': is_no_email_address(user.email), 'role': user.role, 'is_active': user.is_active, 'avatar_url': public_avatar_url(getattr(user, 'wx_avatar_url', None))}

def _session_meta_for_response(request: _facade().Request, user=None) -> dict[str, _facade().Any]:
    from app.application.session_account_meta import enrich_session_meta_with_tenant, load_session_account_meta
    sid = _facade().session_id_from_request(request)
    if not sid:
        return {}
    if user is not None:
        return enrich_session_meta_with_tenant(sid, user)
    meta = load_session_account_meta(sid)
    return meta if meta else {}

def _account_profile_fields(user: _facade().Any, session_meta: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """账号体系真相源字段（暴露给前端只读展示）：tier / account_tier / budget_range /
    entitled_industries / market_membership_tier。account_tier 经派生（非企业为 None）。"""
    from app.application.account_tier_derivation import resolve_account_tier_for_user
    tier = str(getattr(user, 'tier', '') or '') if user is not None else ''
    return {'tier': tier or None, 'account_tier': resolve_account_tier_for_user(tier, getattr(user, 'account_tier', None)), 'budget_range': getattr(user, 'budget_range', None) if user is not None else None, 'entitled_industries': list(getattr(user, 'entitled_industries', None) or []), 'market_membership_tier': session_meta.get('market_membership_tier'), 'email_verified': bool(getattr(user, 'email_verified', False)) if user is not None else False, 'mfa_enabled': bool(getattr(user, 'mfa_enabled', False)) if user is not None else False}

@_facade().router.get('/api/auth/me')
def auth_me(request: _facade().Request):
    from app.application.auth_app_service import get_auth_app_service
    from app.application.desktop_admin_gate import assert_desktop_allows_session_id
    denied = assert_desktop_allows_session_id(_facade().session_id_from_request(request))
    if denied is not None:
        return _facade().JSONResponse(denied, status_code=403)
    user = _facade().resolve_session_user(request)
    if not user:
        return _facade().JSONResponse({**_facade().error_envelope(_facade().UNAUTHORIZED, '请先登录'), 'valid': False}, status_code=200)
    if not getattr(user, 'is_active', True):
        return _facade().JSONResponse(_facade().error_envelope(_facade().ACCOUNT_DISABLED, '账户已被禁用'), status_code=403)
    auth_app_service = get_auth_app_service()
    permissions = auth_app_service.get_user_permissions(user)
    session_meta = _facade()._session_meta_for_response(request, user)
    return {'success': True, 'data': {'user': _facade()._user_public_dict(user), 'permissions': permissions, 'account_kind': session_meta.get('account_kind') or 'enterprise', 'company_brand': session_meta.get('company_brand') or '', 'market_is_admin': bool(session_meta.get('market_is_admin')), 'market_is_enterprise': bool(session_meta.get('market_is_enterprise')), 'market_user_id': session_meta.get('market_user_id'), 'local_user_id': session_meta.get('local_user_id') or getattr(user, 'id', None), 'tenant_id': session_meta.get('tenant_id'), 'tenant_name': session_meta.get('tenant_name') or session_meta.get('company_brand') or '', 'impersonating_market_user_id': session_meta.get('impersonating_market_user_id'), 'impersonating_username': session_meta.get('impersonating_username') or '', **_facade()._account_profile_fields(user, session_meta)}}

@_facade().router.post('/api/auth/mfa/setup')
def auth_mfa_setup(request: _facade().Request):
    """生成 TOTP 密钥（待验证；mfa_enabled 在 /enable 校验通过后才置 True）。"""
    user = _facade().resolve_session_user(request)
    if not user:
        return _facade().JSONResponse(_facade().error_envelope(_facade().UNAUTHORIZED, '请先登录'), status_code=200)
    from app.application.account_security import generate_totp_secret, provisioning_uri
    from app.db.models.user import User
    from app.db.session import get_db
    secret = generate_totp_secret()
    with get_db() as db:
        u = db.get(User, int(user.id))
        if u is None:
            return _facade().JSONResponse(_facade().error_envelope(_facade().UNAUTHORIZED, '用户不存在'), status_code=200)
        u.totp_secret = secret
        db.commit()
        username = u.username
    return {'success': True, 'data': {'secret': secret, 'otpauth_uri': provisioning_uri(secret, username)}}

@_facade().router.post('/api/auth/mfa/enable')
def auth_mfa_enable(request: _facade().Request, body: dict=_facade().Body(default_factory=dict)):
    """校验 TOTP 后开启 MFA。"""
    user = _facade().resolve_session_user(request)
    if not user:
        return _facade().JSONResponse(_facade().error_envelope(_facade().UNAUTHORIZED, '请先登录'), status_code=200)
    code = str(body.get('code') or body.get('totp_code') or '').strip()
    from app.application.account_security import verify_totp
    from app.db.models.user import User
    from app.db.session import get_db
    with get_db() as db:
        u = db.get(User, int(user.id))
        if u is None or not (u.totp_secret or ''):
            return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_INPUT, '请先调用 /api/auth/mfa/setup 生成密钥'), status_code=400)
        if not verify_totp(u.totp_secret, code):
            return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_INPUT, '动态验证码错误'), status_code=400)
        u.mfa_enabled = True
        db.commit()
    return {'success': True, 'message': 'MFA 已开启'}

@_facade().router.post('/api/auth/mfa/disable')
def auth_mfa_disable(request: _facade().Request, body: dict=_facade().Body(default_factory=dict)):
    """关闭 MFA（已开启时需校验当前 TOTP）。"""
    user = _facade().resolve_session_user(request)
    if not user:
        return _facade().JSONResponse(_facade().error_envelope(_facade().UNAUTHORIZED, '请先登录'), status_code=200)
    code = str(body.get('code') or body.get('totp_code') or '').strip()
    from app.application.account_security import verify_totp
    from app.db.models.user import User
    from app.db.session import get_db
    with get_db() as db:
        u = db.get(User, int(user.id))
        if u is None:
            return _facade().JSONResponse(_facade().error_envelope(_facade().UNAUTHORIZED, '用户不存在'), status_code=200)
        if u.mfa_enabled and (not verify_totp(u.totp_secret or '', code)):
            return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_INPUT, '动态验证码错误'), status_code=400)
        u.mfa_enabled = False
        u.totp_secret = None
        db.commit()
    return {'success': True, 'message': 'MFA 已关闭'}

@_facade().router.post('/api/auth/token/refresh')
def auth_token_refresh(body: dict=_facade().Body(default_factory=dict)):
    """无状态 JWT：用 refresh token 轮转出新的 access/refresh（一次性使用）。"""
    from app.security.web_jwt import refresh_web_access_token
    rt = str(body.get('refresh_token') or '').strip()
    tokens = refresh_web_access_token(rt)
    if not tokens:
        return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_INPUT, 'refresh token 无效或已使用'), status_code=401)
    return {'success': True, 'data': tokens}

@_facade().router.get('/api/auth/session/validate')
async def auth_session_validate(request: _facade().Request, background_tasks: _facade().BackgroundTasks):
    from app.application.auth_app_service import get_auth_app_service
    from app.application.desktop_admin_gate import assert_desktop_allows_session_id
    session_id = _facade().session_id_from_request(request)
    if not session_id:
        return _facade().JSONResponse({**_facade().error_envelope(_facade().NO_SESSION, '无会话信息'), 'valid': False}, status_code=200)
    denied = assert_desktop_allows_session_id(session_id)
    if denied is not None:
        return _facade().JSONResponse(denied, status_code=403)
    auth_app_service = get_auth_app_service()
    session_info = auth_app_service.session_manager.get_session_info(session_id)
    if not session_info:
        return _facade().JSONResponse({**_facade().error_envelope(_facade().INVALID_SESSION, '会话无效或已过期'), 'valid': False}, status_code=200)
    try:
        from app.mod_sdk.product_skus import resolve_product_sku
        if resolve_product_sku() == 'enterprise':
            from app.fastapi_routes.market_account import resolve_valid_market_access_token_fast
            market_tok = await resolve_valid_market_access_token_fast(session_id)
            if not market_tok:
                return _facade().JSONResponse({**_facade().error_envelope(_facade().MARKET_NOT_BOUND, '企业版需使用修茈市场企业级账号登录。若此前仅用本地管理员进入，请退出后重新登录。'), 'valid': False}, status_code=200)
    except _facade().INFRA_TRANSIENT:
        _facade().logger.exception('enterprise market session check on validate failed')
    entitled_mod_ids: list[str] = []
    try:
        from app.enterprise.mod_entitlements import get_cached_entitled_client_mod_ids, sync_entitlements_for_session
        background_tasks.add_task(sync_entitlements_for_session, session_id)
        cached = get_cached_entitled_client_mod_ids()
        if cached is not None:
            entitled_mod_ids = sorted(cached)
    except _facade().INFRA_TRANSIENT:
        _facade().logger.exception('sync enterprise entitlements on validate failed')
    user = _facade().resolve_session_user(request)
    session_meta = _facade()._session_meta_for_response(request, user)
    payload: dict[str, _facade().Any] = {'success': True, 'valid': True, 'data': session_info}
    if entitled_mod_ids:
        payload['entitled_mod_ids'] = entitled_mod_ids
    if session_meta:
        payload['account_kind'] = session_meta.get('account_kind')
        payload['company_brand'] = session_meta.get('company_brand')
        payload['market_is_admin'] = session_meta.get('market_is_admin')
        payload['market_is_enterprise'] = session_meta.get('market_is_enterprise')
        payload['market_user_id'] = session_meta.get('market_user_id')
        payload['local_user_id'] = session_meta.get('local_user_id')
        payload['tenant_id'] = session_meta.get('tenant_id')
        payload['tenant_name'] = session_meta.get('tenant_name')
        payload['impersonating_market_user_id'] = session_meta.get('impersonating_market_user_id')
        payload['impersonating_username'] = session_meta.get('impersonating_username')
        payload.update(_facade()._account_profile_fields(user, session_meta))
    return payload

def _market_user_email_from_raw(raw: _facade().Any) -> str:
    if not isinstance(raw, dict):
        return ''
    user = raw.get('user')
    if isinstance(user, dict) and user.get('email'):
        return str(user.get('email') or '').strip()
    data = raw.get('data')
    if isinstance(data, dict):
        inner = data.get('user')
        if isinstance(inner, dict) and inner.get('email'):
            return str(inner.get('email') or '').strip()
    return ''

def _normalize_auth_email(email: str) -> str:
    return (email or '').strip().lower()

def _find_local_users_by_email(email: str) -> list:
    from sqlalchemy import func
    from app.db.models.user import User
    from app.db.session import get_db
    norm = _facade()._normalize_auth_email(email)
    if not norm or '@' not in norm:
        return []
    with get_db() as db:
        return _facade().cast('list[Any]', db.query(User).filter(func.lower(User.email) == norm).filter(User.is_active.is_(True)).order_by(User.id.asc()).all())

def _sync_local_password_for_email(email: str, new_password: str) -> int:
    from app.application.auth_app_service import get_auth_app_service
    auth_app_service = get_auth_app_service()
    updated = 0
    for user in _facade()._find_local_users_by_email(email):
        result = auth_app_service.reset_password(int(user.id), new_password)
        if result.get('success'):
            updated += 1
    return updated

def _jit_create_local_user_for_enterprise(username: str, password: str, email: str='') -> bool:
    from app.db.models.user import User
    from app.db.session import get_db
    from app.utils.security.password_hash import generate_password_hash
    from app.utils.time import utc_now_naive
    try:
        with get_db() as db:
            if db.query(User).filter(User.username == username).first():
                return False
            db.add(User(username=username, password=generate_password_hash(password), display_name=username, email=email or '', role='user', is_active=True, mfa_enabled=False, created_at=utc_now_naive()))
            db.commit()
        return True
    except _facade().INFRA_TRANSIENT as exc:
        _facade().logger.exception('_jit_create_local_user_for_enterprise failed for %s: %s', username, exc)
        return False

@_facade().router.get('/api/runtime/product-sku')
def runtime_product_sku():
    from app.mod_sdk.product_skus import resolve_product_sku
    sku = resolve_product_sku()
    return {'success': True, 'data': {'sku': sku or 'generic', 'is_enterprise_edition': sku == 'enterprise'}}

def _open_registration_allowed(sku: str) -> bool:
    raw = (_facade().os.environ.get('FHD_ALLOW_OPEN_REGISTRATION') or '').strip().lower()
    if raw in ('0', 'false', 'no'):
        return False
    if raw in ('1', 'true', 'yes'):
        return True
    return sku != 'enterprise'

def _enrich_register_with_tenant(*, result: dict[str, _facade().Any], username: str, session_id: str | None, sku: str, company_brand: str='') -> dict[str, _facade().Any]:
    """注册成功后创建试用租户并写入会话元数据（与登录流 bind_tenant_for_login 对齐）。"""
    user_id = (result.get('user') or {}).get('id')
    if user_id is None:
        return result
    try:
        from app.application.enterprise_login_flow import bind_tenant_for_login
        from app.application.session_account_meta import normalize_account_kind, persist_session_account_meta
        tenant_info = bind_tenant_for_login(user_id=int(user_id), company_brand=company_brand or username, username=username)
        if tenant_info.get('tenant_id') is not None:
            result['tenant_id'] = tenant_info['tenant_id']
        if tenant_info.get('tenant_name'):
            result['tenant_name'] = tenant_info['tenant_name']
        if session_id:
            account_kind = normalize_account_kind('enterprise' if sku == 'enterprise' else 'personal')
            persist_session_account_meta(str(session_id), account_kind=account_kind, company_brand=company_brand or '', tenant_id=int(tenant_info['tenant_id']) if tenant_info.get('tenant_id') else None)
            result.setdefault('account_kind', account_kind)
    except _facade().INFRA_TRANSIENT:
        _facade().logger.exception('register tenant provision failed for user_id=%s', user_id)
    return result

@_facade().router.get('/api/auth/subscription/status')
def auth_subscription_status(request: _facade().Request):
    """当前登录用户的试用/付费订阅状态（SaasPricingView 与订阅门禁共用）。"""
    user = _facade().resolve_session_user(request)
    if not user:
        return _facade().JSONResponse(_facade().error_envelope(_facade().UNAUTHORIZED, '请先登录'), status_code=200)
    from app.application.tenant_subscription_app_service import subscription_status_for_user
    status = subscription_status_for_user(int(user.id))
    return {'success': True, 'data': status}

def _attach_session_cookie(response: _facade().Response, session_id: str | None) -> _facade().Response:
    sid = (session_id or '').strip()
    if not sid:
        return response
    cookie_name = _facade().os.environ.get('SESSION_COOKIE_NAME', 'session_id')
    max_age = int(_facade().os.environ.get('SESSION_COOKIE_MAX_AGE', '315360000'))
    raw_samesite = _facade().os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax').strip().lower()
    samesite = _facade().cast("Literal['lax', 'strict', 'none']", raw_samesite if raw_samesite in {'lax', 'strict', 'none'} else 'lax')
    response.set_cookie(key=cookie_name, value=sid, max_age=max_age, httponly=_facade().os.environ.get('SESSION_COOKIE_HTTPONLY', '1') not in ('0', 'false', 'False'), secure=_facade().os.environ.get('SESSION_COOKIE_SECURE', '').lower() in ('1', 'true', 'yes'), samesite=samesite, path='/')
    return response

@_facade().router.post('/api/auth/forgot-account')
def auth_forgot_account(body: dict=_facade().Body(default_factory=dict)):
    """Look up local PostgreSQL users by email (same DB as login)."""
    email = _facade()._normalize_auth_email(str(body.get('email') or ''))
    if not email or '@' not in email:
        return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_INPUT, '请填写有效邮箱'), status_code=400)
    users = _facade()._find_local_users_by_email(email)
    usernames = [str(u.username) for u in users if u.username]
    if usernames:
        message = f'找到 {len(usernames)} 个与本机数据库关联的账号'
    else:
        message = '本机数据库中未找到该邮箱对应的账号，可尝试注册或联系管理员'
    return {'success': True, 'message': message, 'data': {'usernames': usernames, 'found': bool(usernames)}}

@_facade().router.post('/api/auth/forgot-password/send-code')
async def auth_forgot_password_send_code(body: dict=_facade().Body(default_factory=dict)):
    """Send reset code via Xiuci market API; uses XCAGI_MARKET_BASE_URL (e.g. production server)."""
    from app.fastapi_routes.market_account import send_market_reset_password_code
    email = _facade()._normalize_auth_email(str(body.get('email') or ''))
    if not email or '@' not in email:
        return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_INPUT, '请填写有效邮箱'), status_code=400)
    local_users = _facade()._find_local_users_by_email(email)
    try:
        from app.application.auth_app_service import get_auth_app_service
        svc = get_auth_app_service()
        send_local = getattr(svc, 'send_password_reset_code', None)
        if callable(send_local):
            local_result = send_local(email)
            if isinstance(local_result, dict) and local_result.get('success'):
                return {'success': True, 'message': local_result.get('message', '若该邮箱已注册，将收到验证码'), 'data': {'local_user_count': len(local_users)}}
    except _facade().RECOVERABLE_ERRORS:
        pass
    result = await send_market_reset_password_code(email)
    if not result.get('success'):
        hint = result.get('message', '发送失败')
        if local_users:
            hint = f'{hint}（本机库中有该邮箱用户，请确认修茈市场服务与邮件配置正常）'
        return _facade().JSONResponse(_facade().error_envelope(_facade().SEND_CODE_FAILED, hint), status_code=502)
    return {'success': True, 'message': result.get('message', '若该邮箱已注册，将收到验证码'), 'data': {'market_base_url': result.get('market_base_url'), 'local_user_count': len(local_users)}}

@_facade().router.post('/api/auth/forgot-password/reset')
async def auth_forgot_password_reset(body: dict=_facade().Body(default_factory=dict)):
    """Reset password on market, then sync matching users in local PostgreSQL."""
    from app.fastapi_routes.market_account import reset_market_password_with_code
    email = _facade()._normalize_auth_email(str(body.get('email') or ''))
    code = str(body.get('code') or body.get('verification_code') or '').strip()
    new_password = str(body.get('new_password') or body.get('password') or '')
    if not email or '@' not in email:
        return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_INPUT, '请填写有效邮箱'), status_code=400)
    if len(new_password) < 6:
        return _facade().JSONResponse(_facade().error_envelope(_facade().WEAK_PASSWORD, '新密码至少 6 个字符'), status_code=400)
    market_result = await reset_market_password_with_code(email, code, new_password)
    if not market_result.get('success'):
        return _facade().JSONResponse(_facade().error_envelope(_facade().MARKET_RESET_FAILED, market_result.get('message', '重置失败')), status_code=400)
    local_updated = _facade()._sync_local_password_for_email(email, new_password)
    return {'success': True, 'message': '密码已重置，请使用新密码登录', 'data': {'local_users_updated': local_updated}}
