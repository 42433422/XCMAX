# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.domains.auth.routes')

@_facade().router.post('/api/auth/register')
async def auth_register(request: _facade().Request, body: dict=_facade().Body(default_factory=dict)):
    """Register locally (PostgreSQL users) and optionally on Xiuci market; then create session."""
    from app.application import get_user_app_service
    from app.application.auth_app_service import get_auth_app_service
    from app.fastapi_routes.market_account import login_market_with_password, register_market_user, save_session_market_token
    from app.mod_sdk.product_skus import resolve_product_sku
    username = (body.get('username') or '').strip()
    password = body.get('password', '')
    email = (body.get('email') or '').strip()
    verification_code = str(body.get('verification_code') or body.get('code') or '').strip()
    industry_id = (body.get('industry_id') or '').strip()
    budget_range = (body.get('budget_range') or '').strip()
    if not username or not password:
        return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_INPUT, '用户名和密码不能为空'), status_code=400)
    if len(password) < 6:
        return _facade().JSONResponse(_facade().error_envelope(_facade().WEAK_PASSWORD, '密码至少 6 个字符'), status_code=400)
    sku = resolve_product_sku() or 'generic'
    auth_app_service = get_auth_app_service()
    if sku == 'enterprise':
        reg_email = email
        market_reg = await register_market_user(username, password, reg_email, verification_code)
        if not market_reg.get('success'):
            return _facade().JSONResponse(_facade().error_envelope(_facade().MARKET_REGISTER_FAILED, market_reg.get('message', '修茈市场注册失败')), status_code=400)
        if not bool(market_reg.get('desktop_access')):
            payload = _facade().registration_response.pending_registration_payload(market_reg)
            return _facade().JSONResponse(payload)
        email_market = _facade()._market_user_email_from_raw(market_reg.get('raw')) or reg_email
        _facade()._jit_create_local_user_for_enterprise(username, password, email_market)
        result = auth_app_service.login(username, password)
        if not result.get('success'):
            return _facade().JSONResponse(_facade().error_envelope(_facade().LOCAL_LOGIN_AFTER_REGISTER, result.get('message', '注册成功但本地登录失败')), status_code=500)
        session_id = result.get('session_id')
        mtok = str(market_reg.get('token') or '').strip()
        mrefresh = str(market_reg.get('refresh_token') or '').strip()
        if session_id and mtok:
            save_session_market_token(str(session_id), mtok, mrefresh or None)
            result['market_access_token'] = mtok
            if mrefresh:
                result['market_refresh_token'] = mrefresh
        result = _facade()._enrich_register_with_tenant(result=result, username=username, session_id=str(session_id) if session_id else None, sku=sku, company_brand=email_market or email)
    else:
        if not _facade()._open_registration_allowed(sku):
            return _facade().JSONResponse(_facade().error_envelope(_facade().REGISTRATION_DISABLED, '本部署未开放自助注册，请联系管理员创建账号'), status_code=403)
        user_service = get_user_app_service()
        created = user_service.create_user(username=username, password=password, display_name=body.get('display_name') or username, email=email, role='viewer')
        if not created.get('success'):
            msg = created.get('message', '创建用户失败')
            if '已存在' in msg or 'unique' in msg.lower():
                msg = '用户名已存在'
            return _facade().JSONResponse(_facade().error_envelope(_facade().CREATE_FAILED, msg), status_code=400)
        result = auth_app_service.login(username, password)
        if not result.get('success'):
            return _facade().JSONResponse(_facade().error_envelope(_facade().LOGIN_AFTER_REGISTER, result.get('message', '注册成功但登录失败')), status_code=500)
        session_id = result.get('session_id')
        try:
            market_result = await login_market_with_password(username, password)
            if market_result.get('success'):
                mtok = str(market_result.get('token') or '').strip()
                mrefresh = str(market_result.get('refresh_token') or '').strip()
                if session_id and mtok:
                    save_session_market_token(str(session_id), mtok, mrefresh or None)
                    result['market_access_token'] = mtok
                    if mrefresh:
                        result['market_refresh_token'] = mrefresh
        except _facade().INFRA_TRANSIENT:
            _facade().logger.exception('optional market sync after local register failed')
        result = _facade()._enrich_register_with_tenant(result=result, username=username, session_id=str(session_id) if session_id else None, sku=sku, company_brand=email or username)
    from app.application.account_registration import apply_account_profile_on_register
    apply_account_profile_on_register(username, tier='enterprise' if sku == 'enterprise' else 'personal', industry_id=industry_id, budget_range=budget_range)
    payload = {'success': True, **result}
    return _facade()._attach_session_cookie(_facade().JSONResponse(payload), result.get('session_id'))

@_facade().router.post('/api/auth/login')
async def auth_login(request: _facade().Request, body: dict=_facade().Body(default_factory=dict)):
    import time
    from app.utils.metrics import auth_login_duration_seconds
    login_start = time.perf_counter()
    from app.application.auth_app_service import get_auth_app_service
    from app.application.enterprise_login_flow import run_market_first_login
    from app.application.session_account_meta import normalize_account_kind
    from app.fastapi_routes.market_account import login_market_with_password
    from app.mod_sdk.product_skus import resolve_product_sku
    username = (body.get('username') or '').strip()
    password = body.get('password', '')
    if not username or not password:
        auth_login_duration_seconds.labels(auth_method='password').observe(time.perf_counter() - login_start)
        return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_INPUT, '用户名和密码不能为空'), status_code=200)
    auth_app_service = get_auth_app_service()
    sku = resolve_product_sku() or 'personal'
    account_kind = normalize_account_kind(body.get('account_kind'), default='enterprise' if sku == 'enterprise' else 'personal')
    (result, err) = await run_market_first_login(username=username, password=password, account_kind=account_kind, market_result=None, auth_app_service=auth_app_service, sku=sku, jit_create_fn=_facade()._jit_create_local_user_for_enterprise, market_user_email_from_raw=_facade()._market_user_email_from_raw, login_market_fn=login_market_with_password, totp_code=str(body.get('totp_code') or '').strip() or None)
    if err:
        auth_login_duration_seconds.labels(auth_method='password').observe(time.perf_counter() - login_start)
        return err
    if result and result.get('success'):
        _u = result.get('user') or {}
        if _u.get('id') is not None:
            try:
                from app.security.web_jwt import issue_web_tokens
                result['web_tokens'] = issue_web_tokens(user_id=int(_u['id']), username=str(_u.get('username') or ''), account_kind=str(result.get('account_kind') or 'enterprise'))
            except _facade().INFRA_TRANSIENT:
                _facade().logger.exception('issue web tokens failed')
    resp = _facade()._attach_session_cookie(_facade().JSONResponse(result or {}), (result or {}).get('session_id'))
    auth_login_duration_seconds.labels(auth_method='password').observe(time.perf_counter() - login_start)
    return resp

@_facade().router.post('/api/auth/login-with-phone-code')
async def auth_login_with_phone_code(request: _facade().Request, body: dict=_facade().Body(default_factory=dict)):
    import time
    from app.utils.metrics import auth_login_duration_seconds
    login_start = time.perf_counter()
    from app.application.auth_app_service import get_auth_app_service
    from app.application.enterprise_login_flow import run_market_first_login
    from app.application.session_account_meta import normalize_account_kind
    from app.fastapi_routes.market_account import login_market_with_phone_code
    from app.mod_sdk.product_skus import resolve_product_sku
    phone = str(body.get('phone') or '').strip()
    code = str(body.get('code') or '').strip()
    if not phone or not code:
        auth_login_duration_seconds.labels(auth_method='phone_code').observe(time.perf_counter() - login_start)
        return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_INPUT, '手机号和验证码不能为空'), status_code=400)
    auth_app_service = get_auth_app_service()
    sku = resolve_product_sku() or 'personal'
    account_kind = normalize_account_kind(body.get('account_kind'), default='enterprise' if sku == 'enterprise' else 'personal')
    market_result = await login_market_with_phone_code(phone, code)
    username = str(body.get('username') or '').strip()
    (result, err) = await run_market_first_login(username=username, password=None, account_kind=account_kind, market_result=market_result, auth_app_service=auth_app_service, sku=sku, jit_create_fn=_facade()._jit_create_local_user_for_enterprise, market_user_email_from_raw=_facade()._market_user_email_from_raw, login_market_fn=None)
    if err:
        auth_login_duration_seconds.labels(auth_method='phone_code').observe(time.perf_counter() - login_start)
        return err
    resp = _facade()._attach_session_cookie(_facade().JSONResponse(result or {}), (result or {}).get('session_id'))
    auth_login_duration_seconds.labels(auth_method='phone_code').observe(time.perf_counter() - login_start)
    return resp

@_facade().router.get('/api/auth/oidc/status')
def auth_oidc_status():
    from app.infrastructure.auth.oidc_provider import oidc_enabled
    return {'success': True, 'data': {'enabled': oidc_enabled()}}

@_facade().router.get('/api/auth/oidc/start')
async def auth_oidc_start(request: _facade().Request):
    from fastapi.responses import RedirectResponse
    from app.infrastructure.auth.oidc_provider import build_authorize_url, oidc_enabled, sign_oidc_state
    if not oidc_enabled():
        return _facade().JSONResponse({'success': False, 'message': 'OIDC 未启用'}, status_code=404)
    return_to = str(request.query_params.get('return') or '').strip()
    state = sign_oidc_state(return_to=return_to)
    url = await build_authorize_url(state=state)
    return RedirectResponse(url=url, status_code=302)

@_facade().router.get('/api/auth/oidc/callback')
async def auth_oidc_callback(request: _facade().Request):
    from urllib.parse import quote
    from fastapi.responses import RedirectResponse
    from app.application.auth_app_service import get_auth_app_service
    from app.application.enterprise_login_flow import finalize_auth_after_oidc
    from app.application.session_account_meta import normalize_account_kind
    from app.infrastructure.auth.oidc_provider import exchange_oidc_authorization, frontend_redirect_path, oidc_enabled, verify_oidc_state
    from app.mod_sdk.product_skus import resolve_product_sku
    base = frontend_redirect_path()
    if not oidc_enabled():
        return RedirectResponse(url=f'{base}?oidc_error=OIDC_DISABLED', status_code=302)
    code = str(request.query_params.get('code') or '').strip()
    state = str(request.query_params.get('state') or '').strip()
    (ok, _rt) = verify_oidc_state(state)
    if not ok or not code:
        return RedirectResponse(url=f"{base}?oidc_error=OIDC_STATE&oidc_message={quote('状态校验失败')}", status_code=302)
    try:
        oidc_session = await exchange_oidc_authorization(code)
        raw_profile = oidc_session.get('profile')
        profile: dict[str, _facade().Any] = dict(raw_profile) if isinstance(raw_profile, dict) else {}
    except _facade().INFRA_TRANSIENT as exc:
        _facade().logger.exception('OIDC exchange failed')
        return RedirectResponse(url=f'{base}?oidc_error=OIDC_EXCHANGE&oidc_message={quote(str(exc))}', status_code=302)
    auth_app_service = get_auth_app_service()
    auth_result = auth_app_service.authenticate_oidc_user(profile)
    if not auth_result.get('success'):
        msg = str(auth_result.get('message') or 'OIDC 登录失败')
        return RedirectResponse(url=f'{base}?oidc_error=OIDC_AUTH&oidc_message={quote(msg)}', status_code=302)
    sku = resolve_product_sku() or 'personal'
    account_kind = normalize_account_kind(request.query_params.get('account_kind'), default='enterprise' if sku == 'enterprise' else 'personal')
    payload = await finalize_auth_after_oidc(auth_result=auth_result, oidc_profile=profile, oidc_access_token=str(oidc_session.get('access_token') or ''), account_kind=account_kind, sku=sku)
    resp = RedirectResponse(url=f'{base}?oidc=ok', status_code=302)
    return _facade()._attach_session_cookie(resp, payload.get('session_id'))

@_facade().router.post('/api/auth/qr/issue')
async def auth_qr_issue(request: _facade().Request, body: dict=_facade().Body(default_factory=dict)):
    from app.application.session_account_meta import normalize_account_kind
    from app.security.auth_qr_login import issue_auth_qr
    client_hint = str(body.get('client_hint') or request.headers.get('User-Agent') or '')[:256]
    kwargs: dict[str, _facade().Any] = {'client_hint': client_hint}
    if 'account_kind' in body:
        kwargs['account_kind'] = normalize_account_kind(body.get('account_kind'), default='enterprise')
    data = issue_auth_qr(**kwargs)
    return {'success': True, 'data': data}

@_facade().router.get('/api/auth/qr/status')
async def auth_qr_status(qr_id: str=_facade().Query(''), poll_secret: str=_facade().Query('')):
    from app.security.auth_qr_login import consume_confirmed_qr, poll_auth_qr
    rec = poll_auth_qr(qr_id, poll_secret)
    if not rec:
        return _facade().JSONResponse(_facade().error_envelope(_facade().QR_NOT_FOUND, '二维码无效'), status_code=404)
    status = str(rec.get('status') or 'pending')
    if status == 'confirmed':
        confirmed = consume_confirmed_qr(qr_id, poll_secret)
        if confirmed and confirmed.get('session_id'):
            payload = confirmed.get('login_payload') or {}
            resp = _facade().JSONResponse({'success': True, 'data': {'status': 'confirmed', 'session_id': confirmed.get('session_id'), **payload}})
            return _facade()._attach_session_cookie(resp, str(confirmed.get('session_id')))
    if status == 'expired':
        return {'success': True, 'data': {'status': 'expired'}}
    return {'success': True, 'data': {'status': status}}

@_facade().router.get('/api/auth/profile')
def auth_profile_get(user=_facade().Depends(_facade().get_logged_in_user)):
    """当前用户个人资料（展示名、邮箱、头像）。"""
    return {'success': True, 'data': {'user': _facade()._user_public_dict(user)}}

@_facade().router.patch('/api/auth/profile')
def auth_profile_patch(body: dict=_facade().Body(default_factory=dict), user=_facade().Depends(_facade().get_logged_in_user)):
    """更新当前用户展示名与邮箱。"""
    from app.application.user_app_service import get_user_app_service
    display_name = body.get('display_name')
    email = body.get('email')
    kwargs: dict[str, _facade().Any] = {}
    if display_name is not None:
        kwargs['display_name'] = str(display_name).strip()[:64]
    if email is not None:
        kwargs['email'] = str(email).strip()[:128]
    if not kwargs:
        return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_INPUT, '无有效字段'), status_code=400)
    result = get_user_app_service().update_user(user.id, **kwargs)
    if not result.get('success'):
        return _facade().JSONResponse(_facade().error_envelope(_facade().UPDATE_FAILED, result.get('message', '更新失败')), status_code=400)
    from app.db.models.user import User
    from app.db.session import get_db
    with get_db() as db:
        row = db.query(User).filter(User.id == user.id).first()
        if row is None:
            return _facade().JSONResponse(_facade().error_envelope(_facade().NOT_FOUND, '用户不存在'), status_code=404)
        payload = _facade()._user_public_dict(row)
    return {'success': True, 'data': {'user': payload}}

@_facade().router.post('/api/auth/profile/avatar')
async def auth_profile_avatar_upload(file: _facade().UploadFile | None=_facade().File(default=None), user=_facade().Depends(_facade().get_logged_in_user)):
    """上传并替换当前用户头像（png/jpg/gif/webp，≤4MB）。"""
    if file is None or not file.filename:
        return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_INPUT, '请选择图片文件'), status_code=400)
    from app.utils.path_io.user_avatar_storage import AVATAR_API_PATH, save_user_avatar_file
    from app.utils.security.secure_filename import secure_filename
    safe_name = secure_filename(file.filename) or 'avatar.png'
    ext = safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else 'png'
    content = await file.read()
    try:
        save_user_avatar_file(user.id, content, ext)
    except ValueError as exc:
        return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_FILE, str(exc)), status_code=400)
    except OSError as exc:
        _facade().logger.exception('avatar save failed user_id=%s', user.id)
        return _facade().JSONResponse(_facade().error_envelope(_facade().SAVE_FAILED, f'头像保存失败：{exc}'), status_code=500)
    from app.db.models.user import User
    from app.db.session import get_db
    with get_db() as db:
        row = db.query(User).filter(User.id == user.id).first()
        if row is not None:
            row.wx_avatar_url = AVATAR_API_PATH
    return {'success': True, 'data': {'avatar_url': AVATAR_API_PATH}}

@_facade().router.get('/api/auth/avatar')
def auth_profile_avatar_get(user=_facade().Depends(_facade().get_logged_in_user)):
    """返回当前登录用户的头像文件（依赖会话 Cookie 或 Bearer）。"""
    from app.utils.path_io.user_avatar_storage import avatar_file_for_user, media_type_for_path
    path = avatar_file_for_user(user.id)
    if path is None:
        return _facade().JSONResponse(status_code=404, content={'success': False, 'message': '未设置头像'})
    return _facade().FileResponse(str(path), media_type=media_type_for_path(path))

@_facade().router.post('/api/auth/company-brand')
async def auth_update_company_brand(request: _facade().Request, body: dict=_facade().Body(default_factory=dict), user=_facade().Depends(_facade().get_logged_in_user)):
    """更新企业品牌名（写入 session，并同步修茈市场 user.company）。"""
    brand = str(body.get('company_brand') or body.get('company') or '').strip()[:256]
    sid = _facade().session_id_from_request(request)
    if not sid:
        return _facade().JSONResponse(_facade().error_envelope(_facade().NO_SESSION, '无会话'), status_code=400)
    from app.application.session_account_meta import load_session_account_meta, normalize_account_kind, persist_session_account_meta
    from app.fastapi_routes.market_account import _proxy_json, resolve_valid_market_access_token
    meta = load_session_account_meta(sid) or {}
    persist_session_account_meta(sid, account_kind=normalize_account_kind(meta.get('account_kind'), default='enterprise'), company_brand=brand, market_user_id=meta.get('market_user_id'), market_is_admin=bool(meta.get('market_is_admin')), market_is_enterprise=bool(meta.get('market_is_enterprise')), impersonating_market_user_id=meta.get('impersonating_market_user_id'), impersonating_username=str(meta.get('impersonating_username') or ''))
    tok = await resolve_valid_market_access_token(sid)
    if tok:
        auth = tok if tok.lower().startswith('bearer ') else f'Bearer {tok}'
        await _proxy_json('PUT', '/api/auth/profile', json_body={'company': brand}, authorization=auth, return_error_payload=True)
    return {'success': True, 'company_brand': brand}

@_facade().router.post('/api/auth/logout')
def auth_logout(request: _facade().Request):
    from app.application.auth_app_service import get_auth_app_service
    from app.fastapi_routes.market_account import clear_session_market_token
    sid = _facade().session_id_from_request(request)
    if not sid:
        return _facade().JSONResponse(_facade().error_envelope(_facade().NO_SESSION, '无有效会话'), status_code=400)
    auth_app_service = get_auth_app_service()
    result = auth_app_service.logout(sid)
    clear_session_market_token(sid)
    try:
        from app.enterprise.mod_entitlements import clear_session_entitlements
        clear_session_entitlements()
    except _facade().INFRA_TRANSIENT:
        pass
    resp = _facade().JSONResponse(result)
    cookie_name = _facade().os.environ.get('SESSION_COOKIE_NAME', 'session_id')
    resp.delete_cookie(cookie_name, path='/')
    return resp

@_facade().router.post('/api/auth/password/change')
def auth_password_change(body: dict=_facade().Body(default_factory=dict), user=_facade().Depends(_facade().get_logged_in_user)):
    from app.application.auth_app_service import get_auth_app_service
    old_password = body.get('old_password', '')
    new_password = body.get('new_password', '')
    if not old_password or not new_password:
        return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_INPUT, '请填写完整信息'), status_code=400)
    if len(new_password) < 6:
        return _facade().JSONResponse(_facade().error_envelope(_facade().WEAK_PASSWORD, '新密码至少 6 个字符'), status_code=400)
    auth_app_service = get_auth_app_service()
    result = auth_app_service.change_password(user.id, old_password, new_password)
    if not result['success']:
        return _facade().JSONResponse(result, status_code=400)
    return result

@_facade().router.get('/api/users')
def users_list(include_inactive: str=_facade().Query(default='false'), _user=_facade().Depends(_facade()._require_admin)):
    from app.application import get_user_app_service
    user_service = get_user_app_service()
    users = user_service.list_users(skip=0, limit=100)
    if include_inactive.lower() != 'true':
        users = [u for u in users if u.get('is_active', True)]
    return {'success': True, 'data': {'users': users, 'count': len(users)}}

@_facade().router.get('/api/users/{user_id}')
def users_get(user_id: int, _user=_facade().Depends(_facade()._require_admin)):
    from app.application import get_user_app_service
    user_service = get_user_app_service()
    user = user_service.get_user(user_id)
    if not user:
        return _facade().JSONResponse(_facade().error_envelope(_facade().NOT_FOUND, '用户不存在'), status_code=404)
    return {'success': True, 'data': {'user': user}}

@_facade().router.post('/api/users')
def users_create(body: dict=_facade().Body(default_factory=dict), _user=_facade().Depends(_facade()._require_admin)):
    from app.application import get_user_app_service
    username = (body.get('username') or '').strip()
    password = body.get('password', '')
    if not username or not password:
        return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_INPUT, '用户名和密码不能为空'), status_code=400)
    if len(password) < 6:
        return _facade().JSONResponse(_facade().error_envelope(_facade().WEAK_PASSWORD, '密码至少6个字符'), status_code=400)
    role = body.get('role', 'viewer')
    if role not in ['viewer', 'operator', 'admin']:
        return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_ROLE, '无效的角色'), status_code=400)
    user_service = get_user_app_service()
    result = user_service.create_user(username=username, password=password, display_name=body.get('display_name', ''), email=body.get('email', ''), role=role)
    if not result['success']:
        return _facade().JSONResponse(_facade().error_envelope(_facade().CREATE_FAILED, str(result.get('error') or result.get('message') or '创建失败')), status_code=400)
    return _facade().JSONResponse({'success': True, 'data': {'user': result['user']}}, status_code=201)

@_facade().router.put('/api/users/{user_id}')
def users_update(user_id: int, body: dict=_facade().Body(default_factory=dict), _user=_facade().Depends(_facade()._require_admin)):
    from app.application import get_user_app_service
    role = body.get('role')
    if role and role not in ['viewer', 'operator', 'admin']:
        return _facade().JSONResponse(_facade().error_envelope(_facade().INVALID_ROLE, '无效的角色'), status_code=400)
    user_service = get_user_app_service()
    result = user_service.update_user(user_id=user_id, display_name=body.get('display_name'), email=body.get('email'), role=role, is_active=body.get('is_active'))
    if not result['success']:
        return _facade().JSONResponse(_facade().error_envelope(_facade().UPDATE_FAILED, str(result.get('error') or result.get('message') or '更新失败')), status_code=400)
    return {'success': True, 'data': {'user': result['user']}}

@_facade().router.delete('/api/users/{user_id}')
def users_delete(user_id: int, user=_facade().Depends(_facade()._require_admin)):
    if user.id == user_id:
        return _facade().JSONResponse(_facade().error_envelope(_facade().SELF_DELETE, '不能删除自己'), status_code=400)
    from app.application import get_user_app_service
    user_service = get_user_app_service()
    result = user_service.delete_user(user_id)
    if not result.get('success'):
        return _facade().JSONResponse(result, status_code=400)
    return result
