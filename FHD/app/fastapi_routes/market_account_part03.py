# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.market_account')

async def login_market_with_password(username: str, password: str) -> dict[str, _facade().Any]:
    """Authenticate against the market server and return a normalized token payload."""
    from app.application.surface_audit_demo_account import try_local_demo_market_login
    market_base = _facade()._market_base_url()
    demo_shim = try_local_demo_market_login(username, password)
    if demo_shim and _facade()._is_local_market_base(market_base):
        return _facade()._demo_market_login_payload(demo_shim, market_base_url=market_base)
    payload = await _facade()._proxy_json('POST', '/api/auth/login', json_body={'username': username, 'password': password})
    if isinstance(payload, _facade().JSONResponse):
        try:
            status_code = int(payload.status_code or 502)
        except (TypeError, ValueError):
            status_code = 502
        if demo_shim and _facade()._is_local_market_base(market_base) and (status_code >= 400):
            return _facade()._demo_market_login_payload(demo_shim, market_base_url=market_base)
    result = await _facade()._normalize_market_auth_payload(payload, market_base=market_base)
    if not result.get('success') and demo_shim and _facade()._is_local_market_base(market_base):
        sc = int(result.get('status_code') or 502)
        if sc >= 400:
            return _facade()._demo_market_login_payload(demo_shim, market_base_url=market_base)
    return result

async def login_market_with_phone_code(phone: str, code: str) -> dict[str, _facade().Any]:
    """Authenticate against market via phone verification code."""
    market_base = _facade()._market_base_url()
    payload = await _facade()._proxy_json('POST', '/api/auth/login-with-phone-code', json_body={'phone': (phone or '').strip(), 'code': (code or '').strip()})
    return await _facade()._normalize_market_auth_payload(payload, market_base=market_base)

def _market_internal_api_key() -> str:
    return (_facade().os.environ.get('XCAGI_MARKET_INTERNAL_API_KEY') or _facade().os.environ.get('XCAGI_CS_INTAKE_LINK_SECRET') or '').strip()

async def ensure_market_enterprise_profile(market_user_id: int | str | None, *, username: str='', company: str='', mod_ids: list[str] | tuple[str, ...] | None=None) -> dict[str, _facade().Any]:
    """Mark a registered market account as enterprise through the internal market API."""
    try:
        uid = int(str(market_user_id or '').strip())
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        return {'success': False, 'message': '修茈市场注册成功但未返回用户ID，无法标记企业账号', 'market_base_url': _facade()._market_base_url()}
    internal_key = _facade()._market_internal_api_key()
    if not internal_key:
        return {'success': False, 'message': '未配置 XCAGI_MARKET_INTERNAL_API_KEY，无法标记市场企业账号', 'market_base_url': _facade()._market_base_url()}
    body: dict[str, _facade().Any] = {'market_user_id': uid, 'company': (company or '').strip(), 'display_name': (username or '').strip()}
    requested_mod_ids = _facade()._dedupe_mod_ids([str(x) for x in mod_ids or []])
    if requested_mod_ids:
        body['mod_ids'] = requested_mod_ids
    payload = await _facade()._proxy_json('POST', '/api/internal/cs-intake/ensure-enterprise-profile', json_body=body, extra_headers={'X-Internal-Api-Key': internal_key}, return_error_payload=True)
    if isinstance(payload, _facade().JSONResponse):
        return {'success': False, 'message': '市场服务不可用，无法标记企业账号', 'status_code': int(getattr(payload, 'status_code', 502) or 502), 'market_base_url': _facade()._market_base_url()}
    if isinstance(payload, dict) and payload.get('__proxy_error__'):
        status_code = int(payload.get('status_code') or 502)
        raw = payload.get('payload')
        return {'success': False, 'message': _facade()._error_message(raw, status_code) or '市场企业标记失败', 'status_code': status_code, 'raw': raw, 'market_base_url': _facade()._market_base_url()}
    if not isinstance(payload, dict):
        return {'success': False, 'message': '市场企业标记返回格式异常', 'raw': payload, 'market_base_url': _facade()._market_base_url()}
    is_enterprise = _facade()._truthy_identity_flag(payload.get('is_enterprise')) or _facade()._truthy_identity_flag(payload.get('market_is_enterprise'))
    if not (payload.get('ok') or payload.get('success')) or not is_enterprise:
        return {'success': False, 'message': str(payload.get('message') or payload.get('detail') or '市场企业标记失败'), 'raw': payload, 'market_base_url': _facade()._market_base_url()}
    return {'success': True, 'market_user_id': uid, 'username': str(payload.get('username') or username or '').strip(), 'is_enterprise': True, 'mod_ids': [str(x).strip() for x in payload.get('mod_ids') or requested_mod_ids if str(x or '').strip()], 'added_mod_ids': [str(x).strip() for x in payload.get('added_mod_ids') or [] if str(x or '').strip()], 'raw': payload, 'market_base_url': _facade()._market_base_url()}

def _dedupe_mod_ids(mod_ids: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in mod_ids:
        mid = str(raw or '').strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out

def enterprise_mod_ids_for_industry(industry_id: str) -> list[str]:
    """Resolve the MODstore entitlements implied by a selected industry."""
    iid = str(industry_id or '').strip()
    if not iid:
        return []
    mod_ids: list[str] = []
    try:
        from app.mod_sdk.industry_seed import industry_mod_id_for
        mid = str(industry_mod_id_for(iid) or '').strip()
        if mid:
            mod_ids.append(mid)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('enterprise_mod_ids_for_industry: industry_seed failed industry=%s', iid)
    try:
        from app.mod_sdk.industry_mod_aliases import canonical_mod_id_for_industry
        mid = str(canonical_mod_id_for_industry(iid) or '').strip()
        if mid:
            mod_ids.append(mid)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('enterprise_mod_ids_for_industry: alias failed industry=%s', iid)
    try:
        from app.mod_sdk.customer_delivery import deliveries_for_industry
        for row in deliveries_for_industry(iid):
            if not isinstance(row, dict):
                continue
            mid = str(row.get('industry_mod_id') or '').strip()
            if mid:
                mod_ids.append(mid)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('enterprise_mod_ids_for_industry: delivery failed industry=%s', iid)
    return _facade()._dedupe_mod_ids(mod_ids)

async def grant_market_enterprise_entitlements_for_session(session_id: str, industry_id: str) -> dict[str, _facade().Any]:
    """Grant selected-industry MODstore entitlements for the current FHD session."""
    sid = str(session_id or '').strip()
    mod_ids = _facade().enterprise_mod_ids_for_industry(industry_id)
    if not mod_ids:
        return {'success': True, 'mod_ids': [], 'added_mod_ids': []}
    if not sid:
        return {'success': False, 'message': '缺少登录会话，无法写入市场行业权限'}
    market_user_id: int | None = None
    try:
        from app.application.session_account_meta import load_session_account_meta
        meta = load_session_account_meta(sid) or {}
        raw_uid = meta.get('market_user_id')
        if raw_uid is not None:
            market_user_id = int(raw_uid)
    except (TypeError, ValueError):
        market_user_id = None
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('grant_market_enterprise_entitlements: load session meta failed')
    if market_user_id is None:
        token = await _facade().resolve_valid_market_access_token(sid)
        from app.enterprise.mod_entitlements import _market_user_id_from_access_token
        market_user_id = _market_user_id_from_access_token(token)
    if market_user_id is None:
        return {'success': False, 'message': '当前会话没有市场用户ID，无法写入市场行业权限'}
    return await _facade().ensure_market_enterprise_profile(market_user_id, mod_ids=mod_ids)

def _oidc_identity_from_profile(profile: dict[str, _facade().Any]) -> tuple[str, str, str]:
    username = str(profile.get('preferred_username') or profile.get('email') or profile.get('sub') or '').strip()
    email = str(profile.get('email') or '').strip()
    oidc_sub = str(profile.get('sub') or '').strip()
    return (username, email, oidc_sub)

async def login_market_for_oidc_profile(profile: dict[str, _facade().Any], *, oidc_access_token: str='') -> dict[str, _facade().Any]:
    """OIDC SSO 后自动签发/绑定 MODstore JWT（内部桥接；可选 IdP bearer 探测）。"""
    market_base = _facade()._market_base_url()
    (username, email, oidc_sub) = _facade()._oidc_identity_from_profile(profile or {})
    if not username and (not email):
        return {'success': False, 'message': 'OIDC 未返回可用于市场同步的身份字段', 'market_base_url': market_base}
    oidc_tok = _facade()._normalize_bearer_token(oidc_access_token or '')
    if oidc_tok:
        me_payload = await _facade()._proxy_json('GET', '/api/auth/me', authorization=f'Bearer {oidc_tok}', return_error_payload=True)
        if isinstance(me_payload, dict) and (not me_payload.get('__proxy_error__')):
            (is_enterprise, is_market_admin, user_blob) = _facade()._market_identity_from_payloads(me_payload, me_payload)
            raw_out: dict[str, _facade().Any] = dict(me_payload) if isinstance(me_payload, dict) else {}
            if user_blob and (not isinstance(raw_out.get('user'), dict)):
                raw_out['user'] = user_blob
            return {'success': True, 'market_base_url': market_base, 'token': oidc_tok, 'refresh_token': '', 'is_enterprise': is_enterprise, 'is_market_admin': is_market_admin, 'raw': raw_out}
    internal_key = _facade()._market_internal_api_key()
    if not internal_key:
        return {'success': False, 'message': '未配置 XCAGI_MARKET_INTERNAL_API_KEY，SSO 会话无法自动绑定修茈市场 token', 'market_base_url': market_base}
    payload = await _facade()._proxy_json('POST', '/api/auth/internal/sso-issue-token', json_body={'username': username, 'email': email, 'oidc_sub': oidc_sub, 'display_name': str(profile.get('name') or profile.get('given_name') or username).strip()[:128]}, extra_headers={'X-Internal-Api-Key': internal_key}, return_error_payload=True)
    if isinstance(payload, dict) and payload.get('__proxy_error__'):
        raw = payload.get('payload') if isinstance(payload.get('payload'), dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        msg = str(raw.get('detail') or raw.get('message') or '市场 SSO 桥接失败')
        return {'success': False, 'message': msg, 'status_code': int(payload.get('status_code') or 502), 'market_base_url': market_base}
    return await _facade()._normalize_market_auth_payload(payload, market_base=market_base)

async def send_market_phone_code(phone: str) -> dict[str, _facade().Any]:
    """Proxy send-phone-code to market."""
    payload = await _facade()._proxy_json('POST', '/api/auth/send-phone-code', json_body={'phone': (phone or '').strip()})
    if isinstance(payload, _facade().JSONResponse):
        try:
            raw_body = _facade().json.loads(bytes(payload.body).decode('utf-8') if payload.body else '{}')
        except _facade().RECOVERABLE_ERRORS:
            raw_body = {}
        return {'success': False, 'message': str(raw_body.get('message') or raw_body.get('detail') or '发送验证码失败'), 'status_code': int(payload.status_code or 502)}
    if isinstance(payload, dict):
        return {'success': True, 'message': str(payload.get('message') or '验证码已发送')}
    return {'success': True, 'message': '验证码已发送'}

@_facade().router.post('/send-phone-code')
async def market_send_phone_code(body: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    phone = str(body.get('phone') or '').strip()
    if not phone:
        return _facade().JSONResponse({'success': False, 'message': '请填写手机号'}, status_code=400)
    result = await _facade().send_market_phone_code(phone)
    if not result.get('success'):
        status = int(result.get('status_code') or 502)
        return _facade().JSONResponse(result, status_code=status if status >= 400 else 502)
    return {'success': True, 'message': result.get('message') or '验证码已发送'}

@_facade().router.post('/send-register-code')
async def market_send_register_code(body: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    result = await _facade().send_market_register_code(str(body.get('email') or ''))
    if not result.get('success'):
        status = int(result.get('status_code') or 502)
        return _facade().JSONResponse(result, status_code=status if status >= 400 else 502)
    return {'success': True, 'message': result.get('message') or '验证码已发送'}

@_facade().router.post('/login-with-phone-code')
async def market_login_with_phone_code_route(body: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    phone = str(body.get('phone') or '').strip()
    code = str(body.get('code') or '').strip()
    if not phone or not code:
        return _facade().JSONResponse({'success': False, 'message': '请填写手机号和验证码'}, status_code=400)
    result = await _facade().login_market_with_phone_code(phone, code)
    if not result.get('success'):
        status = int(result.get('status_code') or 401)
        return _facade().JSONResponse({'success': False, 'message': result.get('message'), 'error': {'code': result.get('error_code') or 'MARKET_AUTH_FAILED', 'message': result.get('message')}}, status_code=status if status >= 400 else 401)
    return {'success': True, 'data': {'token': result.get('token'), 'refresh_token': result.get('refresh_token'), 'market_base_url': result.get('market_base_url')}}

@_facade().router.post('/account-sync')
async def market_account_sync(request: _facade().Request, body: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    authorization = _facade()._auth_header(str(body.get('authorization') or body.get('token') or ''))
    if not authorization:
        hdr = str(request.headers.get('Authorization') or request.headers.get('authorization') or '').strip()
        if hdr:
            authorization = _facade()._auth_header(hdr)
    if not authorization:
        return _facade().JSONResponse({'success': False, 'message': 'authorization 必填'}, status_code=400)
    payload = await _facade()._proxy_json('GET', '/api/auth/me', authorization=authorization)
    if isinstance(payload, _facade().JSONResponse):
        return payload
    _facade().save_session_market_token(_facade().session_id_from_request(request), _facade()._normalize_bearer_token(authorization))
    data = payload.get('data') if isinstance(payload, dict) and isinstance(payload.get('data'), dict) else payload
    user = data.get('user') if isinstance(data, dict) and isinstance(data.get('user'), dict) else data
    return {'success': True, 'data': {'user': user, 'market_base_url': _facade()._market_base_url()}}

def _degraded_account_overview(message: str) -> dict[str, _facade().Any]:
    """Market unreachable — return 200 so SPA can still show wallet/plan links."""
    return {'degraded': True, 'market_unreachable': True, 'sync_warning': message, 'user': {}, 'wallet': {'balance': None}, 'membership': {'label': '未同步', 'tier': 'unknown', 'can_byok': False}, 'quotas': [], 'llm': {'providers': []}, 'market_base_url': _facade()._market_base_url()}

def _merge_live_overview_fields(data: dict[str, _facade().Any], live: dict[str, _facade().Any]) -> None:
    for key in ('wallet', 'plan', 'membership', 'quotas'):
        if live.get(key) is not None:
            data[key] = live.get(key)
    if isinstance(live.get('llm'), dict):
        raw_current_llm = data.get('llm')
        current_llm: dict[str, _facade().Any] = dict(raw_current_llm) if isinstance(raw_current_llm, dict) else {}
        data['llm'] = {**current_llm, **dict(live['llm'])}
    if live.get('user') is not None:
        data['user'] = live.get('user')

@_facade().router.post('/account-overview')
async def market_account_overview(request: _facade().Request, body: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    try:
        authorization = await _facade()._authorization_from_request_resolved(request, body)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('market_account_overview: resolve authorization failed')
        return {'success': True, 'data': _facade()._degraded_account_overview(f'读取市场令牌失败：{exc}')}
    if not authorization:
        return _facade().JSONResponse({'success': False, 'message': '尚未绑定市场账号；请重新登录软件以自动同步'}, status_code=401)
    cache_key = _facade()._overview_cache_key(authorization)
    if not bool(body.get('refresh')):
        cached = _facade()._ACCOUNT_OVERVIEW_CACHE.get(cache_key)
        if cached is not None:
            (stored_at, cached_data) = cached
            if _facade().time.monotonic() - stored_at <= _facade()._account_overview_cache_ttl():
                cached_overview = dict(cached_data)
                cached_overview.setdefault('market_base_url', _facade()._market_base_url())
                return {'success': True, 'data': cached_overview}
            _facade()._ACCOUNT_OVERVIEW_CACHE.pop(cache_key, None)
    try:
        payload = await _facade()._proxy_json('GET', '/api/account/bootstrap', authorization=authorization, return_error_payload=True)
        data: dict[str, _facade().Any] | None = None
        sync_warning = ''
        if isinstance(payload, _facade().JSONResponse):
            try:
                import json as _json
                proxy_body = _json.loads(bytes(payload.body).decode() if payload.body else '{}')
                err = str(proxy_body.get('message') or proxy_body.get('detail') or '市场服务不可用')
            except _facade().RECOVERABLE_ERRORS:
                err = '市场服务不可用'
            data = _facade()._degraded_account_overview(err)
            sync_warning = err
        elif isinstance(payload, dict) and (not payload.get('__proxy_error__')):
            raw = payload.get('data') if isinstance(payload.get('data'), dict) else payload
            data = dict(raw) if isinstance(raw, dict) else None
            if isinstance(data, dict):
                if _facade()._market_account_live.bootstrap_overview_needs_live_merge(data):
                    live = await _facade()._legacy_account_overview(authorization)
                    if isinstance(live, dict) and (not live.get('__proxy_error__')):
                        _facade()._merge_live_overview_fields(data, live)
                    elif isinstance(live, dict) and live.get('__proxy_error__'):
                        sync_warning = _facade()._error_message(live.get('payload'), int(live.get('status_code') or 502))
        if data is None:
            legacy = await _facade()._legacy_account_overview(authorization)
            if isinstance(legacy, dict) and (not legacy.get('__proxy_error__')):
                data = legacy
            else:
                err = ''
                if isinstance(legacy, dict) and legacy.get('__proxy_error__'):
                    err = _facade()._error_message(legacy.get('payload'), int(legacy.get('status_code') or 502))
                elif isinstance(payload, dict) and payload.get('__proxy_error__'):
                    err = _facade()._error_message(payload.get('payload'), int(payload.get('status_code') or 502))
                else:
                    err = '无法连接修茈市场服务器'
                data = _facade()._degraded_account_overview(err)
                _facade().logger.warning('market_account_overview degraded: %s (base=%s)', err, _facade()._market_base_url())
        if not isinstance(data, dict):
            data = _facade()._degraded_account_overview('市场账户概览返回格式异常')
        sync_warning = await _facade()._market_account_live.refresh_overview_wallet(data, authorization, sync_warning, proxy_json=_facade()._proxy_json, error_message=_facade()._error_message)
        data = {**data, 'market_base_url': _facade()._market_base_url()}
        if sync_warning and (not data.get('sync_warning')):
            data['sync_warning'] = sync_warning
        _facade()._ACCOUNT_OVERVIEW_CACHE[cache_key] = (_facade().time.monotonic(), dict(data))
        return {'success': True, 'data': data}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception('market_account_overview failed')
        return {'success': True, 'data': _facade()._degraded_account_overview(f'账户概览异常：{exc}')}

async def _market_llm_catalog_impl(request: _facade().Request, body: dict[str, _facade().Any]):
    authorization = await _facade()._authorization_from_request_resolved(request, body)
    if not authorization:
        return _facade().JSONResponse({'success': False, 'message': '尚未绑定市场账号；请重新登录软件以自动同步'}, status_code=401)
    refresh = '1' if bool(body.get('refresh')) else '0'
    payload = await _facade()._proxy_json('GET', f'/api/llm/catalog?refresh={refresh}', authorization=authorization, return_error_payload=True)
    if isinstance(payload, _facade().JSONResponse):
        return _facade()._market_account_live.degraded_llm_catalog(payload, _facade()._market_base_url())
    if isinstance(payload, dict) and payload.get('__proxy_error__'):
        status_code = int(payload.get('status_code') or 502)
        raw_error = payload.get('payload')
        msg = _facade()._error_message(raw_error, status_code)
        return {'success': True, 'data': {'degraded': True, 'providers': [], 'sync_warning': msg, 'market_base_url': _facade()._market_base_url()}}
    if not isinstance(payload, dict):
        return {'success': True, 'data': {'degraded': True, 'providers': [], 'sync_warning': '模型目录返回格式异常', 'market_base_url': _facade()._market_base_url()}}
    return {'success': True, 'data': {**payload, 'market_base_url': _facade()._market_base_url()}}

@_facade().router.post('/llm-catalog')
async def market_llm_catalog_post(request: _facade().Request, body: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    return await _facade()._market_llm_catalog_impl(request, body)

@_facade().router.get('/llm-catalog')
async def market_llm_catalog_get(request: _facade().Request, refresh: bool=False):
    return await _facade()._market_llm_catalog_impl(request, {'refresh': refresh})

async def _legacy_account_overview(authorization: str) -> dict[str, _facade().Any]:
    """Compose account overview from older market APIs when /api/account/bootstrap is not deployed."""
    me = await _facade()._proxy_json('GET', '/api/auth/me', authorization=authorization, return_error_payload=True)
    if isinstance(me, dict) and me.get('__proxy_error__'):
        return me
    wallet = await _facade()._proxy_json('GET', '/api/wallet/overview', authorization=authorization, return_error_payload=True)
    if isinstance(wallet, dict) and wallet.get('__proxy_error__'):
        balance = await _facade()._proxy_json('GET', '/api/wallet/balance', authorization=authorization, return_error_payload=True)
        wallet_data = {} if isinstance(balance, dict) and balance.get('__proxy_error__') else {'wallet': balance}
    else:
        wallet_data = wallet if isinstance(wallet, dict) else {}
    plan = await _facade()._proxy_json('GET', '/api/payment/my-plan', authorization=authorization, return_error_payload=True)
    plan_data = {} if isinstance(plan, dict) and plan.get('__proxy_error__') else plan if isinstance(plan, dict) else {}
    llm = await _facade()._proxy_json('GET', '/api/llm/status', authorization=authorization, return_error_payload=True)
    llm_data = {} if isinstance(llm, dict) and llm.get('__proxy_error__') else llm if isinstance(llm, dict) else {}
    user = me.get('user') if isinstance(me, dict) and isinstance(me.get('user'), dict) else me
    wallet_obj = wallet_data.get('wallet') if isinstance(wallet_data.get('wallet'), dict) else wallet_data
    return {'success': True, 'user': user, 'wallet': wallet_obj, 'plan': plan_data.get('plan'), 'membership': plan_data.get('membership'), 'quotas': plan_data.get('quotas') or [], 'llm': {'providers': llm_data.get('providers') or [], 'fernet_configured': llm_data.get('fernet_configured'), 'byok_configured_count': len([p for p in llm_data.get('providers') or [] if p.get('has_user_override')])}}

def _market_auth_from_request(request: _facade().Request) -> str:
    sid = _facade().session_id_from_request(request)
    tok = _facade().session_market_token(sid)
    if tok:
        return tok
    return str(request.headers.get('Authorization') or '').strip()

@_facade().router.get('/payment/plans')
async def market_payment_plans(request: _facade().Request):
    """修茈市场套餐（含微信/支付宝统一收银，Java SoT）。"""
    payload = await _facade()._proxy_json('GET', '/api/payment/plans', authorization=_facade()._market_auth_from_request(request), return_error_payload=True)
    if isinstance(payload, dict) and payload.get('__proxy_error__'):
        return _facade().JSONResponse({'success': False, 'message': _facade()._error_message(payload.get('payload'), int(payload.get('status_code') or 502))}, status_code=int(payload.get('status_code') or 502))
    return {'success': True, 'data': payload, 'market_base_url': _facade()._market_base_url()}

@_facade().router.post('/payment/checkout')
async def market_payment_checkout(request: _facade().Request, body: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    payload = await _facade()._proxy_json('POST', '/api/payment/checkout', json_body=body, authorization=_facade()._market_auth_from_request(request), return_error_payload=True)
    if isinstance(payload, dict) and payload.get('__proxy_error__'):
        return _facade().JSONResponse({'success': False, 'message': _facade()._error_message(payload.get('payload'), int(payload.get('status_code') or 502))}, status_code=int(payload.get('status_code') or 502))
    return {'success': True, 'data': payload}
