# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.xcmax_admin')

@_facade().router.get('/admin/autonomy/audit-log', response_model=None)
async def autonomy_audit_log(request: _facade().Request, limit: int=_facade().Query(default=100, ge=1, le=1000), risk_level: str | None=None, decision: str | None=None, veto_only: bool=False, since: str | None=None, days: int=_facade().Query(default=1, ge=1, le=3650)):
    """Query the append-only autonomy decision and veto trail."""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.audit_log import list_autonomy_audit, summarize_autonomy_audit
    from app.domain.autonomy.operating_metrics import evaluate_autonomy_window
    items = list_autonomy_audit(limit=limit, risk_level=risk_level, decision=decision, veto_only=veto_only, since=since)
    summary = summarize_autonomy_audit(days=days)
    return {'success': True, 'append_only': True, 'items': items, 'count': len(items), 'summary': summary, 'evaluation': evaluate_autonomy_window(days, summary=summary) if days in {30, 90} else None}

@_facade().router.get('/admin/autonomy/actions/pending', response_model=None)
async def admin_pending_autonomy_actions(request: _facade().Request):
    """管理端审批中心：用管理员会话拉取待办（勿走 webhook token）。"""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.approval_resume import list_pending_actions
    items = list_pending_actions()
    return {'ok': True, 'count': len(items), 'items': items}

@_facade().router.post('/admin/autonomy/actions/{action_id}/resume', response_model=None)
async def admin_resume_autonomy_action(action_id: str, request: _facade().Request):
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.approval_resume import ApprovalStateError, admin_execution_contract, get_action_state, resume_action
    try:
        body = await request.json()
    except _facade().RECOVERABLE_ERRORS:
        body = {}
    if not isinstance(body, dict):
        body = {}
    approver = _facade()._admin_approver_from_session(request)
    current = get_action_state(action_id)
    if current is None:
        return _facade().JSONResponse({'ok': False, 'code': 'action_not_found', 'message': '待审批动作不存在'}, status_code=409)
    contract = admin_execution_contract(current)
    if not contract['admin_execution_ready']:
        return _facade().JSONResponse({'ok': False, 'code': str(contract['execution_mode']), 'message': str(contract['execution_guidance']), 'action': {**current, **contract}}, status_code=409)
    try:
        item = resume_action(action_id, approver=approver, approval_id=str(body.get('approval_id') or ''), defer_execution=False)
    except ApprovalStateError as exc:
        return _facade().JSONResponse({'ok': False, 'message': str(exc)}, status_code=409)
    if str(item.get('state') or '') != 'executed':
        return _facade().JSONResponse({'ok': False, 'code': 'execution_failed', 'message': '审批已记录，但动作执行失败；请查看执行结果后修复。', 'action': item}, status_code=502)
    return {'ok': True, 'execution_dispatched': True, 'action': item}

@_facade().router.post('/admin/autonomy/actions/{action_id}/reject', response_model=None)
async def admin_reject_autonomy_action(action_id: str, request: _facade().Request):
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.approval_resume import ApprovalStateError, reject_action
    try:
        body = await request.json()
    except _facade().RECOVERABLE_ERRORS:
        body = {}
    if not isinstance(body, dict):
        body = {}
    approver = _facade()._admin_approver_from_session(request)
    if not approver:
        return _facade().JSONResponse({'ok': False, 'message': 'approver is required'}, status_code=400)
    try:
        item = reject_action(action_id, approver=approver, reason=str(body.get('reason') or ''), approval_id=str(body.get('approval_id') or ''))
    except ApprovalStateError as exc:
        return _facade().JSONResponse({'ok': False, 'message': str(exc)}, status_code=409)
    return {'ok': True, 'action': item}

@_facade().router.get('/admin/autonomy/health', response_model=None)
async def admin_autonomy_health(request: _facade().Request):
    """Admin-session health for autonomy approval service (avoids /api/ops vite→modstore proxy)."""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    return {'ok': True, 'service': 'ops-autonomy-approval', 'via': 'xcmax-admin'}

@_facade().router.get('/admin/autonomy/overview', response_model=None)
async def admin_autonomy_overview(request: _facade().Request):
    """One-shot autonomy dashboard payload for the admin console."""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application import self_maintenance_app_service as sm_svc
    from app.application.autonomy.admin_overview import closure_gap_count, extract_loop_run_summary, list_deploy_events, operating_metrics_windows
    from app.application.autonomy.approval_resume import list_pending_actions
    from app.application.autonomy.audit_log import list_autonomy_audit, summarize_autonomy_audit
    from app.application.ops_closure_status import build_ops_closure_status
    audit_items = list_autonomy_audit(limit=20)
    audit_summary = summarize_autonomy_audit(days=30)
    metrics = operating_metrics_windows()
    deploy = list_deploy_events(limit=20)
    pending = list_pending_actions()
    runtime: dict[str, _facade().Any] = {}
    try:
        runtime = await sm_svc.get_runtime_status_local(limit=40)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('autonomy overview runtime status failed: %s', exc)
        runtime = {'ok': False, 'error': str(exc)}
    closure: dict[str, _facade().Any] = {}
    try:
        closure = {'success': True, 'data': build_ops_closure_status(await _facade()._remote_duty_health(request))}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('autonomy overview closure status failed: %s', exc)
        closure = {'success': False, 'error': str(exc)}
    return {'ok': True, 'health': {'ok': True, 'service': 'ops-autonomy-approval'}, 'pending': {'count': len(pending), 'items': pending[:20]}, 'audit': {'items': audit_items, 'count': len(audit_items), 'summary': audit_summary}, 'loop': extract_loop_run_summary(runtime if isinstance(runtime, dict) else {}), 'runtime': runtime, 'closure': {'gap_count': closure_gap_count(closure), 'payload': closure}, 'deploy_events': deploy, 'operating_metrics': metrics}

@_facade().router.get('/admin/autonomy/deploy-events', response_model=None)
async def admin_autonomy_deploy_events(request: _facade().Request, limit: int=_facade().Query(default=20, ge=1, le=200), since_cursor: str | None=None):
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.admin_overview import list_deploy_events
    data = list_deploy_events(limit=limit, since_cursor=since_cursor)
    return {'ok': True, **data}

@_facade().router.get('/admin/autonomy/operating-metrics', response_model=None)
async def admin_autonomy_operating_metrics(request: _facade().Request):
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.admin_overview import operating_metrics_windows
    return {'ok': True, **operating_metrics_windows()}

@_facade().router.get('/admin/autonomy/github-items', response_model=None)
async def admin_autonomy_github_items(request: _facade().Request, limit: int=_facade().Query(default=30, ge=1, le=100)):
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.admin_overview import list_github_human_items
    return {'ok': True, **list_github_human_items(limit=limit)}

@_facade().router.get('/admin/autonomy/cross-tier-gate', response_model=None)
async def admin_autonomy_cross_tier_gate(request: _facade().Request):
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.admin_overview import evaluate_cross_tier_gate_snapshot
    return {'ok': True, **evaluate_cross_tier_gate_snapshot(None)}

@_facade().router.get('/admin/autonomy/audit-cross-tier', response_model=None)
async def admin_autonomy_audit_cross_tier(request: _facade().Request, tier: str=_facade().Query(default='server'), limit: int=_facade().Query(default=50, ge=1, le=300)):
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.autonomy.admin_overview import read_cross_tier_audit
    return {'ok': True, **read_cross_tier_audit(tier=tier, limit=limit)}

@_facade().router.post('/admin/autonomy/self-maintenance/run', response_model=None)
async def admin_force_self_maintenance_run(request: _facade().Request):
    """Admin break-glass: force one self-maintenance loop via local MODstore."""
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application import self_maintenance_app_service as sm_svc
    try:
        body = await request.json()
    except _facade().RECOVERABLE_ERRORS:
        body = {}
    if not isinstance(body, dict):
        body = {}
    reason = str(body.get('reason') or 'admin_console_force_run').strip() or 'admin_console_force_run'
    try:
        result = await sm_svc.force_run_local(reason=reason)
        return {'ok': True, 'result': result}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('admin force self-maintenance failed: %s', exc)
        return _facade().JSONResponse({'ok': False, 'message': str(exc)}, status_code=502)

def _release_train_snapshot() -> dict[str, _facade().Any]:
    """读取 release_train SSOT；优先 modstore 模块，回退 FHD/config JSON。"""
    from pathlib import Path

    def _default_snapshot(*, note: str | None=None) -> dict[str, _facade().Any]:
        data: dict[str, _facade().Any] = {'epoch': '1.0.0.0', 'current': '1.0.0.1', 'started_at': '2026-06-04', 'day_index': 0}
        if note:
            data['note'] = note
        return data

    def _from_file(path: Path) -> dict[str, _facade().Any]:
        if not path.is_file():
            return _default_snapshot(note='ssot missing')
        try:
            raw = _facade().json.loads(path.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                return raw
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning('release-train json read failed: %s', exc)
        return _default_snapshot()
    mono = (_facade().os.environ.get('XCMAX_MONOREPO_ROOT') or '').strip()
    if mono:
        path = Path(mono).expanduser().resolve() / 'FHD' / 'config' / 'release_train.json'
        return _from_file(path)
    try:
        from modstore_server.release_train import snapshot_public
        return _facade().cast('dict[str, Any]', snapshot_public())
    except _facade().RECOVERABLE_ERRORS:
        pass
    path = Path(__file__).resolve().parents[2] / 'config' / 'release_train.json'
    return _from_file(path)

async def _market_admin_proxy(request: _facade().Request, method: str, path: str, *, json_body: dict[str, _facade().Any] | None=None, require_admin_session: bool=True, authorization_override: str=''):
    """Proxy server-function calls through the market token bound to the local session."""
    if require_admin_session:
        gate = _facade()._require_market_admin_session(request)
        if gate is not None:
            return gate
    if path in {'/api/admin/yuangon-onboard/status', '/api/admin/yuangon-onboard/run'}:
        from app.application.modstore_local_client import prefer_local_modstore
        if prefer_local_modstore():
            from app.application import self_maintenance_app_service as sm_svc
            try:
                if method.upper() == 'GET':
                    return await sm_svc.get_yuangon_onboard_status_local()
                if method.upper() == 'POST':
                    return await sm_svc.run_yuangon_onboard_local(json_body or {})
            except _facade().RECOVERABLE_ERRORS as exc:
                _facade().logger.warning('local yuangon onboarding failed path=%s: %s', path, exc)
                return _facade().JSONResponse({'success': False, 'message': f'本地元工登记服务不可用: {exc}'}, status_code=502)
    try:
        from app.fastapi_routes.market_account import _auth_header, _authorization_from_request_resolved, _error_message, _proxy_json
    except _facade().RECOVERABLE_ERRORS as exc:
        return _facade().JSONResponse({'success': False, 'message': f'市场账号代理不可用: {exc}'}, status_code=500)
    body_for_auth = json_body if isinstance(json_body, dict) else {}
    authorization = _auth_header(authorization_override)
    if not authorization:
        authorization = await _authorization_from_request_resolved(request, body_for_auth)
    if not authorization:
        return _facade().JSONResponse({'success': False, 'message': '尚未绑定修茈服务器账号；请重新登录或在设置中同步市场 Authorization'}, status_code=401)
    payload = await _proxy_json(method, path, json_body=json_body, authorization=authorization, return_error_payload=True)
    if isinstance(payload, _facade().JSONResponse):
        return payload
    if isinstance(payload, dict) and payload.get('__proxy_error__'):
        status_code = int(payload.get('status_code') or 502)
        raw_error = payload.get('payload')
        return _facade().JSONResponse({'success': False, 'message': _error_message(raw_error, status_code), 'data': raw_error}, status_code=status_code)
    return payload

def _is_daily_digest_list_path(path: str) -> bool:
    bare = path.split('?', 1)[0]
    return bare in {'/api/xcmax/admin/daily-digests', '/api/agent/butler/daily-digests'}

def _is_daily_digest_detail_path(path: str) -> bool:
    bare = path.split('?', 1)[0]
    if bare.endswith('/artifacts'):
        return False
    return bare.startswith('/api/xcmax/admin/daily-digests/') or bare.startswith('/api/agent/butler/daily-digests/')

def _is_daily_digest_artifacts_path(path: str) -> bool:
    bare = path.split('?', 1)[0]
    return bare.endswith('/artifacts') and (bare.startswith('/api/xcmax/admin/daily-digests/') or bare.startswith('/api/agent/butler/daily-digests/'))

def _digest_record_id_from_path(path: str) -> int:
    bare = path.split('?', 1)[0]
    if bare.endswith('/artifacts'):
        bare = bare[:-len('/artifacts')]
    return int(bare.rstrip('/').rsplit('/', 1)[-1])

async def _fetch_remote_xcmax_daily_digests(path: str) -> dict[str, _facade().Any] | None:
    """直连修茈 ``/api/xcmax/admin/daily-digests``（生产落库副本；不依赖 butler 会话）。"""
    import httpx
    from app.application.modstore_local_client import internal_auth_headers
    base = (_facade().os.environ.get('XCAGI_MARKET_BASE_URL') or 'https://xiu-ci.com').strip().rstrip('/')
    if base.endswith('/market'):
        base = base[:-len('/market')]
    (bare, _, query) = path.partition('?')
    if bare.startswith('/api/agent/butler/daily-digests'):
        bare = bare.replace('/api/agent/butler/daily-digests', '/api/xcmax/admin/daily-digests', 1)
    elif not bare.startswith('/api/xcmax/admin/daily-digests'):
        return None
    url = f'{base}{bare}'
    if query:
        url = f'{url}?{query}'
    headers = {'Accept': 'application/json', **internal_auth_headers()}
    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code >= 400:
                _facade().logger.warning('remote xcmax daily-digests HTTP %s path=%s', resp.status_code, bare)
                return None
            data = resp.json()
            return data if isinstance(data, dict) else {'success': True, 'data': data}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('remote xcmax daily-digests failed path=%s: %s', bare, exc)
        return None

def _digest_payload_nonempty(payload: _facade().Any) -> bool:
    if not isinstance(payload, dict):
        return False
    data = payload.get('data')
    if isinstance(data, list):
        return len(data) > 0
    if isinstance(data, dict):
        return bool(data.get('id') or data.get('body_html') or data.get('subject'))
    return False

async def _digest_local_or_proxy(request: _facade().Request, method: str, path: str, *, json_body: dict[str, _facade().Any] | None=None):
    """日更读接口：本地 MODstore → 市场代理 → 直连生产 xcmax 存档（三选一回退）。"""
    from app.application.modstore_local_client import prefer_local_modstore
    if prefer_local_modstore() and method.upper() == 'GET':
        from app.application import digest_email_app_service as digest_svc
        local_payload: dict[str, _facade().Any] | None = None
        try:
            if _facade()._is_daily_digest_list_path(path):
                q = path.split('?', 1)[1] if '?' in path else ''
                (limit, offset) = (20, 0)
                for part in q.split('&'):
                    if part.startswith('limit='):
                        limit = int(part.split('=', 1)[1])
                    elif part.startswith('offset='):
                        offset = int(part.split('=', 1)[1])
                local_payload = await digest_svc.list_daily_digests_local(limit=limit, offset=offset)
                if _facade()._digest_payload_nonempty(local_payload):
                    return local_payload
            elif _facade()._is_daily_digest_artifacts_path(path):
                rid = _facade()._digest_record_id_from_path(path)
                return await digest_svc.get_daily_digest_artifacts_local(int(rid))
            elif _facade()._is_daily_digest_detail_path(path):
                rid = _facade()._digest_record_id_from_path(path)
                local_payload = await digest_svc.get_daily_digest_local(int(rid))
                if _facade()._digest_payload_nonempty(local_payload):
                    return local_payload
            elif path.startswith('/api/admin/action-items/stats?'):
                q = path.split('?', 1)[1] if '?' in path else ''
                kind = day = ''
                for part in q.split('&'):
                    if part.startswith('kind='):
                        kind = part.split('=', 1)[1]
                    elif part.startswith('day='):
                        day = part.split('=', 1)[1]
                return await digest_svc.action_items_stats_local(kind=kind, day=day)
            elif path.startswith('/api/admin/action-items?'):
                q = path.split('?', 1)[1] if '?' in path else ''
                kind = day = ''
                for part in q.split('&'):
                    if part.startswith('kind='):
                        kind = part.split('=', 1)[1]
                    elif part.startswith('day='):
                        day = part.split('=', 1)[1]
                return await digest_svc.list_action_items_local(kind=kind, day=day)
            if _facade()._is_daily_digest_list_path(path) or _facade()._is_daily_digest_detail_path(path):
                remote = await _facade()._fetch_remote_xcmax_daily_digests(path)
                if remote is not None:
                    return remote
                if local_payload is not None:
                    return local_payload
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning('local digest/action-items read failed path=%s: %s', path, exc)
            if _facade()._is_daily_digest_list_path(path) or _facade()._is_daily_digest_detail_path(path):
                remote = await _facade()._fetch_remote_xcmax_daily_digests(path)
                if remote is not None:
                    return remote
            return _facade().JSONResponse({'success': False, 'message': str(exc)}, status_code=502)
    proxied = await _facade()._market_admin_proxy(request, method, path, json_body=json_body, require_admin_session=not prefer_local_modstore())
    if method.upper() == 'GET' and (_facade()._is_daily_digest_list_path(path) or _facade()._is_daily_digest_detail_path(path)):
        if isinstance(proxied, _facade().JSONResponse) or not _facade()._digest_payload_nonempty(proxied):
            remote = await _facade()._fetch_remote_xcmax_daily_digests(path)
            if remote is not None:
                return remote
    return proxied
