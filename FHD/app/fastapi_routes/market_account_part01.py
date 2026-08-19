# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.market_account')

def _market_base_url() -> str:
    return (_facade().os.environ.get('XCAGI_MARKET_BASE_URL') or 'http://127.0.0.1:8765').strip().rstrip('/')

def _auth_header(raw: str) -> str:
    token = (raw or '').strip()
    if token.lower().startswith('authorization:'):
        token = token.split(':', 1)[1].strip()
    if token and (not token.lower().startswith('bearer ')):
        token = f'Bearer {token}'
    return token

def session_id_from_request(request: _facade().Request) -> str:
    cookie_name = _facade().os.environ.get('SESSION_COOKIE_NAME', 'session_id')
    cookies = getattr(request, 'cookies', None)
    headers = getattr(request, 'headers', None)
    cookie_sid = cookies.get(cookie_name) if isinstance(cookies, _facade().Mapping) else ''
    header_sid = headers.get('X-Session-ID') if isinstance(headers, _facade().Mapping) else ''
    return str(cookie_sid or header_sid or '').strip()

def bind_market_auth_to_session(request: _facade().Request, market_result: dict[str, _facade().Any]) -> tuple[str, str]:
    """Write market JWT from ``login_market_with_password`` (or register) onto the current FHD session."""
    token = str(market_result.get('token') or '').strip()
    refresh = str(market_result.get('refresh_token') or '').strip()
    if token:
        _facade().save_session_market_token(_facade().session_id_from_request(request), token, refresh or None)
    return (token, refresh)

def save_session_market_token(session_id: str, token: str, refresh_token: str | None=None) -> None:
    sid = (session_id or '').strip()
    tok = (token or '').strip()
    if not sid or not tok:
        return
    _facade()._MARKET_SESSION_TOKENS[sid] = tok
    rtok = (refresh_token or '').strip()
    if rtok:
        _facade()._MARKET_SESSION_REFRESH_TOKENS[sid] = rtok
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_db
        with get_db() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            if row is not None:
                row.market_access_token = tok
                if rtok:
                    row.market_refresh_token = rtok
                db.commit()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('save_session_market_token: failed to persist market token for session_id=%s', sid)

def clear_session_market_token(session_id: str) -> None:
    sid = (session_id or '').strip()
    if sid:
        _facade()._MARKET_SESSION_TOKENS.pop(sid, None)
        _facade()._MARKET_SESSION_REFRESH_TOKENS.pop(sid, None)
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_db
        with get_db() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            if row is not None:
                if getattr(row, 'market_access_token', None):
                    row.market_access_token = None
                if getattr(row, 'market_refresh_token', None):
                    row.market_refresh_token = None
                db.commit()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('clear_session_market_token: failed to clear persisted token for session_id=%s', sid)

def session_market_token(session_id: str) -> str:
    sid = (session_id or '').strip()
    if not sid:
        return ''
    mem = _facade()._MARKET_SESSION_TOKENS.get(sid, '').strip()
    if mem:
        return mem
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_db
        with get_db() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            raw = getattr(row, 'market_access_token', None) if row is not None else None
            t = (raw or '').strip() if raw is not None else ''
            if t:
                _facade()._MARKET_SESSION_TOKENS[sid] = t
                return t
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('session_market_token: DB read failed for session_id=%s', sid)
    return ''

def session_market_refresh_token(session_id: str) -> str:
    sid = (session_id or '').strip()
    if not sid:
        return ''
    mem = _facade()._MARKET_SESSION_REFRESH_TOKENS.get(sid, '').strip()
    if mem:
        return mem
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_db
        with get_db() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            raw = getattr(row, 'market_refresh_token', None) if row is not None else None
            t = (raw or '').strip() if raw is not None else ''
            if t:
                _facade()._MARKET_SESSION_REFRESH_TOKENS[sid] = t
                return t
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('session_market_refresh_token: DB read failed for session_id=%s', sid)
    return ''

def latest_session_market_refresh_token() -> str:
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_db
        with get_db() as db:
            rows = db.query(UserSession).filter(UserSession.market_refresh_token.isnot(None)).order_by(UserSession.created_at.desc()).limit(10).all()
            for row in rows:
                tok = str(getattr(row, 'market_refresh_token', '') or '').strip()
                if tok:
                    return tok
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('latest_session_market_refresh_token: DB read failed')
    return ''

def latest_session_market_token(user_id: int | None=None) -> str:
    """Desktop fallback: use the newest persisted market token when browser cookies are unavailable.

    LAN/IP access can miss the ``session_id`` cookie even though the local single-user desktop
    session has a freshly persisted market token from login. Prefer that over stale localStorage
    tokens sent by the SPA.

    多用户环境必须传 ``user_id`` 以避免串号：若不传则返回全局最新 token（仅适用于
    单用户桌面模式）。云后端/多用户场景下，调用方应传入当前登录用户的 ``user_id``，
    本函数将只返回该用户绑定的市场 token，防止 A 用户拿到 B 用户的市场凭证。
    """
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_db
        with get_db() as db:
            query = db.query(UserSession).filter(UserSession.market_access_token.isnot(None))
            if user_id is not None:
                query = query.filter(UserSession.user_id == user_id)
            rows = query.order_by(UserSession.created_at.desc()).limit(10).all()
            for row in rows:
                tok = str(getattr(row, 'market_access_token', '') or '').strip()
                if tok:
                    return tok
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('latest_session_market_token: DB read failed')
    return ''

def _user_id_from_session(session_id: str) -> int | None:
    """从 session_id 反查 user_id，用于多用户环境下的 market token fallback 隔离。

    返回 None 表示查不到（如 session 不存在或 DB 不可用），调用方应保持原 fallback 行为。
    """
    sid = (session_id or '').strip()
    if not sid:
        return None
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_db
        with get_db() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            return getattr(row, 'user_id', None) if row is not None else None
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('_user_id_from_session: DB read failed for sid=%s', sid[:8])
        return None

def _normalize_bearer_token(raw: str) -> str:
    """Strip ``Bearer `` prefix for consistent ``market_access_token`` JSON fields."""
    t = (raw or '').strip()
    if t.lower().startswith('bearer '):
        return t[7:].strip()
    return t

def _proxy_error_http_status(payload: _facade().Any) -> int | None:
    """Parse HTTP status from ``_proxy_json(..., return_error_payload=True)`` error dict."""
    if not isinstance(payload, dict) or not payload.get('__proxy_error__'):
        return None
    raw = payload.get('status_code')
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None

@_facade().router.get('/session-handoff')
async def market_session_handoff(request: _facade().Request):
    """Return the Xiuci market JWT bound to the current FHD session.

    Login stores this in-memory via ``save_session_market_token``; the SPA needs it in
    ``localStorage`` to append ``xcagi_mt=`` on cross-origin links (cookies do not carry).
    """
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user
        user = resolve_session_user(request)
        if user is None:
            tok = _facade()._normalize_bearer_token(_facade().latest_session_market_token())
            if tok:
                return {'success': True, 'data': {'market_access_token': tok, 'market_base_url': _facade()._market_base_url()}}
            return _facade().JSONResponse({'success': False, 'message': '当前会话未绑定修茈市场账号。请使用与本软件相同的用户名与密码重新登录，或在设置中粘贴修茈 Authorization 完成同步。'}, status_code=404)
        sid = _facade().session_id_from_request(request)
        tok = await _facade().resolve_valid_market_access_token(sid)
        if not tok:
            tok = _facade()._normalize_bearer_token(_facade().latest_session_market_token(user_id=getattr(user, 'id', None)))
            if tok:
                tok = await _facade().resolve_valid_market_access_token(sid)
        if not tok:
            return _facade().JSONResponse({'success': False, 'message': '当前会话未绑定修茈市场账号。请使用与本软件相同的用户名与密码重新登录，或在设置中粘贴修茈 Authorization 完成同步。'}, status_code=404)
        _ = user
        refresh_out = _facade().session_market_refresh_token(sid) or _facade().latest_session_market_refresh_token()
        data: dict[str, _facade().Any] = {'market_access_token': tok, 'market_base_url': _facade()._market_base_url()}
        if refresh_out:
            data['market_refresh_token'] = refresh_out
        try:
            if sid:
                from app.enterprise.mod_entitlements import sync_entitlements_for_session
                await sync_entitlements_for_session(sid)
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception('enterprise entitlements refresh on session-handoff failed')
        return {'success': True, 'data': data}
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('market_session_handoff failed')
        sid = _facade().session_id_from_request(request)
        fallback_tok = _facade()._normalize_bearer_token(_facade().session_market_token(sid) or _facade().latest_session_market_token())
        if fallback_tok:
            return {'success': True, 'data': {'market_access_token': fallback_tok, 'market_base_url': _facade()._market_base_url()}}
        return _facade().JSONResponse({'success': False, 'message': '修茈市场会话交接暂时不可用，请稍后重试或检查 XCAGI_MARKET_BASE_URL 与市场服务状态。', 'data': {'market_base_url': _facade()._market_base_url()}}, status_code=502)

def _authorization_from_request(request: _facade().Request, body: dict[str, _facade().Any]) -> str:
    """Current desktop session token → newest persisted token → explicit browser token.

    The browser may keep an old market JWT in localStorage while the local backend already has
    a fresh token bound to the current FHD login session. Strong account state should follow the
    backend session, not stale client storage.
    """
    sid = _facade().session_id_from_request(request)
    session_auth = _facade()._auth_header(_facade().session_market_token(sid))
    if session_auth:
        return session_auth
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user
        current_user = resolve_session_user(request)
        user_id = getattr(current_user, 'id', None) if current_user else None
    except _facade().RECOVERABLE_ERRORS:
        user_id = None
    if sid or user_id is not None:
        latest_auth = _facade()._auth_header(_facade().latest_session_market_token(user_id=user_id))
        if latest_auth:
            return latest_auth
    auth = _facade()._auth_header(str(body.get('authorization') or body.get('token') or ''))
    if auth:
        return auth
    hdr = str(request.headers.get('Authorization') or request.headers.get('authorization') or '').strip()
    if hdr:
        return _facade()._auth_header(hdr)
    return ''

async def _authorization_from_request_resolved(request: _facade().Request, body: dict[str, _facade().Any]) -> str:
    """Like ``_authorization_from_request`` but refreshes expired session-bound market JWTs."""
    sid = _facade().session_id_from_request(request)
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user
        current_user = resolve_session_user(request)
        user_id = getattr(current_user, 'id', None) if current_user else None
    except _facade().RECOVERABLE_ERRORS:
        user_id = None
    session_tok = _facade()._normalize_bearer_token(_facade().session_market_token(sid))
    if not session_tok and (sid or user_id is not None):
        session_tok = _facade()._normalize_bearer_token(_facade().latest_session_market_token(user_id=user_id))
    if session_tok:
        resolved = await _facade().resolve_valid_market_access_token(sid)
        if resolved:
            return _facade()._auth_header(resolved)
    return _facade()._authorization_from_request(request, body)

def _body_snippet(payload: _facade().Any, limit: int=240) -> str:
    if isinstance(payload, dict):
        try:
            import json as _json
            text = _json.dumps(payload, ensure_ascii=False)
        except _facade().RECOVERABLE_ERRORS:
            text = str(payload)
    else:
        text = str(payload or '')
    text = text.replace('\n', ' ').strip()
    return text[:limit] + ('…' if len(text) > limit else '')

def _error_message(payload: _facade().Any, status_code: int) -> str:
    base = _facade()._market_base_url()
    if status_code == 429:
        return '市场服务请求过于频繁，请稍后再试'
    if isinstance(payload, dict):
        detail = payload.get('detail') or payload.get('message') or payload.get('error')
        if isinstance(detail, list):
            msg = '; '.join((str(x.get('msg') if isinstance(x, dict) else x) for x in detail))
        elif detail:
            msg = str(detail)
        else:
            msg = ''
        if status_code >= 500:
            hint = f'请检查 XCAGI_MARKET_BASE_URL={base}'
            if msg and (not _facade().re.match('^internal server error$', msg, _facade().re.I)):
                return f'市场服务返回 {status_code}：{msg}。{hint}'
            return f'市场服务返回 {status_code}（服务器内部错误）。{hint}'
        if msg:
            return msg
    if status_code >= 500:
        return f'市场服务返回 {status_code}（服务器内部错误）。请检查 XCAGI_MARKET_BASE_URL={base}'
    return f'HTTP {status_code}'

def _market_http_timeout() -> float:
    try:
        return float(_facade().os.environ.get('XCAGI_MARKET_HTTP_TIMEOUT', '20'))
    except ValueError:
        return 20.0

def _market_http_retries() -> int:
    try:
        return max(1, int(_facade().os.environ.get('XCAGI_MARKET_HTTP_RETRIES', '1')))
    except ValueError:
        return 1

def _account_overview_cache_ttl() -> float:
    try:
        return max(0.0, float(_facade().os.environ.get('XCAGI_MARKET_OVERVIEW_CACHE_TTL', '45')))
    except ValueError:
        return 45.0

def _overview_cache_key(authorization: str) -> str:
    return _facade().sha256(_facade()._auth_header(authorization).encode('utf-8')).hexdigest()

def _transport_error_message(exc: Exception) -> tuple[str, int]:
    import httpx
    label = str(exc).strip() or type(exc).__name__
    base = _facade()._market_base_url()
    if isinstance(exc, httpx.ReadTimeout):
        return (f'连接修茈市场超时（{label}）。请检查网络或增大 XCAGI_MARKET_HTTP_TIMEOUT；当前 XCAGI_MARKET_BASE_URL={base}', 503)
    return (f'无法连接修茈市场服务器：{label}。请确认 XCAGI_MARKET_BASE_URL={base} 可达，且 FHD 后端已启动。', 502)
