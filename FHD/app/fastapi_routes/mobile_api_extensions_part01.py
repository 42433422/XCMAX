# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.mobile_api_extensions')

def _mobile_session_id_from_request(request: _facade().Request) -> str:
    auth_raw = request.headers.get('Authorization') or ''
    auth_hdr = auth_raw if isinstance(auth_raw, str) else ''
    if auth_hdr.startswith('Bearer '):
        try:
            from app.security.mobile_jwt import verify_mobile_jwt
            payload = verify_mobile_jwt(auth_hdr[7:].strip()) or {}
            sid = str(payload.get('session_id') or '').strip()
            if sid:
                return sid
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception('mobile session id parse failed')
    sid_raw = request.headers.get('X-Session-ID') or ''
    return sid_raw.strip() if isinstance(sid_raw, str) else ''

def _mobile_market_authorization(request: _facade().Request, user: _facade().Any | None=None) -> str:
    from app.fastapi_routes.market_account import _auth_header, latest_session_market_token, session_market_token
    sid = _facade()._mobile_session_id_from_request(request)
    token = session_market_token(sid) if sid else ''
    if not token:
        token = latest_session_market_token(user_id=getattr(user, 'id', None))
    return _auth_header(token)

def _mobile_unauthorized_response() -> _facade().JSONResponse:
    return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)

def _ai_circle_user(user: _facade().Any) -> tuple[int, str, str | None]:
    uid = int(getattr(user, 'id', 0) or 0)
    name = str(getattr(user, 'display_name', '') or getattr(user, 'username', '') or '企业成员').strip()
    avatar = getattr(user, 'wx_avatar_url', None)
    return (uid, name, str(avatar).strip() if avatar else None)

def _ai_circle_employee_profiles() -> dict[str, dict[str, str]]:
    profiles: dict[str, dict[str, str]] = {}
    for mod in _facade()._mobile_mod_items():
        mod_avatar = str(mod.get('avatar_url') or '').strip()
        for employee in mod.get('workflow_employees') or []:
            if not isinstance(employee, dict):
                continue
            employee_id = str(employee.get('id') or '').strip()
            if not employee_id:
                continue
            profiles[employee_id] = {'name': str(employee.get('label') or employee.get('panel_title') or employee_id).strip(), 'avatar': str(employee.get('market_avatar') or mod_avatar).strip()}
    return profiles

def _ensure_mobile_device_table() -> None:
    try:
        from sqlalchemy import inspect
        from app.db.models.mobile_device import MobileDeviceToken
        from app.db.session import get_db
        with get_db() as db:
            bind = db.get_bind()
            insp = inspect(bind)
            if not insp.has_table(MobileDeviceToken.__tablename__):
                _facade().cast('Table', MobileDeviceToken.__table__).create(bind, checkfirst=True)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('mobile_device_tokens ensure: %s', exc)

def _ensure_outbox_table() -> None:
    try:
        from sqlalchemy import inspect
        from app.db.models.mobile_notification import MobileNotificationOutbox
        from app.db.session import get_db
        with get_db() as db:
            bind = db.get_bind()
            insp = inspect(bind)
            if not insp.has_table(MobileNotificationOutbox.__tablename__):
                _facade().cast('Table', MobileNotificationOutbox.__table__).create(bind, checkfirst=True)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('mobile_notification_outbox ensure: %s', exc)

def _resolve_mobile_relay_user(user: _facade().Any, *, prefer_admin: bool=False) -> dict[str, _facade().Any]:
    """Resolve the mobile user for physical QR/device-code relay binding.

    A relay pairing code already proves physical access to the desktop settings
    screen, so first-time mobile binding must not require a pre-existing mobile
    JWT. Prefer an existing admin account; create a local relay admin only when
    the database has no active users yet.
    """
    (uid, _) = _facade()._mobile_user_identity(user)
    role = str(getattr(user, 'role', '') or '').strip()
    if uid > 0 and (not prefer_admin or role in {'admin', 'super_admin', 'owner'}):
        return _facade()._mobile_user_public_dict(user)
    from app.db.models import User
    from app.db.session import get_db
    try:
        with get_db() as db:
            row = None
            if prefer_admin or uid <= 0:
                row = db.query(User).filter(User.is_active == True).filter(User.role.in_(['admin', 'super_admin', 'owner'])).order_by(User.id.asc()).first()
            if row is None:
                row = db.query(User).filter(User.is_active == True).order_by(User.id.asc()).first()
            if row is None:
                now = _facade().datetime.utcnow()
                row = User(username=f'mobile_relay_{_facade().uuid.uuid4().hex[:8]}', password=_facade().uuid.uuid4().hex, display_name='移动端设备绑定', email='', role='admin', is_active=True, created_at=now, last_login=now)
                db.add(row)
                db.flush()
            public = _facade()._mobile_user_public_dict(row)
            if hasattr(db, 'expunge'):
                db.expunge(row)
            return public
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('mobile relay admin fallback: %s', exc)
        if prefer_admin:
            return _facade()._relay_admin_fallback_user()
        raise

def _register_desktop_relay_for_pairing(host: str, port: int) -> dict[str, _facade().Any] | None:
    enabled = (_facade().os.environ.get('XCAGI_RELAY_PAIRING_ENABLED') or '1').strip().lower()
    if enabled in {'0', 'false', 'off', 'no'}:
        return None
    if not _facade()._host_is_private_or_loopback(host):
        return None
    try:
        from app.application.facades.mobile_relay_facade import register_desktop_relay
        relay = register_desktop_relay(host=host, port=port)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('desktop relay registration skipped: %s', exc)
        return None
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('desktop relay registration skipped after unexpected failure: %s', exc)
        return None
    if not relay:
        return None
    public_relay = dict(relay)
    public_relay.pop('desktop_token', None)
    return public_relay

def _cached_desktop_relay_for_account_binding() -> dict[str, _facade().Any] | None:
    """Return the local desktop's cloud relay id for account-auth binding."""
    try:
        from app.application.facades.mobile_relay_facade import cached_desktop_relay_payload
        relay = cached_desktop_relay_payload()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('cached desktop relay unavailable: %s', exc)
        return None
    if not relay:
        return None
    if relay.get('paired') is not True:
        return None
    relay_id = str(relay.get('relay_id') or '').strip()
    if not relay_id:
        return None
    return {'relay_id': relay_id, 'relay_base_url': str(relay.get('relay_base_url') or '').strip(), 'expires_at': str(relay.get('expires_at') or '').strip(), 'exp': int(relay.get('exp') or 0), 'binding_mode': 'account_auth'}

def _pairing_issue_host(requested: str) -> str:
    host = str(requested or '').strip() or '127.0.0.1'
    if host in ('127.0.0.1', 'localhost', '0.0.0.0'):
        return _facade()._guess_lan_ipv4()
    return host

def _mobile_bridge_request_statuses() -> tuple[str, ...]:
    return ('pending', 'processing', 'resolved', 'closed')

def _approval_items(limit: int=100) -> list[dict[str, _facade().Any]]:
    from app.db.models.approval import ApprovalRequest
    from app.db.session import get_db
    with get_db() as db:
        rows = db.query(ApprovalRequest).order_by(ApprovalRequest.created_at.desc()).limit(limit).all()
        return [{'id': r.id, 'title': r.title, 'status': r.status, 'request_no': r.request_no} for r in rows]

def _shipment_items(limit: int=100) -> list[dict[str, _facade().Any]]:
    from app.db.models.shipment import ShipmentRecord
    from app.db.session import get_db
    with get_db() as db:
        rows = db.query(ShipmentRecord).order_by(ShipmentRecord.id.desc()).limit(limit).all()
        return [{'id': r.id, 'order_number': getattr(r, 'order_number', None) or getattr(r, 'shipment_no', None), 'status': getattr(r, 'status', None)} for r in rows]

def _safe_mobile_sync_items(name: str, loader) -> list[dict[str, _facade().Any]]:
    try:
        return _facade().cast('list[dict[str, Any]]', loader())
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('mobile sync: %s skipped: %s', name, exc)
        return []

def _ai_conversation_changes(user: _facade().Any, limit: int=100) -> list[dict[str, _facade().Any]]:
    """查询当前用户最近的 AI 对话消息，供移动端增量同步。"""
    uid = int(getattr(user, 'id', 0) or 0)
    if uid <= 0:
        return []
    try:
        from app.db.models.ai import AIConversation, AIConversationSession
        from app.db.session import get_db
        with get_db() as db:
            rows = db.query(AIConversation).join(AIConversationSession, AIConversation.session_id == AIConversationSession.session_id).filter(AIConversationSession.user_id == uid).order_by(AIConversation.id.desc()).limit(limit).all()
            return [{'id': r.id, 'session_id': r.session_id, 'role': r.role, 'content': r.content, 'intent': r.intent or '', 'created_at': r.created_at.isoformat() if r.created_at else ''} for r in reversed(rows)]
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('ai_conversation_changes: %s', exc)
        return []

def _mobile_mod_items(market_profiles: dict[str, dict[str, _facade().Any]] | None=None, *, market_connected: bool=False) -> list[dict[str, _facade().Any]]:
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager
        items: list[dict[str, _facade().Any]] = []
        for m in get_mod_manager().list_all_mods() or []:
            if isinstance(m, dict):
                mid = str(m.get('id') or m.get('mod_id') or '').strip()
                name = str(m.get('name') or m.get('title') or mid).strip()
                raw_employees = m.get('workflow_employees')
                employees: list[_facade().Any] = raw_employees if isinstance(raw_employees, list) else []
                menu = m.get('frontend_menu') or m.get('menu') or m.get('menus')
                menu_overrides = m.get('menu_overrides')
                item: dict[str, _facade().Any] = {'id': mid, 'name': name, 'version': m.get('version') or '', 'author': m.get('author') or '', 'description': m.get('description') or '', 'primary': bool(m.get('primary')), 'industry': m.get('industry') if isinstance(m.get('industry'), dict) else {}, 'avatar_url': m.get('avatar') or m.get('logo') or m.get('icon') or '', 'frontend_menu': menu if isinstance(menu, list) else [], 'menu': menu if isinstance(menu, list) else [], 'menu_overrides': menu_overrides if isinstance(menu_overrides, list) else [], 'workflow_employees': _facade()._enrich_workflow_employees(mid, employees, market_profiles, market_connected=market_connected)}
            else:
                mid = str(getattr(m, 'id', None) or getattr(m, 'mod_id', '') or '').strip()
                name = str(getattr(m, 'name', None) or getattr(m, 'title', None) or mid).strip()
                employees = getattr(m, 'workflow_employees', [])
                if not isinstance(employees, list):
                    employees = []
                menu = getattr(m, 'frontend_menu', [])
                menu_overrides = getattr(m, 'frontend_menu_overrides', [])
                item = {'id': mid, 'name': name, 'version': str(getattr(m, 'version', '') or ''), 'author': str(getattr(m, 'author', '') or ''), 'description': str(getattr(m, 'description', '') or ''), 'primary': bool(getattr(m, 'primary', False)), 'industry': getattr(m, 'industry', {}) if isinstance(getattr(m, 'industry', {}), dict) else {}, 'avatar_url': str(getattr(m, 'avatar', '') or getattr(m, 'logo', '') or getattr(m, 'icon', '') or ''), 'frontend_menu': menu if isinstance(menu, list) else [], 'menu': menu if isinstance(menu, list) else [], 'menu_overrides': menu_overrides if isinstance(menu_overrides, list) else [], 'workflow_employees': _facade()._enrich_workflow_employees(mid, employees, market_profiles, market_connected=market_connected)}
            if mid:
                items.append(item)
        _facade()._upsert_admin_duty_mod_item(items, market_profiles, market_connected=market_connected)
        return items[:100]
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('mobile mods list: %s', exc)
        items = []
        _facade()._upsert_admin_duty_mod_item(items, market_profiles, market_connected=market_connected)
        return items

def _admin_roster_ids_by_department_order() -> list[str]:
    try:
        from app.mod_sdk.employee_ssot import derive_admin_duty_roster
        admin = derive_admin_duty_roster()
    except _facade().RECOVERABLE_ERRORS:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for dept in admin.get('departments') or []:
        if not isinstance(dept, dict):
            continue
        for employee in dept.get('employees') or []:
            if not isinstance(employee, dict):
                continue
            eid = str(employee.get('id') or '').strip()
            if eid and eid not in seen:
                seen.add(eid)
                out.append(eid)
    for eid in admin.get('planned_employee_ids') or []:
        eid = str(eid or '').strip()
        if eid and eid not in seen:
            seen.add(eid)
            out.append(eid)
    return out

def _admin_roster_area_labels() -> dict[str, str]:
    try:
        from app.mod_sdk.duty_roster import load_duty_roster_document
        doc = load_duty_roster_document()
    except _facade().RECOVERABLE_ERRORS:
        return {}
    out: dict[str, str] = {}
    areas = doc.get('areas') if isinstance(doc, dict) else {}
    if not isinstance(areas, dict):
        return out
    for (_area_key, area) in areas.items():
        if not isinstance(area, dict):
            continue
        label = _facade()._compact_text(area.get('label'))
        for eid in area.get('ids') or []:
            sid = str(eid or '').strip()
            if sid and label and (sid not in out):
                out[sid] = label
    return out

def _admin_employee_manifest(employee_id: str) -> dict[str, _facade().Any]:
    eid = str(employee_id or '').strip()
    if not eid:
        return {}
    manifest = _facade().Path(__file__).resolve().parents[2] / 'mods' / '_employees' / eid / 'manifest.json'
    try:
        raw = _facade().json.loads(manifest.read_text(encoding='utf-8'))
        return raw if isinstance(raw, dict) else {}
    except (OSError, _facade().json.JSONDecodeError):
        return {}

def _admin_duty_records_from_roster() -> list[dict[str, _facade().Any]]:
    registry = _facade()._load_admin_duty_records()
    roster_ids = _facade()._admin_roster_ids_by_department_order()
    if not roster_ids:
        return registry
    registry_by_id: dict[str, dict[str, _facade().Any]] = {}
    for raw in registry:
        eid = str(raw.get('id') or raw.get('pkg_id') or '').strip()
        if eid and eid not in registry_by_id:
            registry_by_id[eid] = raw
    registry_ids = set(registry_by_id)
    roster_id_set = set(roster_ids)
    if registry_ids and (not registry_ids & roster_id_set):
        return registry
    area_labels = _facade()._admin_roster_area_labels()
    records: list[dict[str, _facade().Any]] = []
    for eid in roster_ids:
        raw = dict(registry_by_id.get(eid) or {})
        manifest: dict[str, _facade().Any] = dict(_facade()._admin_employee_manifest(eid) or {})
        raw_employee_meta = manifest.get('employee')
        employee_meta: dict[str, _facade().Any] = raw_employee_meta if isinstance(raw_employee_meta, dict) else {}
        raw.setdefault('id', eid)
        raw.setdefault('pkg_id', eid)
        raw.setdefault('name', manifest.get('name') or employee_meta.get('label') or eid)
        raw.setdefault('description', manifest.get('description') or '')
        raw.setdefault('version', manifest.get('version') or '')
        raw.setdefault('yuangon_area', area_labels.get(eid, ''))
        raw.setdefault('employee_scope', 'duty')
        raw.setdefault('employee_source', 'duty_roster')
        raw.setdefault('is_duty_employee', True)
        raw.setdefault('is_store_employee', False)
        records.append(raw)
    return records

def _admin_employee_items(market_profiles: dict[str, dict[str, _facade().Any]] | None=None, *, market_connected: bool=False, im_summary: dict[str, dict[str, _facade().Any]] | None=None) -> list[dict[str, _facade().Any]]:
    items: list[dict[str, _facade().Any]] = []
    for raw in _facade()._admin_duty_records_from_roster():
        employee_id = str(raw.get('id') or raw.get('pkg_id') or '').strip()
        if not employee_id:
            continue
        name = _facade()._compact_text(raw.get('name') or employee_id)
        area = _facade()._compact_text(raw.get('yuangon_area') or raw.get('industry'))
        item = {'id': employee_id, 'name': name, 'label': name, 'title': name, 'panel_title': name, 'description': _facade()._compact_text(raw.get('description')), 'panel_summary': _facade()._compact_text(raw.get('description')), 'version': str(raw.get('version') or '').strip(), 'industry': _facade()._compact_text(raw.get('industry')), 'yuangon_area': area, 'employee_scope': _facade()._compact_text(raw.get('employee_scope') or 'duty'), 'employee_source': _facade()._compact_text(raw.get('employee_source') or 'duty_roster'), 'is_duty_employee': bool(raw.get('is_duty_employee', True)), 'is_store_employee': bool(raw.get('is_store_employee', False)), 'status': 'on_duty', 'api_base_path': f'/api/admin/employees/{employee_id}', 'phone_channel': 'admin-duty', 'workflow_placeholder': False, 'stored_filename': _facade()._compact_text(raw.get('stored_filename')), 'file_size': raw.get('file_size') or 0}
        profile = None
        if market_profiles:
            for key in _facade()._admin_employee_match_keys(raw, employee_id, name):
                profile = market_profiles.get(key)
                if profile:
                    break
        _facade()._apply_market_profile(item, profile, market_connected=market_connected)
        if im_summary:
            summary = im_summary.get(employee_id)
            if summary:
                item.update(summary)
        items.append(item)
    return items

def _admin_duty_mod_item(market_profiles: dict[str, dict[str, _facade().Any]] | None=None, *, market_connected: bool=False) -> dict[str, _facade().Any] | None:
    employees = _facade()._admin_employee_items(market_profiles, market_connected=market_connected)
    if not employees:
        return None
    return {'id': 'admin-duty-employees', 'name': '管理端编制员工', 'version': 'local', 'author': 'XCAGI 管理端', 'description': f'{len(employees)} 位管理端编制 AI 员工，来自 duty_roster.json。', 'primary': True, 'industry': {'id': '管理端', 'name': '管理端'}, 'frontend_menu': [], 'menu': [], 'menu_overrides': [], 'workflow_employees': employees}

def _upsert_admin_duty_mod_item(items: list[dict[str, _facade().Any]], market_profiles: dict[str, dict[str, _facade().Any]] | None=None, *, market_connected: bool=False) -> None:
    duty_mod = _facade()._admin_duty_mod_item(market_profiles, market_connected=market_connected)
    if not duty_mod:
        return
    duty_id = str(duty_mod.get('id') or '')
    for item in items:
        if str(item.get('id') or '') != duty_id:
            continue
        if not item.get('workflow_employees'):
            item['workflow_employees'] = duty_mod['workflow_employees']
        return
    items.insert(0, duty_mod)

def _persist_mobile_cs_request(user: _facade().Any, *, message_id: str, msg_body: str, reply: str, backend: str, employee_result: dict[str, _facade().Any]) -> tuple[int, bool, str]:
    from app.db.models.service_request import ServiceRequest
    from app.db.session import get_db
    username = _facade()._safe_user_text(user, 'username')
    extra = {'message_id': message_id, 'mobile_user_id': _facade()._safe_user_id(user), 'username': username, 'ai_reply': reply, 'backend': backend, 'employee_result': employee_result}
    try:
        with get_db() as db:
            _facade().cast('Table', ServiceRequest.__table__).create(db.get_bind(), checkfirst=True)
            row = ServiceRequest(source_instance_id=_facade()._mobile_cs_source_id(user), source_instance_name=_facade()._mobile_cs_source_name(user), request_type='mobile_ai_customer_service', title=msg_body[:80] or f'{_facade().dedicated_cs_label()}咨询', description=msg_body, priority='normal', status='pending', extra_data=_facade().json.dumps(extra, ensure_ascii=False))
            db.add(row)
            db.flush()
            return (int(row.id), True, '')
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('mobile cs service request persist skipped: %s', exc)
        return (0, False, '服务请求保存失败')

@_facade().extension_router.get('/approval/requests')
async def mobile_approval_list(request: _facade().Request, status: str | None=None, page: int=_facade().Query(1, ge=1), page_size: int=_facade().Query(50, ge=1, le=200), user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    from app.db.models.approval import ApprovalRequest
    from app.db.session import get_db
    with get_db() as db:
        q = db.query(ApprovalRequest)
        if status:
            q = q.filter(ApprovalRequest.status == status)
        total = q.count()
        rows = q.order_by(ApprovalRequest.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        items = [{'id': r.id, 'title': r.title, 'status': r.status, 'request_no': r.request_no, 'applicant_id': r.applicant_id} for r in rows]
    return _facade().format_mobile_response(data=_facade().paginate_list(items, total, page, page_size))
