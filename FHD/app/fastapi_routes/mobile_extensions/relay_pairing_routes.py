"""Mobile QR 配对 / 服务桥接 / 云中继 routes (split from mobile_api_extensions).

Included into ``extension_router``; handlers and helpers are re-exported from
``mobile_api_extensions`` for tests and patch compatibility.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_api import get_mobile_user
from app.fastapi_routes.mobile_extensions import _ext as mext
from app.utils.mobile_api import format_mobile_response, paginate_list

logger = logging.getLogger(__name__)

relay_pairing_router = APIRouter()

from app.fastapi_routes.mobile_extensions.models import (
    MobileServiceBridgeRespondBody,
    PairingExchangeBody,
    PairingIssueBody,
    PairingLookupBody,
    RelayDesktopCompleteBody,
    RelayDesktopPollBody,
    RelayDesktopRegisterBody,
    RelayMobileBindAccountBody,
    RelayTaskCreateBody,
)

# ── 配对 ──


@relay_pairing_router.post("/pairing/issue")
async def mobile_pairing_issue(body: PairingIssueBody, request: Request):
    """桌面或运维签发配对 QR 载荷（开发/内网）。"""
    host = mext._pairing_issue_host(body.host or (request.url.hostname or ""))
    api_port = mext._pairing_issue_port(request, int(body.port))
    port = mext._pairing_reachable_port(request, api_port)
    payload = mext.issue_pairing_nonce(host, port)
    data = mext._enrich_pairing_payload(payload, request)
    relay = mext._register_desktop_relay_for_pairing(host, port)
    if relay:
        data["relay"] = relay
        data["relay_id"] = relay.get("relay_id")
        data["relay_base_url"] = relay.get("relay_base_url")
        data["relay_binding_mode"] = "account_auth"
    return format_mobile_response(data=data)


@relay_pairing_router.post("/pairing/lookup")
async def mobile_pairing_lookup(body: PairingLookupBody):
    code = body.code.strip()
    rec = mext.lookup_by_shortcode(code)
    if not rec:
        return JSONResponse(
            format_mobile_response(None, "配对码不存在或已过期", success=False, code=404),
            status_code=404,
        )
    return format_mobile_response(
        data=mext._enrich_pairing_payload(
            {
                "host": rec.get("host"),
                "port": rec.get("port"),
                "nonce": rec.get("nonce"),
                "shortCode": code,
                "exp": rec.get("exp") or 0,
            }
        ),
    )


@relay_pairing_router.post("/pairing/exchange")
async def mobile_pairing_exchange(body: PairingExchangeBody, user=Depends(get_mobile_user)):
    nonce = body.nonce.strip()
    code = body.code.strip()
    if not nonce and not code:
        return JSONResponse(
            format_mobile_response(None, "缺少配对码", success=False, code=400),
            status_code=400,
        )
    rec = mext.consume_by_shortcode(code) if code else mext.consume_pairing_nonce(nonce)
    if not rec:
        return JSONResponse(
            format_mobile_response(
                None, "配对码无效或已过期，请刷新二维码", success=False, code=400
            ),
            status_code=400,
        )
    user_public = mext._resolve_mobile_relay_user(user, prefer_admin=True)
    data = {
        **mext._enrich_pairing_payload(rec),
        **mext._relay_mobile_auth_payload(user_public),
        "hint": "已返回可保存的 api_base_url，手机端可直接绑定该设备。",
    }
    relay = mext._cached_desktop_relay_for_account_binding()
    if relay:
        data["relay"] = relay
        data["relay_id"] = relay.get("relay_id")
        data["relay_base_url"] = relay.get("relay_base_url")
        data["relay_binding_mode"] = "account_auth"
    return format_mobile_response(data=data)


# ── 服务桥接 ──


@relay_pairing_router.get("/service-bridge/requests")
async def mobile_service_bridge_requests(
    request: Request,
    status: str | None = None,
    source_instance_id: str | None = None,
    request_type: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
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
        items = (
            q.order_by(ServiceRequest.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return format_mobile_response(
            data=paginate_list([r.to_dict() for r in items], total, page, per_page)
        )


@relay_pairing_router.put("/service-bridge/requests/{request_id}/respond")
async def mobile_service_bridge_request_respond(
    request_id: int,
    body: MobileServiceBridgeRespondBody,
    user=Depends(get_mobile_user),
):
    if request_id <= 0:
        return JSONResponse(
            format_mobile_response(None, "请求 ID 无效", success=False, code=400),
            status_code=400,
        )
    if body.status not in mext._mobile_bridge_request_statuses():
        return JSONResponse(
            format_mobile_response(None, "状态值非法", success=False, code=400),
            status_code=400,
        )
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.db.session import get_db

    try:
        with get_db() as db:
            from app.db.models.service_request import ServiceRequest

            req = db.query(ServiceRequest).filter(ServiceRequest.id == request_id).first()
            if not req:
                return JSONResponse(
                    format_mobile_response(None, "请求不存在", success=False, code=404),
                    status_code=404,
                )
            req.response = body.response
            req.responded_by = body.responded_by
            req.responded_at = datetime.utcnow()
            req.status = body.status
            db.flush()
        return format_mobile_response(data=req.to_dict())
    except HTTPException:
        raise
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_service_bridge_request_respond")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )
    except Exception as exc:
        logger.exception("mobile service-bridge respond failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


# ── 中继服务 ──


@relay_pairing_router.post("/relay/desktop/register")
async def mobile_relay_desktop_register(body: RelayDesktopRegisterBody):
    """Desktop runtime registers a long-lived cloud relay binding session."""
    try:
        data = mext.MobileRelayService().register_desktop(
            label=body.label,
            device_id=body.device_id,
            capabilities=body.capabilities,
            relay_base_url=body.relay_base_url,
        )
        return format_mobile_response(data=data)
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_relay_desktop_register")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@relay_pairing_router.post("/relay/mobile/bind-account")
async def mobile_relay_bind_account(
    body: RelayMobileBindAccountBody,
    user=Depends(get_mobile_user),
):
    uid, username = mext._mobile_user_identity(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        desktop = mext.MobileRelayService().bind_mobile_by_account(
            user_id=uid,
            username=username,
            relay_id=body.relay_id,
        )
        if not desktop:
            return JSONResponse(
                format_mobile_response(None, "未找到可绑定的电脑执行端", success=False, code=404),
                status_code=404,
            )
        user_public = mext._mobile_user_public_dict(user)
        return format_mobile_response(
            data={
                "desktop": desktop,
                "relay_id": desktop.get("relay_id"),
                **mext._relay_mobile_auth_payload(user_public, desktop),
            }
        )
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_relay_bind_account")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@relay_pairing_router.get("/relay/mobile/desktops")
async def mobile_relay_desktops(user=Depends(get_mobile_user)):
    uid, _ = mext._mobile_user_identity(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        items = mext.MobileRelayService().list_desktops(user_id=uid)
        return format_mobile_response(data={"items": items, "count": len(items)})
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_relay_desktops")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@relay_pairing_router.post("/relay/tasks")
async def mobile_relay_create_task(body: RelayTaskCreateBody, user=Depends(get_mobile_user)):
    uid, _ = mext._mobile_user_identity(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        payload = dict(body.payload or {})
        payload.setdefault("user_id", uid)
        task = mext.MobileRelayService().create_task(
            user_id=uid,
            relay_id=body.relay_id,
            kind=body.kind,
            payload=payload,
        )
        if not task:
            return JSONResponse(
                format_mobile_response(None, "未找到已绑定的电脑执行端", success=False, code=404),
                status_code=404,
            )
        return format_mobile_response(data={"task": task})
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_relay_create_task")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@relay_pairing_router.get("/relay/tasks/{task_id}")
async def mobile_relay_task_status(task_id: str, user=Depends(get_mobile_user)):
    uid, _ = mext._mobile_user_identity(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    task = mext.MobileRelayService().get_task(user_id=uid, task_id=task_id)
    if not task:
        return JSONResponse(
            format_mobile_response(None, "任务不存在", success=False, code=404),
            status_code=404,
        )
    return format_mobile_response(data={"task": task})


@relay_pairing_router.post("/relay/tasks/{task_id}/cancel")
async def mobile_relay_task_cancel(task_id: str, user=Depends(get_mobile_user)):
    uid, _ = mext._mobile_user_identity(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    task = mext.MobileRelayService().cancel_task(user_id=uid, task_id=task_id)
    if not task:
        return JSONResponse(
            format_mobile_response(None, "任务不存在", success=False, code=404),
            status_code=404,
        )
    return format_mobile_response(data={"task": task})


@relay_pairing_router.post("/relay/desktop/poll")
async def mobile_relay_desktop_poll(body: RelayDesktopPollBody):
    try:
        data = mext.MobileRelayService().poll_desktop(
            relay_id=body.relay_id,
            desktop_token=body.desktop_token,
            max_tasks=body.max_tasks,
            capabilities=body.capabilities,
        )
        if not data:
            return JSONResponse(
                format_mobile_response(None, "中继桌面凭证无效", success=False, code=404),
                status_code=404,
            )
        return format_mobile_response(data=data)
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_relay_desktop_poll")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@relay_pairing_router.post("/relay/desktop/tasks/{task_id}/complete")
async def mobile_relay_desktop_complete(task_id: str, body: RelayDesktopCompleteBody):
    try:
        task = mext.MobileRelayService().complete_desktop_task(
            relay_id=body.relay_id,
            desktop_token=body.desktop_token,
            task_id=task_id,
            status=body.status,
            result=body.result,
        )
        if not task:
            return JSONResponse(
                format_mobile_response(None, "任务或桌面凭证无效", success=False, code=404),
                status_code=404,
            )
        return format_mobile_response(data={"task": task})
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_relay_desktop_complete")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )
