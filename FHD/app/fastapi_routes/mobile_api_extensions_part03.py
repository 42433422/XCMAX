# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.mobile_api_extensions')

@_facade().extension_router.get('/admin/home')
async def mobile_admin_home(request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user)):
    (meta, err) = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    (market_profiles, market_connected, market_error) = await _facade()._load_market_ai_employee_profile_index()
    employees = _facade()._admin_employee_items(market_profiles, market_connected=market_connected)
    uid = _facade()._mobile_request_user_id(request, user)
    im_summary: dict[str, dict[str, _facade().Any]] = {}
    if uid > 0 and employees:
        try:
            from app.application.im_app_service import ImApplicationService
            from app.db import SessionLocal
            db = SessionLocal()
            try:
                im_summary = ImApplicationService(db).employee_im_summary(uid, employees)
            finally:
                db.close()
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug('employee_im_summary skipped', exc_info=True)
    employees = _facade()._admin_employee_items(market_profiles, market_connected=market_connected, im_summary=im_summary)
    return _facade().format_mobile_response(data={'account_kind': meta.get('account_kind') or 'admin', 'employees': employees, 'employee_count': len(employees), 'features': _facade().ADMIN_MOBILE_FEATURES, 'feature_count': len(_facade().ADMIN_MOBILE_FEATURES), 'market_connected': market_connected, 'market_profile_count': len(market_profiles), 'market_error': market_error})

@_facade().extension_router.get('/circle/posts')
async def mobile_ai_circle_posts(limit: int=_facade().Query(default=50, ge=1, le=100), user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    from app.application.ai_circle_service import list_posts
    try:
        import importlib
        employee_circle_sync = importlib.import_module('app.application.employee_circle_sync')
        await employee_circle_sync.sync_modstore_reports()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.warning('circle: modstore report sync skipped', exc_info=True)
    (uid, _, _) = _facade()._ai_circle_user(user)
    posts = list_posts(user_id=uid, limit=limit)
    profiles = _facade()._ai_circle_employee_profiles()
    for post in posts:
        profile = profiles.get(str(post.get('employee_id') or ''))
        if profile:
            post['author_name'] = profile['name']
            post['author_avatar'] = profile['avatar'] or post.get('author_avatar')
    return _facade().format_mobile_response(data={'items': posts, 'count': len(posts)})

@_facade().extension_router.post('/circle/posts')
async def mobile_ai_circle_create_post(body: _facade().AiCirclePostBody, user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    from app.application.ai_circle_service import create_user_post
    (uid, name, avatar) = _facade()._ai_circle_user(user)
    try:
        post_id = create_user_post(user_id=uid, author_name=name, avatar=avatar, body=body.body)
        return _facade().format_mobile_response(data={'id': post_id}, message='发布成功')
    except ValueError:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '动态内容无效', success=False, code=400), status_code=400)

@_facade().extension_router.post('/circle/posts/{post_id}/like')
async def mobile_ai_circle_toggle_like(post_id: int, user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    from app.application.ai_circle_service import toggle_like
    (uid, _, _) = _facade()._ai_circle_user(user)
    try:
        liked = toggle_like(post_id=post_id, user_id=uid)
        return _facade().format_mobile_response(data={'liked': liked})
    except LookupError:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '动态不存在', success=False, code=404), status_code=404)

@_facade().extension_router.post('/circle/posts/{post_id}/comments')
async def mobile_ai_circle_add_comment(post_id: int, body: _facade().AiCircleCommentBody, user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    from app.application.ai_circle_service import add_comment
    (uid, name, _) = _facade()._ai_circle_user(user)
    try:
        comment_id = add_comment(post_id=post_id, user_id=uid, author_name=name, body=body.body)
        return _facade().format_mobile_response(data={'id': comment_id}, message='评论成功')
    except ValueError:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '评论内容无效', success=False, code=400), status_code=400)
    except LookupError:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '动态不存在', success=False, code=404), status_code=404)

@_facade().extension_router.get('/mods')
async def mobile_mods_summary(user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    (market_profiles, market_connected, market_error) = await _facade()._load_market_ai_employee_profile_index()
    return _facade().format_mobile_response(data={'items': _facade()._mobile_mod_items(market_profiles, market_connected=market_connected), 'market_connected': market_connected, 'market_profile_count': len(market_profiles), 'market_error': market_error})

@_facade().extension_router.get('/platform-shell')
async def mobile_platform_shell(user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    installed = [m['id'] for m in _facade()._mobile_mod_items()]
    from app.mod_sdk.platform_shell import build_platform_shell_payload
    return _facade().format_mobile_response(data=build_platform_shell_payload(installed))

@_facade().extension_router.get('/onboarding/industries', response_model=dict[str, _facade().Any])
async def mobile_onboarding_industries(request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user)):
    """返回移动端首次开通可选行业目录。"""
    if user is None:
        return _facade()._mobile_unauthorized_response()
    try:
        from app.mod_sdk.industry_baseline import build_onboarding_industry_catalog_for_request
        data = await build_onboarding_industry_catalog_for_request(request)
        return _facade().format_mobile_response(data=data)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile onboarding industries failed')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '行业目录加载失败', success=False, code=500), status_code=500)

@_facade().extension_router.get('/onboarding/industry-baseline', response_model=dict[str, _facade().Any])
async def mobile_industry_baseline(request: _facade().Request, industry_id: str=_facade().Query(default='通用'), user=_facade().Depends(_facade().get_mobile_user)):
    """返回指定行业的移动端初始化方案。"""
    if user is None:
        return _facade()._mobile_unauthorized_response()
    try:
        from app.mod_sdk.industry_baseline import build_industry_baseline_plan_for_request
        data = await build_industry_baseline_plan_for_request(request, industry_id)
        return _facade().format_mobile_response(data=data)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile industry baseline failed')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '行业基线加载失败', success=False, code=500), status_code=500)

@_facade().extension_router.post('/onboarding/select-industry', response_model=dict[str, _facade().Any])
async def mobile_select_onboarding_industry(body: dict[str, _facade().Any], request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user)):
    """Persist the mobile onboarding industry selection to the shared workspace SSOT."""
    if user is None:
        return _facade()._mobile_unauthorized_response()
    industry_id = str(body.get('industry_id') or body.get('industryId') or '').strip()
    industry_mod_id = str(body.get('industry_mod_id') or body.get('industryModId') or '').strip()
    if not industry_id:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '缺少 industry_id', success=False, code=400), status_code=400)
    try:
        from app.application.tenant_workspace_prefs import bind_selected_industry_for_user
        from app.fastapi_routes.market_account import grant_market_enterprise_entitlements_for_session
        data = bind_selected_industry_for_user(user, industry_id, industry_mod_id=industry_mod_id)
        try:
            market_entitlements = await grant_market_enterprise_entitlements_for_session(_facade()._mobile_session_id_from_request(request), industry_id)
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception('mobile select onboarding industry market sync failed')
            market_entitlements = {'success': False, 'message': '市场权益同步失败'}
        if not market_entitlements.get('success'):
            _facade().logger.warning('mobile onboarding industry saved while market entitlement sync failed: industry=%s message=%s', industry_id, market_entitlements.get('message'))
        return _facade().format_mobile_response(data={**(data or {}), 'market_entitlements': market_entitlements}, message='行业已绑定到当前账号')
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile select onboarding industry failed')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '行业绑定失败', success=False, code=500), status_code=500)

@_facade().extension_router.post('/mod-store/install-host-foundation', response_model=dict[str, _facade().Any])
async def mobile_install_host_foundation(edition: str | None=_facade().Query(default=None), user=_facade().Depends(_facade().get_mobile_user)):
    """为移动端账号安装宿主基础能力包。"""
    if user is None:
        return _facade()._mobile_unauthorized_response()
    try:
        from app.fastapi_routes.mod_store_routes import _install_host_foundation_internal
        result = await _install_host_foundation_internal(edition)
        return _facade().format_mobile_response(data=result.data, message=result.message, success=bool(result.success), code=200 if result.success else 409)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile install host foundation failed')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '基础员工包安装失败', success=False, code=500), status_code=500)

@_facade().extension_router.post('/mod-store/install-industry-seed', response_model=dict[str, _facade().Any])
async def mobile_install_industry_seed(body: dict[str, _facade().Any], user=_facade().Depends(_facade().get_mobile_user)):
    """按行业安装移动端初始化种子包。"""
    if user is None:
        return _facade()._mobile_unauthorized_response()
    raw = str(body.get('industry_id') or body.get('industryId') or body.get('mod_id') or '').strip()
    if not raw:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '缺少 industry_id', success=False, code=400), status_code=400)
    try:
        from app.mod_sdk.industry_seed import install_industry_seed_with_fallback
        data = await install_industry_seed_with_fallback(raw)
        if data.get('success'):
            selected_industry = str(data.get('industry_id') or '').strip()
            if selected_industry:
                from app.application.account_registration import set_account_industry
                set_account_industry(str(getattr(user, 'username', '') or ''), selected_industry)
        return _facade().format_mobile_response(data=data, message=str(data.get('message') or ''), success=bool(data.get('success')), code=200 if data.get('success') else 409)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile install industry seed failed')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '行业种子安装失败', success=False, code=500), status_code=500)

@_facade().extension_router.post('/mod-store/install', response_model=dict[str, _facade().Any])
async def mobile_install_mod(body: dict[str, _facade().Any], user=_facade().Depends(_facade().get_mobile_user)):
    """从移动端安装指定市场 Mod。"""
    if user is None:
        return _facade()._mobile_unauthorized_response()
    mod_id = str(body.get('mod_id') or body.get('pkg_id') or body.get('package_file') or '').strip()
    if not mod_id:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '缺少 mod_id', success=False, code=400), status_code=400)
    try:
        from app.fastapi_routes.mod_store_routes import _install_from_catalog
        result = await _install_from_catalog(mod_id, '', activate=True)
        return _facade().format_mobile_response(data=result.data, message=result.message, success=bool(result.success), code=200 if result.success else 409)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile install mod failed')
        return _facade().JSONResponse(_facade().format_mobile_response(None, 'MOD 安装失败', success=False, code=500), status_code=500)

@_facade().extension_router.post('/mod-store/install-customer-delivery-seed', response_model=dict[str, _facade().Any])
async def mobile_install_customer_delivery_seed(body: dict[str, _facade().Any], user=_facade().Depends(_facade().get_mobile_user)):
    """安装客户交付场景的移动端种子包。"""
    if user is None:
        return _facade()._mobile_unauthorized_response()
    mod_id = str(body.get('mod_id') or body.get('pkg_id') or '').strip()
    industry_id = str(body.get('industry_id') or body.get('industryId') or '').strip()
    if not mod_id:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '缺少 mod_id', success=False, code=400), status_code=400)
    try:
        from app.mod_sdk.customer_delivery_seed import install_customer_delivery_seed_package
        data = await install_customer_delivery_seed_package(mod_id=mod_id, industry_id=industry_id, market_token=str(body.get('market_access_token') or body.get('market_token') or body.get('token') or ''))
        return _facade().format_mobile_response(data=data, message=str(data.get('message') or ''), success=bool(data.get('success')), code=200 if data.get('success') else 409)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile install customer delivery seed failed')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '客户交付包安装失败', success=False, code=500), status_code=500)

@_facade().extension_router.get('/home')
async def mobile_home(user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    (market_profiles, market_connected, market_error) = await _facade()._load_market_ai_employee_profile_index()
    mod_items = _facade()._mobile_mod_items(market_profiles, market_connected=market_connected)
    installed = [m['id'] for m in mod_items]
    from app.mod_sdk.platform_shell import build_platform_shell_payload
    sync_data: dict[str, _facade().Any] = {}
    try:
        from app.db.xcmax_sync import SyncDb
        sync_data = SyncDb().get_status()
    except _facade().RECOVERABLE_ERRORS:
        sync_data = {'error': '市场同步失败'}
    return _facade().format_mobile_response(data={'mods': mod_items, 'market_connected': market_connected, 'market_profile_count': len(market_profiles), 'market_error': market_error, 'platform_shell': build_platform_shell_payload(installed), 'sync': sync_data})

@_facade().extension_router.get('/nav-menu')
async def mobile_nav_menu(user=_facade().Depends(_facade().get_mobile_user)):
    """返回当前用户可见的侧栏菜单项（核心菜单 + Mod 菜单）。

    供手机端"探索"Tab 配对后动态渲染工具列表，与桌面端侧栏对齐。
    """
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    user_role = str(getattr(user, 'role', '') or '').strip().lower()
    is_admin = user_role in {'admin', 'super_admin', 'owner'}
    account_kind = 'admin' if is_admin else 'enterprise'
    visible_keys = _facade()._ROLE_VISIBLE_KEYS.get(account_kind)
    items: list[dict[str, _facade().Any]] = []
    for item in _facade()._CORE_NAV_ITEMS:
        if visible_keys is not None and item['key'] not in visible_keys:
            continue
        items.append({**item, 'source': 'core'})
    if is_admin:
        items.append({**_facade()._ADMIN_NAV_ITEM, 'source': 'core'})
    try:
        mod_items = _facade()._mobile_mod_items()
        for mod in mod_items:
            mod_id = str(mod.get('id') or '').strip()
            mod_name = str(mod.get('name') or mod_id).strip()
            frontend_menu = mod.get('frontend_menu') or mod.get('menu') or []
            if not isinstance(frontend_menu, list):
                continue
            for menu_entry in frontend_menu:
                if not isinstance(menu_entry, dict):
                    continue
                menu_id = str(menu_entry.get('id') or menu_entry.get('key') or '').strip()
                if not menu_id:
                    continue
                menu_label = str(menu_entry.get('label') or menu_entry.get('name') or mod_name).strip()
                menu_path = str(menu_entry.get('path') or menu_entry.get('url') or f'/mod/{mod_id}').strip()
                menu_icon = str(menu_entry.get('icon') or menu_entry.get('iconClass') or 'fa-cube').strip()
                items.append({'key': f'mod-{menu_id}' if not menu_id.startswith('mod-') else menu_id, 'name': menu_label, 'icon': menu_icon, 'path': menu_path, 'source': 'mod', 'mod_id': mod_id})
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('nav-menu mod items failed: %s', exc)
    return _facade().format_mobile_response(data={'items': items, 'account_kind': account_kind})

def _modstore_platform_base() -> str:
    """获取 MODstore 后端 base url（如 http://127.0.0.1:8765）。"""
    return _facade().os.environ.get('MODSTORE_PLATFORM_URL', 'http://localhost:8000').rstrip('/')

def _modstore_admin_token() -> str:
    """获取调 MODstore admin API 用的 Bearer token。"""
    return _facade().os.environ.get('MODSTORE_AUTH_TOKEN', '').strip()

async def _modstore_admin_proxy(method: str, path: str, *, params: dict[str, _facade().Any] | None=None, json_body: dict[str, _facade().Any] | None=None, timeout: float=10.0) -> dict[str, _facade().Any]:
    """通用代理：调 MODstore 后端 admin API。

    返回 {"ok": bool, "status": int, "data": ..., "error": str}。
    """
    import httpx
    url = f'{_facade()._modstore_platform_base()}{path}'
    headers = {'Accept': 'application/json'}
    token = _facade()._modstore_admin_token()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, params=params, json=json_body, headers=headers)
        try:
            data = resp.json()
        except _facade().RECOVERABLE_ERRORS:
            data = {'raw': resp.text[:500]}
        if resp.is_success:
            return {'ok': True, 'status': resp.status_code, 'data': data}
        return {'ok': False, 'status': resp.status_code, 'error': str(data.get('detail') or data.get('error') or resp.text[:200])[:300]}
    except _facade().RECOVERABLE_ERRORS as exc:
        return {'ok': False, 'status': 0, 'error': f'无法连接 MODstore 后端：{_facade()._compact_text(exc)[:200]}'}

@_facade().extension_router.get('/admin/employee-pending-questions')
async def mobile_admin_employee_pending_questions(request: _facade().Request, limit: int=_facade().Query(default=50, ge=1, le=200), include_history: bool=_facade().Query(default=False), employee_id: str | None=_facade().Query(default=None), user=_facade().Depends(_facade().get_mobile_user)):
    """拉员工 Phase-D 主动提问列表（pending 优先）。

    GET /api/mobile/v1/admin/employee-pending-questions
      ?limit=50&include_history=false&employee_id=llm-ops-engineer

    返回 {"items": [...], "count": N, "market_connected": bool}
    每个 item 含：id / employee_id / task / question / status / asked_at / answer / answered_at
    """
    (meta, err) = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    params: dict[str, _facade().Any] = {'limit': limit, 'include_expired': bool(include_history)}
    if employee_id:
        params['employee_id'] = employee_id
    out = await _facade()._modstore_admin_proxy('GET', '/api/admin/employee-autonomy/questions', params=params)
    if not out.get('ok'):
        return _facade().format_mobile_response(None, f"拉员工提问失败：{out.get('error') or '未知错误'}", success=False, code=out.get('status') or 502)
    data = out.get('data') if isinstance(out.get('data'), dict) else {}
    if not isinstance(data, dict):
        data = {}
    items = data.get('items') if isinstance(data.get('items'), list) else []
    return _facade().format_mobile_response(data={'items': items, 'count': int(data.get('count') or len(items or [])), 'market_connected': bool(out.get('ok'))})

@_facade().extension_router.post('/admin/employee-pending-questions/{question_id}/answer')
async def mobile_admin_employee_pending_question_answer(question_id: int, body: dict[str, _facade().Any], request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user)):
    """老板回答员工的 Phase-D 提问。

    POST /api/mobile/v1/admin/employee-pending-questions/{id}/answer
    body: {"answer": "先做 A，因为..."}

    成功后员工执行管道被阻塞的 ask_human_blocking() 会拿到答案继续执行。
    """
    (meta, err) = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    answer_text = str((body or {}).get('answer') or '').strip()
    if not answer_text:
        return _facade().format_mobile_response(None, 'answer 字段不能为空', success=False, code=400)
    out = await _facade()._modstore_admin_proxy('POST', f'/api/admin/employee-autonomy/questions/{int(question_id)}/answer', json_body={'answer': answer_text})
    if not out.get('ok'):
        return _facade().format_mobile_response(None, f"回答失败：{out.get('error') or '未知错误'}", success=False, code=out.get('status') or 502)
    data = out.get('data') if isinstance(out.get('data'), dict) else {}
    return _facade().format_mobile_response(data=data)

def _sse_line(payload: dict) -> bytes:
    """构造 SSE event line：data: {json}\\n\\n"""
    return ('data: ' + _facade().json.dumps(payload, ensure_ascii=False) + '\n\n').encode('utf-8')

def _chunk_employee_reply(text: str) -> list[str]:
    """把员工完整回复切成 SSE chunk（按句号/换行，每块 <= 120 字）。"""
    if not text:
        return []
    parts = _facade().re.split('(?<=[。！？!?\\n])', text)
    chunks: list[str] = []
    buf = ''
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) > 120:
            if buf:
                chunks.append(buf)
            if len(p) > 120:
                chunks.append(p)
                buf = ''
            else:
                buf = p
        else:
            buf += p
    if buf:
        chunks.append(buf)
    return chunks or [text]
