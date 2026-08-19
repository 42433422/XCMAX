# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.xcmax_admin')

@_facade().router.post('/ops/duty-runs', response_model=None)
async def ops_duty_runs(request: _facade().Request, body: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    return await _facade()._market_admin_proxy(request, 'POST', '/api/admin/duty-graph/runs', json_body=body)

@_facade().router.get('/ops/duty-runs/{run_id}', response_model=None)
async def ops_duty_run_detail(request: _facade().Request, run_id: int):
    if run_id <= 0:
        return _facade().JSONResponse({'success': False, 'message': 'run_id 无效'}, status_code=400)
    return await _facade()._market_admin_proxy(request, 'GET', f'/api/admin/duty-graph/runs/{run_id}')

@_facade().router.get('/ops/closure-status', response_model=None)
async def ops_closure_status(request: _facade().Request):
    from app.application.ops_closure_status import build_ops_closure_status
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    data = build_ops_closure_status(await _facade()._remote_duty_health(request))
    return {'success': True, 'data': data}

@_facade().router.get('/ops/runtime-inventory', response_model=None)
async def ops_runtime_inventory(request: _facade().Request):
    """Desired×actual 运行时真相清单（拓扑 SSOT + 本机探针），并刷新公开投影。"""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.runtime_inventory import write_runtime_inventory_projection
    try:
        result = write_runtime_inventory_projection(host='127.0.0.1')
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('runtime inventory probe failed: %s', exc)
        return {'success': False, 'error': str(exc)}
    snapshot = result.get('snapshot') or {}
    return {'success': True, 'data': snapshot, 'publication': result.get('publication') or {}}

@_facade().router.post('/ops/staffing/onboard', response_model=None)
async def ops_staffing_onboard(request: _facade().Request, body: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    """将编制缺岗员工登记到 MODstore Catalog（代理 yuangon-onboard/run）。"""
    payload: dict[str, _facade().Any] = {'dry_run': bool(body.get('dry_run', False)), 'force': bool(body.get('force', False))}
    pkg_ids = body.get('employee_ids') or body.get('pkg_ids')
    if isinstance(pkg_ids, list):
        payload['pkg_ids'] = ','.join((str(x).strip() for x in pkg_ids if str(x).strip()))
    elif isinstance(pkg_ids, str) and pkg_ids.strip():
        payload['pkg_ids'] = pkg_ids.strip()
    return await _facade()._market_admin_proxy(request, 'POST', '/api/admin/yuangon-onboard/run', json_body=payload)

@_facade().router.post('/ops/staffing/install-local', response_model=None)
async def ops_staffing_install_local(request: _facade().Request, body: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    """从 MODstore Catalog 安装 employee_pack 到本地 mods/_employees/。"""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    pkg_id = str(body.get('employee_id') or body.get('pkg_id') or '').strip()
    if not pkg_id:
        return _facade().JSONResponse({'success': False, 'message': 'employee_id 必填'}, status_code=400)
    try:
        from app.fastapi_routes.mod_store_routes import _install_from_catalog
        result = await _install_from_catalog(pkg_id, '', activate=True)
        if hasattr(result, 'model_dump'):
            data = result.model_dump()
        elif isinstance(result, dict):
            data = result
        else:
            data = {'result': str(result)}
        return {'success': bool(data.get('success', True)), 'data': data}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('ops_staffing_install_local failed: %s', exc)
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)

@_facade().router.post('/ops/staffing/close-gap', response_model=None)
async def ops_staffing_close_gap(request: _facade().Request, body: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    """补登记编制缺岗并安装本地缺失 employee_pack（桌面一键闭环）。"""
    from app.application.ops_closure_status import build_ops_closure_status
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    before = build_ops_closure_status(await _facade()._remote_duty_health(request))
    onboard_result: dict[str, _facade().Any] | None = None
    missing_remote = list(before.get('missing_remote_employees') or [])
    if missing_remote and (not bool(body.get('skip_onboard', False))):
        onboard_result = await _facade()._market_admin_proxy(request, 'POST', '/api/admin/yuangon-onboard/run', json_body={'pkg_ids': ','.join(missing_remote)})
        if isinstance(onboard_result, _facade().JSONResponse):
            return onboard_result
    mid = build_ops_closure_status(await _facade()._remote_duty_health(request))
    install_results: list[dict[str, _facade().Any]] = []
    if not bool(body.get('skip_install', False)):
        from app.fastapi_routes.mod_store_routes import _install_from_catalog
        for employee_id in list(mid.get('missing_local_employee_packs') or []):
            try:
                result = await _install_from_catalog(employee_id, '', activate=True)
                if hasattr(result, 'model_dump'):
                    data = result.model_dump()
                elif isinstance(result, dict):
                    data = result
                else:
                    data = {'result': str(result)}
                install_results.append({'employee_id': employee_id, 'success': bool(data.get('success', True)), 'message': str(data.get('message') or '')})
            except _facade().RECOVERABLE_ERRORS as exc:
                install_results.append({'employee_id': employee_id, 'success': False, 'message': str(exc)})
    after = build_ops_closure_status(await _facade()._remote_duty_health(request))
    onboard_ok = True
    if isinstance(onboard_result, dict):
        onboard_ok = bool(onboard_result.get('success', True))
    return {'success': True, 'data': {'before': before, 'after': after, 'onboard': onboard_result, 'onboard_ok': onboard_ok, 'install_results': install_results}}

@_facade().router.get('/sync/status', response_model=None)
async def sync_status():
    """获取双向同步健康状态。"""
    try:
        from app.db.xcmax_sync import SyncDb
        db = SyncDb()
        info = db.get_status()
        return {'success': True, 'data': info}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug('sync_status db read failed: %s', exc)
        return {'success': True, 'data': {'healthy': False, 'local_cursor': None, 'remote_cursor': None, 'outbox_count': 0, 'last_sync_at': None, 'conflict_count': 0, 'note': '同步数据库尚未初始化，请先完成 sync-foundation 阶段。'}}

@_facade().router.post('/sync/push', response_model=None)
async def sync_push():
    """触发本地 outbox 向服务器推送。"""
    try:
        from app.application.xcmax_sync_app import push_outbox
        result = push_outbox(remote_host=_facade().REMOTE_HOST, remote_port=_facade().REMOTE_PORT)
        return {'success': True, 'data': result}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('sync_push failed: %s', exc)
        return _facade().JSONResponse({'success': False, 'message': f'推送失败: {exc}'}, status_code=500)

@_facade().router.get('/sync/changes', response_model=None)
async def sync_changes(since_cursor: int=_facade().Query(0, ge=0), limit: int=_facade().Query(100, ge=1, le=1000)):
    """获取变更日志（支持断线补拉）。"""
    try:
        from app.db.xcmax_sync import SyncDb
        db = SyncDb()
        rows = db.get_changes(since_cursor=since_cursor, limit=limit)
        return {'success': True, 'data': rows, 'count': len(rows)}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug('sync_changes read failed: %s', exc)
        return {'success': True, 'data': [], 'count': 0, 'note': str(exc)}

@_facade().router.post('/sync/receive', response_model=None)
async def sync_receive(body: dict | list):
    """接收远端推来的变更，写入 inbox，立即尝试应用，并记录审计日志。"""
    try:
        from app.db.xcmax_sync import SyncDb
        db = SyncDb()
        items = body if isinstance(body, list) else [body]
        written = db.enqueue_inbox(items)
        try:
            from app.application.xcmax_sync_app import apply_inbox
            result = apply_inbox(limit=len(items) + 50)
        except _facade().RECOVERABLE_ERRORS as ae:
            result = {'applied': 0, 'error': str(ae)}
        try:
            from app.mod_sdk.audit import write_audit_event
            write_audit_event(actor=None, action='xcmax.sync.receive', payload={'received': written, 'apply': result})
        except _facade().RECOVERABLE_ERRORS:
            pass
        return {'success': True, 'received': written, 'apply_result': result}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('sync_receive failed: %s', exc)
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)

@_facade().router.post('/sync/pull', response_model=None)
async def sync_pull():
    """主动从远端拉取增量变更并应用到本地。"""
    try:
        from app.application.xcmax_sync_app import apply_inbox, pull_from_remote
        pull_result = pull_from_remote(remote_host=_facade().REMOTE_HOST, remote_port=_facade().REMOTE_PORT)
        apply_result = apply_inbox()
        return {'success': True, 'data': {'pull': pull_result, 'apply': apply_result}}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('sync_pull failed: %s', exc)
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)

@_facade().router.get('/sync/entitlements/current', response_model=None)
async def sync_current_entitlements(request: _facade().Request):
    """读取当前登录账号最近一次收到的账号权益强推快照。

    企业端侧边栏用它判断管理端是否已经向本机账号推送了新权益。该接口只读，不进入
    管理员代管态，也不改变当前登录身份。
    """
    try:
        from app.application.session_account_meta import load_session_account_meta
        from app.application.xcmax_sync_app import read_sync_meta
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
        sid = _session_id_from_request(request)
        meta = load_session_account_meta(sid) if sid else None
        if not meta:
            return {'success': True, 'data': {'has_snapshot': False, 'account': None, 'snapshot': None, 'updated_at_ms': 0, 'note': 'no active session'}}
        market_user_id = meta.get('impersonating_market_user_id') or meta.get('market_user_id')
        username_candidates = [str(meta.get('impersonating_username') or '').strip(), str(meta.get('company_brand') or '').strip()]
        try:
            from app.infrastructure.auth.dependencies import resolve_session_user
            user = resolve_session_user(request)
            if user is not None:
                username_candidates.append(str(getattr(user, 'username', '') or '').strip())
                username_candidates.append(str(getattr(user, 'display_name', '') or '').strip())
        except _facade().RECOVERABLE_ERRORS:
            pass
        snapshots: list[dict[str, _facade().Any]] = []
        if market_user_id not in (None, ''):
            snap = read_sync_meta(f'account_entitlements:{market_user_id}')
            if snap:
                snapshots.append(snap)
        for username in username_candidates:
            if not username:
                continue
            snap = read_sync_meta(f'account_entitlements:username:{username}')
            if snap:
                snapshots.append(snap)

        def _snap_updated_at_ms(snapshot: dict[str, _facade().Any]) -> int:
            meta_obj = snapshot.get('meta') if isinstance(snapshot.get('meta'), dict) else {}
            try:
                if not isinstance(meta_obj, dict):
                    meta_obj = {}
                return int(meta_obj.get('updated_at_ms') or 0)
            except (TypeError, ValueError):
                return 0
        snapshot = max(snapshots, key=_snap_updated_at_ms) if snapshots else None
        updated_at_ms = _snap_updated_at_ms(snapshot or {})
        return {'success': True, 'data': {'has_snapshot': bool(snapshot), 'account': {'market_user_id': market_user_id, 'username': next((u for u in username_candidates if u), ''), 'account_kind': meta.get('account_kind'), 'market_is_enterprise': bool(meta.get('market_is_enterprise')), 'market_is_admin': bool(meta.get('market_is_admin'))}, 'snapshot': snapshot, 'updated_at_ms': updated_at_ms}}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('sync_current_entitlements failed: %s', exc)
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)

async def _sync_sse_generator(request: _facade().Request, since_cursor: int):
    """持续产生 SSE 事件：每隔 SYNC_POLL_INTERVAL_S 秒检查一次本地变更日志。"""
    import json as _json
    cursor = since_cursor
    connected = _json.dumps({'type': 'connected', 'cursor': since_cursor}, ensure_ascii=False)
    yield f'data: {connected}\n\n'
    while True:
        if await request.is_disconnected():
            break
        try:
            from app.db.xcmax_sync import SyncDb
            db = SyncDb()
            rows = db.get_changes(since_cursor=cursor, limit=50)
            if rows:
                cursor = rows[-1]['id']
                data = _json.dumps({'cursor': cursor, 'changes': rows}, ensure_ascii=False, default=str)
                yield f'data: {data}\n\n'
            else:
                status = db.get_status()
                heartbeat = _json.dumps({'type': 'heartbeat', 'cursor': cursor, 'status': status}, ensure_ascii=False, default=str)
                yield f'data: {heartbeat}\n\n'
        except _facade().RECOVERABLE_ERRORS as exc:
            err = _json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)
            yield f'data: {err}\n\n'
        await _facade().asyncio.sleep(_facade().SYNC_POLL_INTERVAL_S)

@_facade().router.get('/sync/conflicts', response_model=None)
async def list_conflicts(limit: int=_facade().Query(50, ge=1, le=500)):
    """列出 inbox 中待处理的冲突条目。"""
    try:
        from app.application.admin_sync_app_service import list_admin_sync_conflicts
        data = list_admin_sync_conflicts(limit=limit)
        return {'success': True, 'data': data, 'count': len(data)}
    except _facade().RECOVERABLE_ERRORS as exc:
        return {'success': True, 'data': [], 'count': 0, 'note': str(exc)}

@_facade().router.post('/sync/conflicts/{inbox_id}/resolve', response_model=None)
async def resolve_conflict(inbox_id: int, body: dict):
    """手动解决指定冲突（action: 'apply' | 'skip'）。"""
    action = str(body.get('action') or 'skip').strip()
    try:
        from app.db.xcmax_sync import SyncDb
        db = SyncDb()
        if action == 'apply':
            from app.application.admin_sync_app_service import fetch_admin_inbox_row
            from app.application.xcmax_sync_app import entity_appliers
            row = fetch_admin_inbox_row(inbox_id)
            if row:
                applier = entity_appliers().get(row['entity_type'])
                if applier:
                    applier(row)
            db.mark_inbox_applied(inbox_id)
        else:
            from app.application.admin_sync_app_service import mark_admin_inbox_skipped
            mark_admin_inbox_skipped(inbox_id)
        return {'success': True, 'inbox_id': inbox_id, 'action': action}
    except _facade().RECOVERABLE_ERRORS as exc:
        return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=500)

@_facade().router.get('/sync/stream', response_model=None)
async def sync_stream(request: _facade().Request, since_cursor: int=_facade().Query(0, ge=0)):
    """专用 SSE 同步流：服务端实时推送本地变更（与 AI chat streaming 完全分离）。

    客户端监听示例：
        const es = new EventSource('/api/xcmax/sync/stream?since_cursor=0')
        es.onmessage = e => { const d = JSON.parse(e.data); console.log(d) }
    """
    return _facade().StreamingResponse(_facade()._sync_sse_generator(request, since_cursor), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no'})

async def _xcmax_market_proxy_impl(request: _facade().Request, subpath: str):
    """编制图 LLM / 员工执行等：经会话市场 token 转发至 MODstore ``/api/...``。"""
    method = request.method.upper()
    json_body: dict[str, _facade().Any] | None = None
    if method in {'POST', 'PUT', 'PATCH'}:
        try:
            body = await request.json()
            json_body = body if isinstance(body, dict) else None
        except _facade().RECOVERABLE_ERRORS:
            json_body = None
    api_path = f"/api/{str(subpath or '').lstrip('/')}"
    if api_path.startswith('/api/ops/self-maintenance/'):
        return await _facade()._self_maintenance_local_or_proxy(request, method, api_path, json_body=json_body)
    return await _facade()._market_admin_proxy(request, method, api_path, json_body=json_body)

def _register_market_proxy_method(method: str) -> None:

    async def endpoint(request: _facade().Request, subpath: str):
        return await _facade()._xcmax_market_proxy_impl(request, subpath)
    endpoint.__name__ = f'xcmax_market_proxy_{method.lower()}'
    endpoint.__qualname__ = endpoint.__name__
    _facade().router.add_api_route('/market-proxy/{subpath:path}', endpoint, methods=[method], response_model=None)

def _to_int(value: _facade().Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

def _to_float(value: _facade().Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

def _collect_local_ledger() -> dict[str, _facade().Any]:
    """FHD 本地 token 账本（model_usage_ledger.json）。"""
    try:
        from app.infrastructure.billing.model_usage import list_model_usage_entries
        entries = list_model_usage_entries(limit=500)
    except _facade().RECOVERABLE_ERRORS as exc:
        return {'available': False, 'reason': f'读取账本失败: {exc}'}
    prompt = sum((_facade()._to_int(e.get('prompt_tokens')) for e in entries))
    completion = sum((_facade()._to_int(e.get('completion_tokens')) for e in entries))
    total = sum((_facade()._to_int(e.get('total_tokens')) for e in entries))
    cost = sum((_facade()._to_float(e.get('cost_units')) for e in entries))
    by_model: dict[str, dict[str, _facade().Any]] = {}
    for e in entries:
        key = f"{e.get('provider', '?')}/{e.get('model', '?')}"
        slot = by_model.setdefault(key, {'total': 0, 'count': 0, 'cost': 0.0})
        slot['total'] += _facade()._to_int(e.get('total_tokens'))
        slot['count'] += 1
        slot['cost'] += _facade()._to_float(e.get('cost_units'))
    return {'available': True, 'source': 'FHD 本地账本', 'records': len(entries), 'prompt_tokens': prompt, 'completion_tokens': completion, 'total_tokens': total, 'cost_units': cost, 'by_model': dict(sorted(by_model.items(), key=lambda x: -x[1]['total']))}

def _collect_cursor_usage() -> dict[str, _facade().Any]:
    """Cursor 用量（cursor-usage CLI）。"""
    import shutil
    import subprocess
    cli = shutil.which('cursor-usage') or str(_facade().os.path.expanduser('~/Library/Python/3.9/bin/cursor-usage'))
    if not _facade().os.path.exists(cli):
        return {'available': False, 'reason': f'cursor-usage CLI 不存在: {cli}'}
    try:
        proc = subprocess.run([cli, '--json', '--days', '30'], capture_output=True, text=True, timeout=30)
    except _facade().RECOVERABLE_ERRORS as exc:
        return {'available': False, 'reason': f'执行失败: {exc}'}
    if proc.returncode != 0:
        return {'available': False, 'reason': f'exit={proc.returncode}'}
    try:
        raw = _facade().json.loads(proc.stdout)
    except _facade().RECOVERABLE_ERRORS as exc:
        return {'available': False, 'reason': f'JSON 解析失败: {exc}'}
    aggs = raw.get('aggregations', []) if isinstance(raw, dict) else []
    total_input = sum((_facade()._to_int(a.get('inputTokens')) for a in aggs))
    total_output = sum((_facade()._to_int(a.get('outputTokens')) for a in aggs))
    total_cache_read = sum((_facade()._to_int(a.get('cacheReadTokens')) for a in aggs))
    total_cache_write = sum((_facade()._to_int(a.get('cacheWriteTokens')) for a in aggs))
    total_cents = sum((_facade()._to_float(a.get('totalCents')) for a in aggs))
    by_model: dict[str, dict[str, _facade().Any]] = {}
    for a in aggs:
        m = a.get('modelIntent', 'unknown')
        slot = by_model.setdefault(m, {'input': 0, 'output': 0, 'cache_read': 0, 'cache_write': 0, 'cents': 0.0})
        slot['input'] += _facade()._to_int(a.get('inputTokens'))
        slot['output'] += _facade()._to_int(a.get('outputTokens'))
        slot['cache_read'] += _facade()._to_int(a.get('cacheReadTokens'))
        slot['cache_write'] += _facade()._to_int(a.get('cacheWriteTokens'))
        slot['cents'] += _facade()._to_float(a.get('totalCents'))
    return {'available': True, 'source': 'Cursor (cursor-usage CLI, 最近 30 天)', 'aggregations': len(aggs), 'prompt_tokens': total_input, 'completion_tokens': total_output, 'cache_read_tokens': total_cache_read, 'cache_write_tokens': total_cache_write, 'total_tokens': total_input + total_output + total_cache_read + total_cache_write, 'cost_cents': total_cents, 'by_model': dict(sorted(by_model.items(), key=lambda x: -(x[1]['input'] + x[1]['output'] + x[1]['cache_read'])))}
