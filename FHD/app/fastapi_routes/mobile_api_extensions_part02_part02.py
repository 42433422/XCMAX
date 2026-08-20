# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.mobile_api_extensions")


@_facade().extension_router.put("/service-bridge/requests/{request_id}/respond")
async def mobile_service_bridge_request_respond(
    request_id: int,
    body: _facade().MobileServiceBridgeRespondBody,
    user=_facade().Depends(_facade().get_mobile_user),
):
    if request_id <= 0:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "请求 ID 无效", success=False, code=400),
            status_code=400,
        )
    if body.status not in _facade()._mobile_bridge_request_statuses():
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "状态值非法", success=False, code=400),
            status_code=400,
        )
    if user is None:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    from app.db.session import get_db

    try:
        with get_db() as db:
            from app.db.models.service_request import ServiceRequest

            req = db.query(ServiceRequest).filter(ServiceRequest.id == request_id).first()
            if not req:
                return _facade().JSONResponse(
                    _facade().format_mobile_response(None, "请求不存在", success=False, code=404),
                    status_code=404,
                )
            req.response = body.response
            req.responded_by = body.responded_by
            req.responded_at = _facade().datetime.utcnow()
            req.status = body.status
            db.flush()
        return _facade().format_mobile_response(data=req.to_dict())
    except _facade().HTTPException:
        raise
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile_service_bridge_request_respond")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "服务响应失败", success=False, code=500),
            status_code=500,
        )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile service-bridge respond failed")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "服务响应失败", success=False, code=500),
            status_code=500,
        )


@_facade().extension_router.post("/relay/desktop/register")
async def mobile_relay_desktop_register(body: _facade().RelayDesktopRegisterBody):
    """Desktop runtime registers a long-lived cloud relay binding session."""
    try:
        data = (
            _facade()
            .MobileRelayService()
            .register_desktop(
                label=body.label,
                device_id=body.device_id,
                capabilities=body.capabilities,
                relay_base_url=body.relay_base_url,
            )
        )
        return _facade().format_mobile_response(data=data)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile_relay_desktop_register")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "桌面端注册失败", success=False, code=500),
            status_code=500,
        )


@_facade().extension_router.post("/relay/mobile/bind-account")
async def mobile_relay_bind_account(
    body: _facade().RelayMobileBindAccountBody, user=_facade().Depends(_facade().get_mobile_user)
):
    uid, username = _facade()._mobile_user_identity(user)
    if uid <= 0:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        desktop = (
            _facade()
            .MobileRelayService()
            .bind_mobile_by_account(user_id=uid, username=username, relay_id=body.relay_id)
        )
        if not desktop:
            return _facade().JSONResponse(
                _facade().format_mobile_response(
                    None, "未找到可绑定的电脑执行端", success=False, code=404
                ),
                status_code=404,
            )
        user_public = _facade()._mobile_user_public_dict(user)
        return _facade().format_mobile_response(
            data={
                "desktop": desktop,
                "relay_id": desktop.get("relay_id"),
                **_facade()._relay_mobile_auth_payload(user_public, desktop),
            }
        )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile_relay_bind_account")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "账号绑定失败", success=False, code=500),
            status_code=500,
        )


@_facade().extension_router.get("/relay/mobile/desktops")
async def mobile_relay_desktops(user=_facade().Depends(_facade().get_mobile_user)):
    uid, _ = _facade()._mobile_user_identity(user)
    if uid <= 0:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        items = _facade().MobileRelayService().list_desktops(user_id=uid)
        return _facade().format_mobile_response(data={"items": items, "count": len(items)})
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile_relay_desktops")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "暂时无法获取桌面端", success=False, code=500),
            status_code=500,
        )


@_facade().extension_router.post("/relay/tasks")
async def mobile_relay_create_task(
    body: _facade().RelayTaskCreateBody, user=_facade().Depends(_facade().get_mobile_user)
):
    uid, _ = _facade()._mobile_user_identity(user)
    if uid <= 0:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        payload = dict(body.payload or {})
        payload.setdefault("user_id", uid)
        task = (
            _facade()
            .MobileRelayService()
            .create_task(user_id=uid, relay_id=body.relay_id, kind=body.kind, payload=payload)
        )
        if not task:
            return _facade().JSONResponse(
                _facade().format_mobile_response(
                    None, "未找到已绑定的电脑执行端", success=False, code=404
                ),
                status_code=404,
            )
        return _facade().format_mobile_response(data={"task": task})
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile_relay_create_task")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "任务创建失败", success=False, code=500),
            status_code=500,
        )


@_facade().extension_router.get("/relay/tasks/{task_id}")
async def mobile_relay_task_status(task_id: str, user=_facade().Depends(_facade().get_mobile_user)):
    uid, _ = _facade()._mobile_user_identity(user)
    if uid <= 0:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    task = _facade().MobileRelayService().get_task(user_id=uid, task_id=task_id)
    if not task:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "任务不存在", success=False, code=404),
            status_code=404,
        )
    return _facade().format_mobile_response(data={"task": task})


@_facade().extension_router.post("/relay/tasks/{task_id}/cancel")
async def mobile_relay_task_cancel(task_id: str, user=_facade().Depends(_facade().get_mobile_user)):
    uid, _ = _facade()._mobile_user_identity(user)
    if uid <= 0:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    task = _facade().MobileRelayService().cancel_task(user_id=uid, task_id=task_id)
    if not task:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "任务不存在", success=False, code=404),
            status_code=404,
        )
    return _facade().format_mobile_response(data={"task": task})


@_facade().extension_router.post("/relay/desktop/poll")
async def mobile_relay_desktop_poll(body: _facade().RelayDesktopPollBody):
    try:
        data = (
            _facade()
            .MobileRelayService()
            .poll_desktop(
                relay_id=body.relay_id, desktop_token=body.desktop_token, max_tasks=body.max_tasks
            )
        )
        if not data:
            return _facade().JSONResponse(
                _facade().format_mobile_response(None, "中继桌面凭证无效", success=False, code=404),
                status_code=404,
            )
        return _facade().format_mobile_response(data=data)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile_relay_desktop_poll")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "轮询桌面任务失败", success=False, code=500),
            status_code=500,
        )


@_facade().extension_router.post("/relay/desktop/tasks/{task_id}/complete")
async def mobile_relay_desktop_complete(task_id: str, body: _facade().RelayDesktopCompleteBody):
    try:
        task = (
            _facade()
            .MobileRelayService()
            .complete_desktop_task(
                relay_id=body.relay_id,
                desktop_token=body.desktop_token,
                task_id=task_id,
                status=body.status,
                result=body.result,
            )
        )
        if not task:
            return _facade().JSONResponse(
                _facade().format_mobile_response(
                    None, "任务或桌面凭证无效", success=False, code=404
                ),
                status_code=404,
            )
        return _facade().format_mobile_response(data={"task": task})
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile_relay_desktop_complete")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "任务完成回传失败", success=False, code=500),
            status_code=500,
        )


@_facade().extension_router.get("/admin/employees")
async def mobile_admin_employees(
    request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user)
):
    _, err = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    (
        market_profiles,
        market_connected,
        market_error,
    ) = await _facade()._load_market_ai_employee_profile_index()
    uid = _facade()._mobile_request_user_id(request, user)
    im_summary: dict[str, dict[str, _facade().Any]] = {}
    if uid > 0:
        try:
            from app.application.im_app_service import ImApplicationService
            from app.db import SessionLocal

            db = SessionLocal()
            try:
                raw_items = _facade()._admin_employee_items(
                    market_profiles, market_connected=market_connected
                )
                im_summary = ImApplicationService(db).employee_im_summary(uid, raw_items)
            finally:
                db.close()
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug(
                "employee_im_summary skipped for /admin/employees", exc_info=True
            )
    items = _facade()._admin_employee_items(
        market_profiles, market_connected=market_connected, im_summary=im_summary
    )
    return _facade().format_mobile_response(
        data={
            "items": items,
            "count": len(items),
            "market_connected": market_connected,
            "market_profile_count": len(market_profiles),
            "market_error": market_error,
        }
    )


@_facade().extension_router.get("/admin/features")
async def mobile_admin_features(
    request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user)
):
    _, err = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    return _facade().format_mobile_response(
        data={
            "items": _facade().ADMIN_MOBILE_FEATURES,
            "count": len(_facade().ADMIN_MOBILE_FEATURES),
        }
    )


@_facade().extension_router.get("/im/cs/inbox")
async def mobile_im_cs_inbox(
    request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user)
):
    """运营者手机:列出所有企业客户的专属客服会话。"""
    _, err = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db

    try:
        with get_db() as db:
            items = ImApplicationService(db).list_cs_inbox()
        conversations = [
            {
                "conversationId": c.get("id"),
                "customerName": c.get("customer_name") or f"用户{c.get('customer_user_id')}",
                "lastMessageAt": str(c.get("last_message_at") or ""),
                "unreadCount": int(c.get("unread_count") or 0),
            }
            for c in items
        ]
        return _facade().format_mobile_response(data={"conversations": conversations})
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile cs inbox failed")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "客服收件箱加载失败", success=False, code=500),
            status_code=500,
        )
