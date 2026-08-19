# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.xcmax_admin')

async def _self_maintenance_local_or_proxy(request: _facade().Request, method: str, path: str, *, json_body: dict[str, _facade().Any] | None=None):
    """自维护 loop runtime：优先本地 MODstore :8788，远端 market-proxy 404 时再试本地。"""
    if not path.startswith('/api/ops/self-maintenance/'):
        return None
    from app.application import self_maintenance_app_service as sm_svc
    from app.application.modstore_local_client import prefer_local_modstore
    from app.fastapi_routes.market_account import _authorization_from_request
    authorization = _authorization_from_request(request, json_body or {})

    async def _call_local() -> dict[str, _facade().Any] | None:
        if path.startswith('/api/ops/self-maintenance/status'):
            limit = 80
            if '?' in path:
                for part in path.split('?', 1)[1].split('&'):
                    if part.startswith('limit='):
                        try:
                            limit = int(part.split('=', 1)[1])
                        except ValueError:
                            pass
            return await sm_svc.get_runtime_status_local(limit=limit, authorization=authorization)
        if path == '/api/ops/self-maintenance/governance-review' and method.upper() == 'POST':
            note = str((json_body or {}).get('note') or '')
            return await sm_svc.governance_review_local(note=note, authorization=authorization)
        if path == '/api/ops/self-maintenance/run' and method.upper() == 'POST':
            reason = str((json_body or {}).get('reason') or 'admin_force_run')
            return await sm_svc.force_run_local(reason=reason, authorization=authorization)
        return None
    if prefer_local_modstore():
        try:
            local_payload = await _call_local()
            if local_payload is not None:
                return local_payload
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning('local self-maintenance failed path=%s: %s', path, exc)
    proxied = await _facade()._market_admin_proxy(request, method, path, json_body=json_body)
    if isinstance(proxied, _facade().JSONResponse) and proxied.status_code == 404:
        try:
            local_payload = await _call_local()
            if local_payload is not None:
                return local_payload
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning('self-maintenance local fallback after upstream 404 path=%s: %s', path, exc)
    return proxied

async def _remote_duty_health(request: _facade().Request) -> dict[str, _facade().Any]:
    health_payload = await _facade()._market_admin_proxy(request, 'GET', '/api/admin/duty-graph/health')
    if isinstance(health_payload, dict):
        return health_payload
    if hasattr(health_payload, 'body'):
        try:
            return _facade().cast('dict[str, Any]', _facade().json.loads(getattr(health_payload, 'body', b'') or b'{}'))
        except _facade().RECOVERABLE_ERRORS:
            return {}
    return {}

def _collect_mod_modules() -> list[dict[str, _facade().Any]]:
    """从 mod_manager 读取已加载的本地 Mod，转换成 XCmax 模块格式。"""
    rows: list[dict[str, _facade().Any]] = []
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager
        mgr = get_mod_manager()
        if mgr is None:
            return rows
        registry = getattr(mgr, '_registry', None) or {}
        for (mod_id, meta) in registry.items() if hasattr(registry, 'items') else []:
            name = str(getattr(meta, 'name', None) or mod_id).strip()
            version = str(getattr(meta, 'version', None) or '').strip()
            rows.append({'module_id': str(mod_id), 'display_name': name, 'route': f'/mod/{mod_id}', 'source': 'local', 'sync_scope': 'module_info', 'active': True, 'version': version})
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug('collect_mod_modules failed: %s', exc)
    return rows

def _collect_employee_pack_modules() -> list[dict[str, _facade().Any]]:
    """从员工包注册表读取员工包，转换成 XCmax 模块格式。"""
    rows: list[dict[str, _facade().Any]] = []
    try:
        from app.infrastructure.mods.employee_registry import EmployeeRegistry
        from app.infrastructure.mods.mod_manager import get_mod_manager
        mgr = get_mod_manager()
        mods_root = getattr(mgr, 'mods_root', None) if mgr else None
        if mods_root:
            registry = EmployeeRegistry(mods_root)
            for pack in registry.list_packs():
                pack_id = str(pack.get('id') or '')
                name = str(pack.get('name') or pack_id).strip()
                rows.append({'module_id': pack_id, 'display_name': name, 'route': '', 'source': 'employee', 'sync_scope': 'employee_pack', 'active': True, 'version': str(pack.get('version') or '')})
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug('collect_employee_pack_modules failed: %s', exc)
    return rows

@_facade().router.get('/admin/market/users', response_model=None)
async def admin_list_market_users(request: _facade().Request):
    return await _facade()._market_admin_proxy(request, 'GET', '/api/admin/users')

@_facade().router.post('/admin/market/users', response_model=None)
async def admin_create_market_user(request: _facade().Request, payload: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    from app.application.session_account_meta import audit_admin_action
    from app.fastapi_routes.market_account import register_market_user
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    username = str(payload.get('username') or '').strip()
    password = str(payload.get('password') or '')
    email = str(payload.get('email') or '').strip()
    verification_code = str(payload.get('verification_code') or payload.get('code') or '').strip()
    if not username or not password:
        return _facade().JSONResponse({'success': False, 'message': 'username、password 必填'}, status_code=422)
    if len(password) < 6:
        return _facade().JSONResponse({'success': False, 'message': 'password 至少 6 位'}, status_code=422)
    if not email:
        email = f'{username.lower()}@xcagi.local'
    result = await register_market_user(username, password, email, verification_code)
    if not result.get('success'):
        return _facade().JSONResponse({'success': False, 'message': result.get('message') or '创建账号失败', 'data': result.get('raw')}, status_code=400)
    audit_admin_action(request, 'create_market_user', target_user_id=result.get('market_user_id'), detail=f'username={username}')
    return {'success': True, 'data': {'market_user_id': result.get('market_user_id'), 'username': username, 'email': email, 'market_base_url': result.get('market_base_url'), 'raw': result.get('raw')}}

@_facade().router.get('/admin/market/assignable-mods', response_model=None)
async def admin_list_assignable_mods(request: _facade().Request):
    return await _facade()._market_admin_proxy(request, 'GET', '/api/admin/enterprise/assignable-mods')

@_facade().router.get('/admin/market/wallets', response_model=None)
async def admin_list_wallets(request: _facade().Request):
    """代理远端 ``/api/admin/wallets``，返回所有用户钱包余额。

    远端返回 ``{items: [{id, user_id, balance, updated_at}], total}``。
    """
    limit = request.query_params.get('limit', '500')
    offset = request.query_params.get('offset', '0')
    return await _facade()._market_admin_proxy(request, 'GET', f'/api/admin/wallets?limit={limit}&offset={offset}')

@_facade().router.get('/admin/market/orders', response_model=None)
async def admin_list_orders(request: _facade().Request):
    """经营看板：代理 MODstore ``/api/admin/orders``（订单列表 + 经营聚合）。

    打通「AI 不知道订单」断点：管理端经此接口读取平台订单数据，供 AI 员工感知与处理。
    """
    q = []
    if request.query_params.get('status'):
        q.append(f"status={request.query_params['status']}")
    if request.query_params.get('limit'):
        q.append(f"limit={request.query_params['limit']}")
    if request.query_params.get('offset'):
        q.append(f"offset={request.query_params['offset']}")
    query = '?' + '&'.join(q) if q else ''
    return await _facade()._market_admin_proxy(request, 'GET', f'/api/admin/orders{query}')

@_facade().router.post('/admin/market/users/{user_id}/wallet/credit', response_model=None)
async def admin_credit_user_wallet(request: _facade().Request, user_id: int, payload: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    from app.application.session_account_meta import audit_admin_action
    try:
        amount = float(payload.get('amount') or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        return _facade().JSONResponse({'success': False, 'message': '加款金额必须大于 0'}, status_code=422)
    description = str(payload.get('description') or '').strip() or '后台加款'
    out = await _facade()._market_admin_proxy(request, 'POST', f'/api/admin/users/{user_id}/wallet/credit', json_body={'amount': amount, 'description': description})
    audit_admin_action(request, 'credit_user_wallet', target_user_id=user_id, detail=f'amount={amount}')
    return out

@_facade().router.get('/admin/market/users/{user_id}/mods', response_model=None)
async def admin_list_user_mods(request: _facade().Request, user_id: int):
    return await _facade()._market_admin_proxy(request, 'GET', f'/api/admin/users/{user_id}/mods')

@_facade().router.post('/admin/market/users/{user_id}/mods/{mod_id}', response_model=None)
async def admin_bind_user_mod(request: _facade().Request, user_id: int, mod_id: str):
    from app.application.session_account_meta import audit_admin_action
    out = await _facade()._market_admin_proxy(request, 'POST', f'/api/admin/users/{user_id}/mods/{mod_id}')
    audit_admin_action(request, 'bind_user_mod', target_user_id=user_id, mod_id=mod_id)
    return out

@_facade().router.delete('/admin/market/users/{user_id}/mods/{mod_id}', response_model=None)
async def admin_unbind_user_mod(request: _facade().Request, user_id: int, mod_id: str):
    from app.application.session_account_meta import audit_admin_action
    out = await _facade()._market_admin_proxy(request, 'DELETE', f'/api/admin/users/{user_id}/mods/{mod_id}')
    audit_admin_action(request, 'unbind_user_mod', target_user_id=user_id, mod_id=mod_id)
    return out

@_facade().router.put('/admin/market/users/{user_id}/admin', response_model=None)
async def admin_set_user_admin(request: _facade().Request, user_id: int, is_admin: bool=_facade().Query(...)):
    return await _facade()._market_admin_proxy(request, 'PUT', f"/api/admin/users/{user_id}/admin?is_admin={('true' if is_admin else 'false')}")

@_facade().router.put('/admin/market/users/{user_id}/enterprise', response_model=None)
async def admin_set_user_enterprise(request: _facade().Request, user_id: int, is_enterprise: bool=_facade().Query(...)):
    return await _facade()._market_admin_proxy(request, 'PUT', f"/api/admin/users/{user_id}/enterprise?is_enterprise={('true' if is_enterprise else 'false')}")

def _clean_string_list(raw: _facade().Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for item in raw:
        text = str(item or '').strip()
        if text and text not in result:
            result.append(text)
    return result

def _truthy(raw: _facade().Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return raw != 0
    if isinstance(raw, str):
        return raw.strip().lower() in {'1', 'true', 'yes', 'y', 'on'}
    return False

@_facade().router.put('/admin/users/{user_id}/profile', response_model=None)
async def admin_set_user_profile(request: _facade().Request, user_id: int, payload: dict=_facade().Body(...)):
    """设置用户账号体系字段（本地 User 表持久化）。

    body: {
        username: str,
        tier?: personal|enterprise|admin,
        industry_id?: str,
        account_tier?: normal|pro|max|ultra,   # 仅 enterprise 可设
        budget_range?: str,
        entitled_industries?: list[str],
    }
    校验：account_tier 仅企业可设；industry_id 必须 ∈ entitled_industries（显式提供时）。
    """
    from app.application.account_tier_derivation import VALID_ACCOUNT_TIERS, normalize_account_tier, should_have_account_tier
    from app.application.entitled_industries_init import merge_entitled_industries, validate_industry_in_entitled
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    username = str(payload.get('username') or '').strip()
    tier = str(payload.get('tier') or '').strip()
    industry_id = str(payload.get('industry_id') or '').strip()
    account_tier = str(payload.get('account_tier') or '').strip()
    budget_range = str(payload.get('budget_range') or '').strip()
    entitled_raw = payload.get('entitled_industries')
    entitled_provided = isinstance(entitled_raw, list)
    entitled_in = merge_entitled_industries([str(x or '').strip() for x in entitled_raw or []], []) if entitled_provided else None
    if not username:
        return _facade().JSONResponse({'success': False, 'message': 'username 必填'}, status_code=422)
    if tier and tier not in _facade()._VALID_TIERS:
        return _facade().JSONResponse({'success': False, 'message': f'tier 必须是 {sorted(_facade()._VALID_TIERS)} 之一'}, status_code=422)
    norm_account_tier = None
    if account_tier:
        norm_account_tier = normalize_account_tier(account_tier)
        if norm_account_tier is None:
            return _facade().JSONResponse({'success': False, 'message': f'account_tier 必须是 {sorted(VALID_ACCOUNT_TIERS)} 之一'}, status_code=422)
    try:
        from app.db.models.user import User
        from app.db.session import get_db
        with get_db() as db:
            user = db.query(User).filter(User.username == username).first()
            if user is None:
                user = User(username=username, password='', role='user')
                db.add(user)
                db.flush()
            final_tier = (tier or str(getattr(user, 'tier', '') or '') or 'personal').strip().lower()
            if norm_account_tier is not None and (not should_have_account_tier(final_tier)):
                return _facade().JSONResponse({'success': False, 'message': '账号等级（account_tier）仅企业用户可设置'}, status_code=422)
            current_entitled = list(getattr(user, 'entitled_industries', None) or [])
            final_entitled = entitled_in if entitled_in is not None else current_entitled
            if industry_id:
                if entitled_provided:
                    if not validate_industry_in_entitled(industry_id, final_entitled):
                        return _facade().JSONResponse({'success': False, 'message': 'industry_id 必须在 entitled_industries 内'}, status_code=422)
                else:
                    final_entitled = merge_entitled_industries(final_entitled or ['通用'], [industry_id])
            if tier:
                user.tier = tier
            if industry_id:
                user.industry_id = industry_id
            if budget_range:
                user.budget_range = budget_range
            if norm_account_tier is not None:
                user.account_tier = norm_account_tier
            elif not should_have_account_tier(final_tier):
                user.account_tier = None
            if entitled_in is not None or industry_id:
                user.entitled_industries = final_entitled
            db.commit()
            result = {'username': username, 'tier': user.tier, 'industry_id': user.industry_id, 'account_tier': user.account_tier, 'budget_range': user.budget_range, 'entitled_industries': list(getattr(user, 'entitled_industries', None) or [])}
        return {'success': True, 'data': result}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('设置用户 profile 失败: %s', exc)
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)

@_facade().router.get('/admin/users/profiles', response_model=None)
async def admin_list_user_profiles(request: _facade().Request):
    """返回本地所有用户的账号体系字段映射（按 username 索引）。

    前端拿到远端用户列表后，调此端点合并本地 profile。
    """
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    try:
        from app.db.models.user import User
        from app.db.session import get_db
        with get_db() as db:
            rows = db.query(User.username, User.tier, User.industry_id, User.account_tier, User.budget_range, User.entitled_industries).all()
        data = {r[0]: {'tier': r[1], 'industry_id': r[2], 'account_tier': r[3], 'budget_range': r[4], 'entitled_industries': list(r[5] or [])} for r in rows}
        return {'success': True, 'data': data}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('读取用户 profile 列表失败: %s', exc)
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)

@_facade().router.post('/admin/market/users/{user_id}/entitlements/push', response_model=None)
async def admin_force_push_user_entitlements(request: _facade().Request, user_id: int, payload: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    """把账号权益完整快照强制推送到企业端同步链路。

    这个接口服务管理端的“账号权益”页，不进入代管会话，也不污染桌面端当前登录态。
    """
    from app.application.session_account_meta import audit_admin_action
    from app.application.xcmax_sync_app import push_outbox, record_change
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    user_data = payload.get('user') if isinstance(payload.get('user'), dict) else {}
    profile_data = payload.get('profile') if isinstance(payload.get('profile'), dict) else {}
    wallet_data = payload.get('wallet') if isinstance(payload.get('wallet'), dict) else None
    if not isinstance(user_data, dict):
        user_data = {}
    username = str(user_data.get('username') or payload.get('username') or '').strip()
    if not username:
        return _facade().JSONResponse({'success': False, 'message': 'username 必填'}, status_code=422)
    if not isinstance(profile_data, dict):
        profile_data = {}
    tier = str(profile_data.get('tier') or user_data.get('tier') or '').strip().lower()
    if tier not in _facade()._VALID_TIERS:
        tier = 'enterprise' if _facade()._truthy(user_data.get('is_enterprise')) else 'personal'
    industry_id = str(profile_data.get('industry_id') or user_data.get('industry_id') or '通用').strip()
    entitled_industries = _facade()._clean_string_list(profile_data.get('entitled_industries'))
    if industry_id and industry_id not in entitled_industries:
        entitled_industries.append(industry_id)
    snapshot = {'market_user_id': str(user_id), 'username': username, 'email': str(user_data.get('email') or payload.get('email') or '').strip(), 'is_admin': _facade()._truthy(user_data.get('is_admin')), 'is_enterprise': _facade()._truthy(user_data.get('is_enterprise')) or tier == 'enterprise', 'profile': {'username': username, 'tier': tier, 'industry_id': industry_id or '通用', 'account_tier': str(profile_data.get('account_tier') or '').strip(), 'budget_range': str(profile_data.get('budget_range') or '').strip(), 'entitled_industries': entitled_industries}, 'mod_ids': _facade()._clean_string_list(payload.get('mod_ids')), 'wallet': wallet_data, 'workflow_employees': payload.get('workflow_employees') if isinstance(payload.get('workflow_employees'), list) else [], 'installed_mods': payload.get('installed_mods') if isinstance(payload.get('installed_mods'), list) else [], 'source': 'admin_entitlements_force_push', 'meta': {'updated_at_ms': int(_facade().time.time() * 1000), 'target': 'enterprise', 'push_mode': 'forced'}}
    change_id = record_change('account_entitlements', str(user_id), 'sync', snapshot, actor='admin')
    if change_id < 0:
        return _facade().JSONResponse({'success': False, 'message': '写入账号权益同步队列失败'}, status_code=500)
    push_result = push_outbox(remote_host=_facade().REMOTE_HOST, remote_port=_facade().REMOTE_PORT)
    if int(push_result.get('failed') or 0) > 0 or int(push_result.get('sent') or 0) <= 0:
        return _facade().JSONResponse({'success': False, 'message': '账号权益已写入本地队列，但推送企业端失败，请检查云端同步服务', 'data': {'change_id': change_id, 'snapshot': snapshot, 'push': push_result}}, status_code=502)
    audit_admin_action(request, 'force_push_user_entitlements', target_user_id=user_id, detail=f"username={username}; change_id={change_id}; sent={push_result.get('sent')}")
    return {'success': True, 'data': {'change_id': change_id, 'snapshot': snapshot, 'push': push_result}}

@_facade().router.post('/admin/impersonate', response_model=None)
async def admin_start_impersonate(request: _facade().Request, body: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    from app.application.impersonation_bridge import create_impersonation_bridge_token
    from app.application.session_account_meta import audit_admin_action, load_session_account_meta, normalize_account_kind, persist_session_account_meta
    from app.enterprise.mod_entitlements import persist_entitlements_to_session_row, refresh_session_entitlements_from_market, reload_enterprise_mods_after_login
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
    from app.fastapi_routes.market_account import resolve_valid_market_access_token
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    sid = _session_id_from_request(request)
    target_id = body.get('market_user_id')
    target_name = str(body.get('username') or '').strip()
    target_company = str(body.get('company') or body.get('company_brand') or '').strip()
    if target_id is None:
        return _facade().JSONResponse({'success': False, 'message': 'market_user_id 必填'}, status_code=400)
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        return _facade().JSONResponse({'success': False, 'message': 'market_user_id 无效'}, status_code=400)
    meta = load_session_account_meta(sid) or {}
    persist_session_account_meta(sid, account_kind=normalize_account_kind(meta.get('account_kind'), default='admin'), company_brand=target_company or str(meta.get('company_brand') or ''), market_user_id=meta.get('market_user_id'), market_is_admin=True, market_is_enterprise=bool(meta.get('market_is_enterprise')), impersonating_market_user_id=target_id, impersonating_username=target_name)
    tok = await resolve_valid_market_access_token(sid)
    if tok:
        client_ids = await refresh_session_entitlements_from_market(market_token=tok, market_user_id=meta.get('market_user_id'), market_username=target_name, session_id=sid)
        persist_entitlements_to_session_row(sid, client_ids)
        await reload_enterprise_mods_after_login()
    audit_admin_action(request, 'impersonate_start', target_user_id=target_id, detail=target_name)
    return {'success': True, 'impersonating_market_user_id': target_id, 'impersonating_username': target_name, 'bridge_token': create_impersonation_bridge_token(sid)}

@_facade().router.post('/admin/impersonate/activate-enterprise', response_model=None)
async def admin_activate_enterprise_impersonation(request: _facade().Request, body: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    from app.application.impersonation_bridge import consume_impersonation_bridge_token, mirror_admin_impersonation_to_enterprise_session
    from app.config import Config
    token = str(body.get('bridge_token') or body.get('token') or '').strip()
    if not token:
        return _facade().JSONResponse({'success': False, 'message': 'bridge_token 必填'}, status_code=400)
    admin_sid = consume_impersonation_bridge_token(token)
    if not admin_sid:
        return _facade().JSONResponse({'success': False, 'message': 'bridge_token 无效或已过期'}, status_code=400)
    enterprise_sid = str(body.get('enterprise_session_id') or request.cookies.get(getattr(Config, 'SESSION_COOKIE_NAME', 'session_id')) or '').strip()
    try:
        sid = mirror_admin_impersonation_to_enterprise_session(admin_sid, enterprise_sid or None)
    except ValueError as exc:
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=400)
    return {'success': True, 'session_id': sid}
