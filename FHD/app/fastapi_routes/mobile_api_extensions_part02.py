# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.mobile_api_extensions')

@_facade().extension_router.get('/customers')
async def mobile_customers(page: int=_facade().Query(1, ge=1), per_page: int=_facade().Query(20, ge=1, le=100), user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    from app.db.models import Customer
    from app.db.session import get_db
    from app.infrastructure.tenant_scope import apply_tenant_filter
    with get_db() as db:
        q = apply_tenant_filter(db.query(Customer), Customer)
        total = q.count()
        rows = q.offset((page - 1) * per_page).limit(per_page).all()
        items = [{'id': c.id, 'name': c.customer_name, 'phone': c.contact_phone} for c in rows]
    return _facade().format_mobile_response(data=_facade().paginate_list(items, total, page, per_page))

@_facade().extension_router.get('/shipments')
async def mobile_shipments(page: int=_facade().Query(1, ge=1), per_page: int=_facade().Query(20, ge=1, le=100), user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    from app.db.models.shipment import ShipmentRecord
    from app.db.session import get_db
    with get_db() as db:
        q = db.query(ShipmentRecord)
        total = q.count()
        rows = q.order_by(ShipmentRecord.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
        items = [{'id': r.id, 'order_number': getattr(r, 'order_number', None) or getattr(r, 'shipment_no', None), 'status': getattr(r, 'status', None)} for r in rows]
    return _facade().format_mobile_response(data=_facade().paginate_list(items, total, page, per_page))

def _employee_ssot_payload() -> dict[str, _facade().Any]:
    """管理端 6 部门上岗 + 企业端 4 部门上架/未上架，自动派生自 SSOT。"""
    from app.application.ops_closure_status import _installed_employee_pack_ids
    from app.mod_sdk.employee_ssot import derive_employee_ssot
    installed: set[str] = set()
    try:
        installed = _installed_employee_pack_ids()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('mobile employee-ssot: 读取已安装 employee_pack 失败: %s', exc)
    return derive_employee_ssot(installed_ids=installed)

@_facade().extension_router.get('/employee-ssot')
async def mobile_employee_ssot(user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    return _facade().format_mobile_response(data=_facade()._employee_ssot_payload())

@_facade().extension_router.post('/devices/register')
async def mobile_device_register(body: _facade().DeviceRegisterBody, user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    _facade()._ensure_mobile_device_table()
    from app.db.models.mobile_device import MobileDeviceToken
    from app.db.session import get_db
    from app.utils.time import utc_now_naive
    token = (body.push_token or body.fcm_token).strip()
    provider = (body.push_provider or 'fcm').strip().lower()[:16]
    if not token:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '缺少 push_token', success=False, code=400), status_code=400)
    with get_db() as db:
        row = db.query(MobileDeviceToken).filter(MobileDeviceToken.user_id == user.id, MobileDeviceToken.fcm_token == body.fcm_token.strip()).first()
        if row:
            row.device_label = body.device_label[:200]
            row.platform = body.platform[:32]
            row.fcm_token = body.fcm_token.strip()[:512]
            row.push_provider = provider
            row.push_token = token
            row.product_sku = (body.product_sku or 'personal')[:32]
            row.updated_at = utc_now_naive()
        else:
            db.add(MobileDeviceToken(user_id=user.id, fcm_token=body.fcm_token.strip(), push_provider=provider, push_token=token, product_sku=(body.product_sku or 'personal')[:32], platform=body.platform[:32], device_label=body.device_label[:200]))
    return _facade().format_mobile_response(data={'registered': True})

@_facade().extension_router.delete('/devices/unregister')
async def mobile_device_unregister(fcm_token: str=_facade().Query(..., min_length=8), user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    _facade()._ensure_mobile_device_table()
    from app.db.models.mobile_device import MobileDeviceToken
    from app.db.session import get_db
    with get_db() as db:
        db.query(MobileDeviceToken).filter(MobileDeviceToken.user_id == user.id, MobileDeviceToken.fcm_token == fcm_token.strip()).delete()
    return _facade().format_mobile_response(data={'unregistered': True})

@_facade().extension_router.get('/notifications/pending')
async def mobile_notifications_pending(limit: int=_facade().Query(50, ge=1, le=200), user=_facade().Depends(_facade().get_mobile_user)):
    """自建推送后台通道:返回未送达的离线通知并标记 delivered（客户端 WorkManager 轮询）。"""
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    _facade()._ensure_outbox_table()
    import json as _json
    from app.db.models.mobile_notification import MobileNotificationOutbox
    from app.db.session import get_db
    from app.utils.time import utc_now_naive
    items: list[dict] = []
    with get_db() as db:
        rows = db.query(MobileNotificationOutbox).filter(MobileNotificationOutbox.user_id == user.id, MobileNotificationOutbox.delivered.is_(False)).order_by(MobileNotificationOutbox.created_at.asc()).limit(limit).all()
        now = utc_now_naive()
        for r in rows:
            try:
                data = _json.loads(r.data_json or '{}')
            except (ValueError, TypeError):
                data = {}
            items.append({'id': r.id, 'title': r.title, 'body': r.body, 'route': r.route, 'channel': r.channel, 'data': data})
            r.delivered = True
            r.delivered_at = now
    return _facade().format_mobile_response(data={'notifications': items})

@_facade().extension_router.post('/pairing/issue')
async def mobile_pairing_issue(body: _facade().PairingIssueBody, request: _facade().Request):
    """桌面或运维签发配对 QR 载荷（开发/内网）。"""
    host = _facade()._pairing_issue_host(body.host or (request.url.hostname or ''))
    api_port = _facade()._pairing_issue_port(request, int(body.port))
    port = _facade()._pairing_reachable_port(request, api_port)
    payload = _facade().issue_pairing_nonce(host, port)
    data = _facade()._enrich_pairing_payload(payload, request)
    relay = _facade()._register_desktop_relay_for_pairing(host, port)
    if relay:
        data['relay'] = relay
        data['relay_id'] = relay.get('relay_id')
        data['relay_base_url'] = relay.get('relay_base_url')
        data['relay_binding_mode'] = 'account_auth'
    return _facade().format_mobile_response(data=data)

@_facade().extension_router.post('/pairing/lookup')
async def mobile_pairing_lookup(body: _facade().PairingLookupBody):
    code = body.code.strip()
    rec = _facade().lookup_by_shortcode(code)
    if not rec:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '配对码不存在或已过期', success=False, code=404), status_code=404)
    return _facade().format_mobile_response(data=_facade()._enrich_pairing_payload({'host': rec.get('host'), 'port': rec.get('port'), 'nonce': rec.get('nonce'), 'shortCode': code, 'exp': rec.get('exp') or 0}))

@_facade().extension_router.post('/pairing/exchange')
async def mobile_pairing_exchange(body: _facade().PairingExchangeBody, user=_facade().Depends(_facade().get_mobile_user)):
    nonce = body.nonce.strip()
    code = body.code.strip()
    if not nonce and (not code):
        return _facade().JSONResponse(_facade().format_mobile_response(None, '缺少配对码', success=False, code=400), status_code=400)
    rec = _facade().consume_by_shortcode(code) if code else _facade().consume_pairing_nonce(nonce)
    if not rec:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '配对码无效或已过期，请刷新二维码', success=False, code=400), status_code=400)
    user_public = _facade()._resolve_mobile_relay_user(user, prefer_admin=True)
    data = {**_facade()._enrich_pairing_payload(rec), **_facade()._relay_mobile_auth_payload(user_public), 'hint': '已返回可保存的 api_base_url，手机端可直接绑定该设备。'}
    relay = _facade()._cached_desktop_relay_for_account_binding()
    if relay:
        data['relay'] = relay
        data['relay_id'] = relay.get('relay_id')
        data['relay_base_url'] = relay.get('relay_base_url')
        data['relay_binding_mode'] = 'account_auth'
    return _facade().format_mobile_response(data=data)

@_facade().extension_router.get('/service-bridge/requests')
async def mobile_service_bridge_requests(request: _facade().Request, status: str | None=None, source_instance_id: str | None=None, request_type: str | None=None, page: int=_facade().Query(1, ge=1), per_page: int=_facade().Query(20, ge=1, le=100), user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    from app.db.session import get_db
    with get_db() as db:
        from app.db.models.service_request import ServiceRequest
        q = db.query(ServiceRequest)
        if status:
            q = q.filter(ServiceRequest.status == status)
        if source_instance_id:
            q = q.filter(ServiceRequest.source_instance_id == source_instance_id)
        if request_type:
            q = q.filter(ServiceRequest.request_type == request_type)
        total = q.count()
        items = q.order_by(ServiceRequest.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
        return _facade().format_mobile_response(data=_facade().paginate_list([r.to_dict() for r in items], total, page, per_page))

@_facade().extension_router.put('/service-bridge/requests/{request_id}/respond')
async def mobile_service_bridge_request_respond(request_id: int, body: _facade().MobileServiceBridgeRespondBody, user=_facade().Depends(_facade().get_mobile_user)):
    if request_id <= 0:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '请求 ID 无效', success=False, code=400), status_code=400)
    if body.status not in _facade()._mobile_bridge_request_statuses():
        return _facade().JSONResponse(_facade().format_mobile_response(None, '状态值非法', success=False, code=400), status_code=400)
    if user is None:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    from app.db.session import get_db
    try:
        with get_db() as db:
            from app.db.models.service_request import ServiceRequest
            req = db.query(ServiceRequest).filter(ServiceRequest.id == request_id).first()
            if not req:
                return _facade().JSONResponse(_facade().format_mobile_response(None, '请求不存在', success=False, code=404), status_code=404)
            req.response = body.response
            req.responded_by = body.responded_by
            req.responded_at = _facade().datetime.utcnow()
            req.status = body.status
            db.flush()
        return _facade().format_mobile_response(data=req.to_dict())
    except _facade().HTTPException:
        raise
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile_service_bridge_request_respond')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '服务响应失败', success=False, code=500), status_code=500)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile service-bridge respond failed')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '服务响应失败', success=False, code=500), status_code=500)

@_facade().extension_router.post('/relay/desktop/register')
async def mobile_relay_desktop_register(body: _facade().RelayDesktopRegisterBody):
    """Desktop runtime registers a long-lived cloud relay binding session."""
    try:
        data = _facade().MobileRelayService().register_desktop(label=body.label, device_id=body.device_id, capabilities=body.capabilities, relay_base_url=body.relay_base_url)
        return _facade().format_mobile_response(data=data)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile_relay_desktop_register')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '桌面端注册失败', success=False, code=500), status_code=500)

@_facade().extension_router.post('/relay/mobile/bind-account')
async def mobile_relay_bind_account(body: _facade().RelayMobileBindAccountBody, user=_facade().Depends(_facade().get_mobile_user)):
    (uid, username) = _facade()._mobile_user_identity(user)
    if uid <= 0:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    try:
        desktop = _facade().MobileRelayService().bind_mobile_by_account(user_id=uid, username=username, relay_id=body.relay_id)
        if not desktop:
            return _facade().JSONResponse(_facade().format_mobile_response(None, '未找到可绑定的电脑执行端', success=False, code=404), status_code=404)
        user_public = _facade()._mobile_user_public_dict(user)
        return _facade().format_mobile_response(data={'desktop': desktop, 'relay_id': desktop.get('relay_id'), **_facade()._relay_mobile_auth_payload(user_public, desktop)})
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile_relay_bind_account')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '账号绑定失败', success=False, code=500), status_code=500)

@_facade().extension_router.get('/relay/mobile/desktops')
async def mobile_relay_desktops(user=_facade().Depends(_facade().get_mobile_user)):
    (uid, _) = _facade()._mobile_user_identity(user)
    if uid <= 0:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    try:
        items = _facade().MobileRelayService().list_desktops(user_id=uid)
        return _facade().format_mobile_response(data={'items': items, 'count': len(items)})
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile_relay_desktops')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '暂时无法获取桌面端', success=False, code=500), status_code=500)

@_facade().extension_router.post('/relay/tasks')
async def mobile_relay_create_task(body: _facade().RelayTaskCreateBody, user=_facade().Depends(_facade().get_mobile_user)):
    (uid, _) = _facade()._mobile_user_identity(user)
    if uid <= 0:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    try:
        payload = dict(body.payload or {})
        payload.setdefault('user_id', uid)
        task = _facade().MobileRelayService().create_task(user_id=uid, relay_id=body.relay_id, kind=body.kind, payload=payload)
        if not task:
            return _facade().JSONResponse(_facade().format_mobile_response(None, '未找到已绑定的电脑执行端', success=False, code=404), status_code=404)
        return _facade().format_mobile_response(data={'task': task})
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile_relay_create_task')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '任务创建失败', success=False, code=500), status_code=500)

@_facade().extension_router.get('/relay/tasks/{task_id}')
async def mobile_relay_task_status(task_id: str, user=_facade().Depends(_facade().get_mobile_user)):
    (uid, _) = _facade()._mobile_user_identity(user)
    if uid <= 0:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    task = _facade().MobileRelayService().get_task(user_id=uid, task_id=task_id)
    if not task:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '任务不存在', success=False, code=404), status_code=404)
    return _facade().format_mobile_response(data={'task': task})

@_facade().extension_router.post('/relay/tasks/{task_id}/cancel')
async def mobile_relay_task_cancel(task_id: str, user=_facade().Depends(_facade().get_mobile_user)):
    (uid, _) = _facade()._mobile_user_identity(user)
    if uid <= 0:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '未授权', success=False, code=401), status_code=401)
    task = _facade().MobileRelayService().cancel_task(user_id=uid, task_id=task_id)
    if not task:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '任务不存在', success=False, code=404), status_code=404)
    return _facade().format_mobile_response(data={'task': task})

@_facade().extension_router.post('/relay/desktop/poll')
async def mobile_relay_desktop_poll(body: _facade().RelayDesktopPollBody):
    try:
        data = _facade().MobileRelayService().poll_desktop(relay_id=body.relay_id, desktop_token=body.desktop_token, max_tasks=body.max_tasks)
        if not data:
            return _facade().JSONResponse(_facade().format_mobile_response(None, '中继桌面凭证无效', success=False, code=404), status_code=404)
        return _facade().format_mobile_response(data=data)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile_relay_desktop_poll')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '轮询桌面任务失败', success=False, code=500), status_code=500)

@_facade().extension_router.post('/relay/desktop/tasks/{task_id}/complete')
async def mobile_relay_desktop_complete(task_id: str, body: _facade().RelayDesktopCompleteBody):
    try:
        task = _facade().MobileRelayService().complete_desktop_task(relay_id=body.relay_id, desktop_token=body.desktop_token, task_id=task_id, status=body.status, result=body.result)
        if not task:
            return _facade().JSONResponse(_facade().format_mobile_response(None, '任务或桌面凭证无效', success=False, code=404), status_code=404)
        return _facade().format_mobile_response(data={'task': task})
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile_relay_desktop_complete')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '任务完成回传失败', success=False, code=500), status_code=500)

@_facade().extension_router.get('/admin/employees')
async def mobile_admin_employees(request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user)):
    (_, err) = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    (market_profiles, market_connected, market_error) = await _facade()._load_market_ai_employee_profile_index()
    uid = _facade()._mobile_request_user_id(request, user)
    im_summary: dict[str, dict[str, _facade().Any]] = {}
    if uid > 0:
        try:
            from app.application.im_app_service import ImApplicationService
            from app.db import SessionLocal
            db = SessionLocal()
            try:
                raw_items = _facade()._admin_employee_items(market_profiles, market_connected=market_connected)
                im_summary = ImApplicationService(db).employee_im_summary(uid, raw_items)
            finally:
                db.close()
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug('employee_im_summary skipped for /admin/employees', exc_info=True)
    items = _facade()._admin_employee_items(market_profiles, market_connected=market_connected, im_summary=im_summary)
    return _facade().format_mobile_response(data={'items': items, 'count': len(items), 'market_connected': market_connected, 'market_profile_count': len(market_profiles), 'market_error': market_error})

@_facade().extension_router.get('/admin/features')
async def mobile_admin_features(request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user)):
    (_, err) = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    return _facade().format_mobile_response(data={'items': _facade().ADMIN_MOBILE_FEATURES, 'count': len(_facade().ADMIN_MOBILE_FEATURES)})

@_facade().extension_router.get('/im/cs/inbox')
async def mobile_im_cs_inbox(request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user)):
    """运营者手机:列出所有企业客户的专属客服会话。"""
    (_, err) = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db
    try:
        with get_db() as db:
            items = ImApplicationService(db).list_cs_inbox()
        conversations = [{'conversationId': c.get('id'), 'customerName': c.get('customer_name') or f"用户{c.get('customer_user_id')}", 'lastMessageAt': str(c.get('last_message_at') or ''), 'unreadCount': int(c.get('unread_count') or 0)} for c in items]
        return _facade().format_mobile_response(data={'conversations': conversations})
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile cs inbox failed')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '客服收件箱加载失败', success=False, code=500), status_code=500)

@_facade().extension_router.get('/im/cs/inbox/{conversation_id}/messages')
async def mobile_im_cs_inbox_messages(conversation_id: int, request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user)):
    """运营者手机:读某客服会话历史(fromCustomer 区分客户/客服)。"""
    (_, err) = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db
    try:
        with get_db() as db:
            svc = ImApplicationService(db)
            cs_id = int(svc.enterprise_cs_user_id() or 0)
            raw = svc.cs_inbox_messages(conversation_id)
        messages = [{'messageId': str(m.get('id') or ''), 'fromCustomer': int(m.get('sender_user_id') or 0) != cs_id, 'senderName': str(m.get('sender_display_name') or ''), 'body': str(m.get('body') or ''), 'timestamp': str(m.get('created_at') or '')} for m in raw]
        return _facade().format_mobile_response(data={'messages': messages})
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile cs inbox messages failed')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '客服消息加载失败', success=False, code=500), status_code=500)

@_facade().extension_router.post('/im/cs/inbox/{conversation_id}/reply')
async def mobile_im_cs_inbox_reply(conversation_id: int, body: dict, request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user)):
    """运营者手机:以「企业专属客服」身份回复客户。"""
    (_, err) = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    text = str(body.get('body') or '').strip()
    if not text:
        return _facade().JSONResponse(_facade().format_mobile_response(None, '消息不能为空', success=False, code=400), status_code=400)
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db
    try:
        with get_db() as db:
            result = ImApplicationService(db).cs_reply(conversation_id, text)
        sent = result.get('message') or {}
        return _facade().format_mobile_response(data={'messageId': str(sent.get('id') or ''), 'timestamp': str(sent.get('created_at') or '')})
    except (ValueError, PermissionError):
        return _facade().JSONResponse(_facade().format_mobile_response(None, '回复内容无效', success=False, code=400), status_code=400)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('mobile cs inbox reply failed')
        return _facade().JSONResponse(_facade().format_mobile_response(None, '客服回复失败', success=False, code=500), status_code=500)
