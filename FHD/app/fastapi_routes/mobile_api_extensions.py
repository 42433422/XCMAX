"""移动端 API 扩展：代理列表、设备注册、QR 配对。"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.application.codex_super_employee_service import CodexSuperEmployeeService
from app.fastapi_routes.mobile_api import get_mobile_user
from app.security.mobile_jwt import issue_mobile_tokens
from app.security.mobile_pairing import (
    consume_by_shortcode,
    consume_pairing_nonce,
    issue_pairing_nonce,
    lookup_by_shortcode,
)
from app.services.mobile_relay_service import MobileRelayService
from app.utils.mobile_api import format_mobile_response, paginate_list
from app.utils.operational_errors import RECOVERABLE_ERRORS

OPERATIONAL_ERRORS = RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

extension_router = APIRouter(tags=["mobile-api-ext"])

_MARKET_AI_EMPLOYEE_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "profiles": {},
    "connected": False,
    "error": "",
}


def _ensure_mobile_device_table() -> None:
    try:
        from sqlalchemy import inspect

        from app.db.models.mobile_device import MobileDeviceToken
        from app.db.session import get_db

        with get_db() as db:
            bind = db.get_bind()
            insp = inspect(bind)
            if not insp.has_table(MobileDeviceToken.__tablename__):
                MobileDeviceToken.__table__.create(bind, checkfirst=True)
    except OPERATIONAL_ERRORS as exc:
        logger.warning("mobile_device_tokens ensure: %s", exc)


class DeviceRegisterBody(BaseModel):
    fcm_token: str = Field(..., min_length=8)
    push_provider: str = Field(default="fcm", max_length=16)
    push_token: str = Field(default="", max_length=512)
    product_sku: str = Field(default="personal", max_length=32)
    device_label: str = Field(default="", max_length=200)
    platform: str = Field(default="android", max_length=32)


class PairingExchangeBody(BaseModel):
    nonce: str = Field(default="", max_length=128)
    code: str = Field(default="", max_length=16)


class PairingLookupBody(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class PairingIssueBody(BaseModel):
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=5000, ge=1, le=65535)


class RelayDesktopRegisterBody(BaseModel):
    label: str = Field(default="", max_length=200)
    device_id: str = Field(default="", max_length=128)
    relay_base_url: str = Field(default="", max_length=512)
    capabilities: dict[str, Any] = Field(default_factory=dict)


class RelayMobileConfirmBody(BaseModel):
    relay_id: str = Field(..., min_length=8, max_length=80)
    code: str = Field(..., min_length=4, max_length=16)


class RelayMobileConfirmCodeBody(BaseModel):
    code: str = Field(..., min_length=4, max_length=16)


class RelayTaskCreateBody(BaseModel):
    relay_id: str = Field(..., min_length=8, max_length=80)
    kind: str = Field(default="codex.invoke", max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class RelayDesktopPollBody(BaseModel):
    relay_id: str = Field(..., min_length=8, max_length=80)
    desktop_token: str = Field(..., min_length=16, max_length=256)
    max_tasks: int = Field(default=5, ge=1, le=20)


class RelayDesktopCompleteBody(BaseModel):
    relay_id: str = Field(..., min_length=8, max_length=80)
    desktop_token: str = Field(..., min_length=16, max_length=256)
    status: str = Field(default="completed", max_length=32)
    result: dict[str, Any] = Field(default_factory=dict)


class CodexSuperEmployeeMobileMessageBody(BaseModel):
    message: str = Field(default="", max_length=4000)
    body: str = Field(default="", max_length=4000)
    context: dict[str, Any] = Field(default_factory=dict)


class MobileServiceBridgeRespondBody(BaseModel):
    response: str
    responded_by: str | None = None
    status: str = Field(default="resolved", max_length=32)


@extension_router.get("/approval/requests")
async def mobile_approval_list(
    request: Request,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.db.models.approval import ApprovalRequest
    from app.db.session import get_db

    with get_db() as db:
        q = db.query(ApprovalRequest)
        if status:
            q = q.filter(ApprovalRequest.status == status)
        total = q.count()
        rows = (
            q.order_by(ApprovalRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [
            {
                "id": r.id,
                "title": r.title,
                "status": r.status,
                "request_no": r.request_no,
                "applicant_id": r.applicant_id,
            }
            for r in rows
        ]
    return format_mobile_response(data=paginate_list(items, total, page, page_size))


@extension_router.get("/customers")
async def mobile_customers(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.db.models import Customer
    from app.db.session import get_db

    with get_db() as db:
        q = db.query(Customer)
        total = q.count()
        rows = q.offset((page - 1) * per_page).limit(per_page).all()
        items = [
            {
                "id": c.id,
                "name": c.customer_name,
                "phone": c.contact_phone,
            }
            for c in rows
        ]
    return format_mobile_response(data=paginate_list(items, total, page, per_page))


@extension_router.get("/shipments")
async def mobile_shipments(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.db.models.shipment import ShipmentRecord
    from app.db.session import get_db

    with get_db() as db:
        q = db.query(ShipmentRecord)
        total = q.count()
        rows = (
            q.order_by(ShipmentRecord.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
        )
        items = [
            {
                "id": r.id,
                "order_number": getattr(r, "order_number", None) or getattr(r, "shipment_no", None),
                "status": getattr(r, "status", None),
            }
            for r in rows
        ]
    return format_mobile_response(data=paginate_list(items, total, page, per_page))


@extension_router.post("/devices/register")
async def mobile_device_register(body: DeviceRegisterBody, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    _ensure_mobile_device_table()
    from app.db.models.mobile_device import MobileDeviceToken
    from app.db.session import get_db
    from app.utils.time import utc_now_naive

    token = (body.push_token or body.fcm_token).strip()
    provider = (body.push_provider or "fcm").strip().lower()[:16]
    if not token:
        return JSONResponse(
            format_mobile_response(None, "缺少 push_token", success=False, code=400),
            status_code=400,
        )
    with get_db() as db:
        row = (
            db.query(MobileDeviceToken)
            .filter(
                MobileDeviceToken.user_id == user.id,
                MobileDeviceToken.fcm_token == body.fcm_token.strip(),
            )
            .first()
        )
        if row:
            row.device_label = body.device_label[:200]
            row.platform = body.platform[:32]
            row.fcm_token = body.fcm_token.strip()[:512]
            row.push_provider = provider
            row.push_token = token
            row.product_sku = (body.product_sku or "personal")[:32]
            row.updated_at = utc_now_naive()
        else:
            db.add(
                MobileDeviceToken(
                    user_id=user.id,
                    fcm_token=body.fcm_token.strip(),
                    push_provider=provider,
                    push_token=token,
                    product_sku=(body.product_sku or "personal")[:32],
                    platform=body.platform[:32],
                    device_label=body.device_label[:200],
                )
            )
    return format_mobile_response(data={"registered": True})


@extension_router.delete("/devices/unregister")
async def mobile_device_unregister(
    fcm_token: str = Query(..., min_length=8),
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    _ensure_mobile_device_table()
    from app.db.models.mobile_device import MobileDeviceToken
    from app.db.session import get_db

    with get_db() as db:
        db.query(MobileDeviceToken).filter(
            MobileDeviceToken.user_id == user.id,
            MobileDeviceToken.fcm_token == fcm_token.strip(),
        ).delete()
    return format_mobile_response(data={"unregistered": True})


def _guess_lan_ipv4() -> str:
    """本机对外网卡 IPv4，供手机扫码时避免 127.0.0.1。"""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ip = str(probe.getsockname()[0] or "").strip()
        probe.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return "127.0.0.1"


def _pairing_issue_host(requested: str) -> str:
    host = str(requested or "").strip() or "127.0.0.1"
    if host in ("127.0.0.1", "localhost", "0.0.0.0"):
        return _guess_lan_ipv4()
    return host


def _pairing_issue_port(request: Request, requested: int) -> int:
    request_port = _request_host_port(request)
    # Older callers omitted the port but hit the model default 5000.  When the
    # current request clearly arrived on another port, prefer that real API port
    # so mobile phones do not bind to stale desktop defaults.
    if requested > 0 and not (requested == 5000 and request_port not in (0, 5000)):
        return requested
    if request_port:
        return request_port
    for key in ("XCAGI_API_PORT", "FASTAPI_PORT"):
        raw = os.environ.get(key, "").strip()
        port = int(raw) if raw.isdigit() else 0
        if 0 < port <= 65535:
            return port
    return 5000


def _request_host_port(request: Request) -> int:
    host_header = (request.headers.get("host") or "").strip()
    if ":" in host_header:
        raw_port = host_header.rsplit(":", 1)[-1]
        port = int(raw_port) if raw_port.isdigit() else 0
        if 0 < port <= 65535:
            return port
    return 0


def _pairing_api_base_url(host: str, port: int) -> str:
    clean_host = str(host or "").strip().removeprefix("http://").removeprefix("https://")
    clean_host = clean_host.strip("/").split("/", 1)[0].split("?", 1)[0]
    bare_host = clean_host.rsplit(":", 1)[0] if ":" in clean_host else clean_host
    clean_port = int(port or 0)
    if clean_port <= 0:
        clean_port = 5000
    return f"http://{bare_host}:{clean_port}/"


def _host_is_private_or_loopback(host: str) -> bool:
    clean = str(host or "").strip().removeprefix("http://").removeprefix("https://")
    clean = clean.strip("/").split("/", 1)[0].split("?", 1)[0].rsplit(":", 1)[0]
    try:
        ip = ipaddress.ip_address(clean)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return clean in {"localhost", "0.0.0.0"} or clean.endswith(".local")


def _mobile_user_identity(user: Any) -> tuple[int, str]:
    uid = int(getattr(user, "id", 0) or 0)
    username = str(
        getattr(user, "username", "")
        or getattr(user, "display_name", "")
        or getattr(user, "email", "")
        or ""
    ).strip()
    return uid, username


def _mobile_user_public_dict(user: Any) -> dict[str, Any]:
    return {
        "id": int(getattr(user, "id", 0) or 0),
        "username": str(getattr(user, "username", "") or ""),
        "display_name": str(getattr(user, "display_name", "") or ""),
        "email": str(getattr(user, "email", "") or ""),
        "role": str(getattr(user, "role", "") or ""),
        "is_active": bool(getattr(user, "is_active", True)),
        "account_id": str(getattr(user, "account_id", "") or ""),
        "tenant_id": str(getattr(user, "tenant_id", "") or ""),
    }


def _relay_admin_fallback_user() -> dict[str, Any]:
    return {
        "id": 1,
        "username": "admin",
        "display_name": "管理员账号",
        "email": "",
        "role": "admin",
        "is_active": True,
    }


def _resolve_mobile_relay_user(user: Any, *, prefer_admin: bool = False) -> dict[str, Any]:
    """Resolve the mobile user for physical QR/device-code relay binding.

    A relay pairing code already proves physical access to the desktop settings
    screen, so first-time mobile binding must not require a pre-existing mobile
    JWT. Prefer an existing admin account; create a local relay admin only when
    the database has no active users yet.
    """
    uid, _ = _mobile_user_identity(user)
    role = str(getattr(user, "role", "") or "").strip()
    if uid > 0 and (not prefer_admin or role in {"admin", "super_admin", "owner"}):
        return _mobile_user_public_dict(user)

    from app.db.models import User
    from app.db.session import get_db

    try:
        with get_db() as db:
            row = None
            if prefer_admin or uid <= 0:
                row = (
                    db.query(User)
                    .filter(User.is_active == True)  # noqa: E712
                    .filter(User.role.in_(["admin", "super_admin", "owner"]))
                    .order_by(User.id.asc())
                    .first()
                )
            if row is None:
                row = (
                    db.query(User)
                    .filter(User.is_active == True)  # noqa: E712
                    .order_by(User.id.asc())
                    .first()
                )
            if row is None:
                now = datetime.utcnow()
                row = User(
                    username=f"mobile_relay_{uuid.uuid4().hex[:8]}",
                    password=uuid.uuid4().hex,
                    display_name="移动端设备绑定",
                    email="",
                    role="admin",
                    is_active=True,
                    created_at=now,
                    last_login=now,
                )
                db.add(row)
                db.flush()
            public = _mobile_user_public_dict(row)
            if hasattr(db, "expunge"):
                db.expunge(row)
            return public
    except RECOVERABLE_ERRORS as exc:
        logger.warning("mobile relay admin fallback: %s", exc)
        if prefer_admin:
            return _relay_admin_fallback_user()
        raise


def _relay_mobile_auth_payload(
    user_public: dict[str, Any],
    desktop: dict[str, Any] | None = None,
) -> dict[str, Any]:
    uid = int(user_public.get("id") or 0)
    username = str(user_public.get("username") or user_public.get("display_name") or "mobile")
    role = str(user_public.get("role") or "")
    account_kind = "admin" if role in {"admin", "super_admin", "owner"} else "enterprise"
    session_id = f"mobile-relay-{uuid.uuid4().hex}"
    relay = desktop or {}
    return {
        "user": user_public,
        "session_id": session_id,
        "session_token": str(relay.get("session_token") or user_public.get("session_token") or session_id).strip(),
        "account_id": str(relay.get("account_id") or user_public.get("account_id") or uid).strip(),
        "tenant_id": str(relay.get("tenant_id") or user_public.get("tenant_id") or "").strip(),
        "relay_base_url": str(relay.get("relay_base_url") or user_public.get("relay_base_url") or "").strip(),
        "local_base_url": str(relay.get("local_base_url") or user_public.get("local_base_url") or "").strip(),
        "paired_at": str(relay.get("paired_at") or user_public.get("paired_at") or "").strip(),
        "account_kind": account_kind,
        **issue_mobile_tokens(
            user_id=uid,
            session_id=session_id,
            account_kind=account_kind,
            username=username,
        ),
        "expires_in": 24 * 3600,
    }


def _register_desktop_relay_for_pairing(host: str, port: int) -> dict[str, Any] | None:
    enabled = (os.environ.get("XCAGI_RELAY_PAIRING_ENABLED") or "1").strip().lower()
    if enabled in {"0", "false", "off", "no"}:
        return None
    if not _host_is_private_or_loopback(host):
        return None
    try:
        from app.services.mobile_relay_desktop_client import register_desktop_relay

        relay = register_desktop_relay(host=host, port=port)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("desktop relay registration skipped: %s", exc)
        return None
    if not relay:
        return None
    public_relay = dict(relay)
    public_relay.pop("desktop_token", None)
    return public_relay


def _enrich_pairing_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    host = str(data.get("host") or "").strip()
    port = int(data.get("port") or 0)
    base_url = _pairing_api_base_url(host, port)
    code = str(data.get("shortCode") or data.get("code") or "").strip()
    nonce = str(data.get("nonce") or "").strip()
    data["api_base_url"] = base_url
    data["base_url"] = base_url
    if code:
        data["code"] = code
    data["deep_link"] = "xcagi://pairing?" + urlencode(
        {
            "code": code,
            "nonce": nonce,
            "host": host,
            "port": str(port),
            "api_base_url": base_url,
        }
    )
    data["qr_json"] = {
        "v": 2,
        "kind": "xcagi_pairing",
        "t": code,
        "code": code,
        "shortCode": code,
        "nonce": nonce,
        "host": host,
        "port": port,
        "api_base_url": base_url,
    }
    return data


@extension_router.post("/pairing/issue")
async def mobile_pairing_issue(body: PairingIssueBody, request: Request):
    """桌面或运维签发配对 QR 载荷（开发/内网）。"""
    host = _pairing_issue_host(body.host or (request.url.hostname or ""))
    port = _pairing_issue_port(request, int(body.port))
    payload = issue_pairing_nonce(host, port)
    data = _enrich_pairing_payload(payload)
    relay = _register_desktop_relay_for_pairing(host, port)
    if relay:
        relay_code = str(relay.get("pairing_code") or "").strip()
        data["relay"] = relay
        data["relay_id"] = relay.get("relay_id")
        data["relay_base_url"] = relay.get("relay_base_url")
        if relay_code:
            data["shortCode"] = relay_code
            data["code"] = relay_code
        relay_qr = dict(relay.get("qr_json") or {})
        relay_qr["lan_fallback"] = dict(data.get("qr_json") or {})
        data["qr_json"] = relay_qr
        data["deep_link"] = "xcagi://relay-pairing?" + urlencode(
            {
                "relay_id": str(relay.get("relay_id") or ""),
                "code": str(relay.get("pairing_code") or ""),
                "relay_base_url": str(relay.get("relay_base_url") or ""),
            }
        )
    return format_mobile_response(data=data)


@extension_router.post("/pairing/lookup")
async def mobile_pairing_lookup(body: PairingLookupBody):
    code = body.code.strip()
    rec = lookup_by_shortcode(code)
    if not rec:
        return JSONResponse(
            format_mobile_response(None, "配对码不存在或已过期", success=False, code=404),
            status_code=404,
        )
    return format_mobile_response(
        data=_enrich_pairing_payload(
            {
                "host": rec.get("host"),
                "port": rec.get("port"),
                "nonce": rec.get("nonce"),
                "shortCode": code,
                "exp": rec.get("exp") or 0,
            }
        ),
    )


@extension_router.post("/pairing/exchange")
async def mobile_pairing_exchange(body: PairingExchangeBody, user=Depends(get_mobile_user)):
    nonce = body.nonce.strip()
    code = body.code.strip()
    if not nonce and not code:
        return JSONResponse(
            format_mobile_response(None, "缺少配对码", success=False, code=400),
            status_code=400,
        )
    rec = consume_by_shortcode(code) if code else consume_pairing_nonce(nonce)
    if not rec:
        return JSONResponse(
            format_mobile_response(
                None, "配对码无效或已过期，请刷新二维码", success=False, code=400
            ),
            status_code=400,
        )
    user_public = _resolve_mobile_relay_user(user, prefer_admin=True)
    return format_mobile_response(
        data={
            **_enrich_pairing_payload(rec),
            **_relay_mobile_auth_payload(user_public),
            "hint": "已返回可保存的 api_base_url，手机端可直接绑定该设备。",
        }
    )


def _mobile_bridge_request_statuses() -> tuple[str, ...]:
    return ("pending", "processing", "resolved", "closed")


@extension_router.get("/service-bridge/requests")
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
        return format_mobile_response(data=paginate_list([r.to_dict() for r in items], total, page, per_page))


@extension_router.put("/service-bridge/requests/{request_id}/respond")
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
    if body.status not in _mobile_bridge_request_statuses():
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
    except RECOVERABLE_ERRORS as exc:
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


@extension_router.post("/relay/desktop/register")
async def mobile_relay_desktop_register(body: RelayDesktopRegisterBody):
    """Desktop runtime registers a long-lived cloud relay binding session."""
    try:
        data = MobileRelayService().register_desktop(
            label=body.label,
            device_id=body.device_id,
            capabilities=body.capabilities,
            relay_base_url=body.relay_base_url,
        )
        return format_mobile_response(data=data)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_relay_desktop_register")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/relay/mobile/confirm")
async def mobile_relay_confirm(body: RelayMobileConfirmBody, user=Depends(get_mobile_user)):
    try:
        user_public = _resolve_mobile_relay_user(user, prefer_admin=True)
        uid = int(user_public.get("id") or 0)
        username = str(user_public.get("username") or user_public.get("display_name") or "")
        desktop = MobileRelayService().confirm_mobile(
            user_id=uid,
            username=username,
            relay_id=body.relay_id,
            code=body.code,
        )
        if not desktop:
            return JSONResponse(
                format_mobile_response(None, "中继配对码无效或已过期", success=False, code=400),
                status_code=400,
            )
        return format_mobile_response(
            data={
                "desktop": desktop,
                "relay_id": desktop.get("relay_id"),
                **_relay_mobile_auth_payload(user_public, desktop),
            }
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_relay_confirm")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/relay/mobile/confirm-code")
async def mobile_relay_confirm_code(
    body: RelayMobileConfirmCodeBody,
    user=Depends(get_mobile_user),
):
    try:
        user_public = _resolve_mobile_relay_user(user, prefer_admin=True)
        uid = int(user_public.get("id") or 0)
        username = str(user_public.get("username") or user_public.get("display_name") or "")
        desktop = MobileRelayService().confirm_mobile_by_code(
            user_id=uid,
            username=username,
            code=body.code,
        )
        if not desktop:
            return JSONResponse(
                format_mobile_response(None, "设备码无效或已过期", success=False, code=400),
                status_code=400,
            )
        return format_mobile_response(
            data={
                "desktop": desktop,
                "relay_id": desktop.get("relay_id"),
                **_relay_mobile_auth_payload(user_public, desktop),
            }
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_relay_confirm_code")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.get("/relay/mobile/desktops")
async def mobile_relay_desktops(user=Depends(get_mobile_user)):
    uid, _ = _mobile_user_identity(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        items = MobileRelayService().list_desktops(user_id=uid)
        return format_mobile_response(data={"items": items, "count": len(items)})
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_relay_desktops")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/relay/tasks")
async def mobile_relay_create_task(body: RelayTaskCreateBody, user=Depends(get_mobile_user)):
    uid, _ = _mobile_user_identity(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        payload = dict(body.payload or {})
        payload.setdefault("user_id", uid)
        task = MobileRelayService().create_task(
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
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_relay_create_task")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.get("/relay/tasks/{task_id}")
async def mobile_relay_task_status(task_id: str, user=Depends(get_mobile_user)):
    uid, _ = _mobile_user_identity(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    task = MobileRelayService().get_task(user_id=uid, task_id=task_id)
    if not task:
        return JSONResponse(
            format_mobile_response(None, "任务不存在", success=False, code=404),
            status_code=404,
        )
    return format_mobile_response(data={"task": task})


@extension_router.post("/relay/desktop/poll")
async def mobile_relay_desktop_poll(body: RelayDesktopPollBody):
    try:
        data = MobileRelayService().poll_desktop(
            relay_id=body.relay_id,
            desktop_token=body.desktop_token,
            max_tasks=body.max_tasks,
        )
        if not data:
            return JSONResponse(
                format_mobile_response(None, "中继桌面凭证无效", success=False, code=404),
                status_code=404,
            )
        return format_mobile_response(data=data)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_relay_desktop_poll")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/relay/desktop/tasks/{task_id}/complete")
async def mobile_relay_desktop_complete(task_id: str, body: RelayDesktopCompleteBody):
    try:
        task = MobileRelayService().complete_desktop_task(
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
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_relay_desktop_complete")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


def _employee_text(employee: Any, key: str) -> str:
    if isinstance(employee, dict):
        return _compact_text(employee.get(key))
    return _compact_text(getattr(employee, key, ""))


def _workflow_employee_match_keys(mod_id: str, employee: Any) -> list[str]:
    keys = [
        mod_id,
        _employee_text(employee, "id"),
        _employee_text(employee, "label"),
        _employee_text(employee, "name"),
        _employee_text(employee, "panel_title"),
    ]
    out: list[str] = []
    seen: set[str] = set()
    for key in keys:
        normalized = key.strip().lower()
        if normalized and normalized not in seen:
            out.append(normalized)
            seen.add(normalized)
    return out


def _workflow_employee_to_dict(employee: Any) -> dict[str, Any]:
    if isinstance(employee, dict):
        return dict(employee)
    out: dict[str, Any] = {}
    for key in (
        "id",
        "label",
        "name",
        "panel_title",
        "panel_summary",
        "api_base_path",
        "phone_channel",
        "workflow_placeholder",
    ):
        value = getattr(employee, key, None)
        if value is not None:
            out[key] = value
    return out


def _enrich_workflow_employees(
    mod_id: str,
    employees: list[Any],
    market_profiles: dict[str, dict[str, Any]] | None = None,
    *,
    market_connected: bool = False,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for employee in employees:
        row = _workflow_employee_to_dict(employee)
        profile = None
        if market_profiles:
            for key in _workflow_employee_match_keys(mod_id, row):
                profile = market_profiles.get(key)
                if profile:
                    break
        _apply_market_profile(row, profile, market_connected=market_connected)
        enriched.append(row)
    return enriched


def _mobile_mod_items(
    market_profiles: dict[str, dict[str, Any]] | None = None,
    *,
    market_connected: bool = False,
) -> list[dict[str, Any]]:
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        items: list[dict[str, Any]] = []
        for m in get_mod_manager().list_all_mods() or []:
            if isinstance(m, dict):
                mid = str(m.get("id") or m.get("mod_id") or "").strip()
                name = str(m.get("name") or m.get("title") or mid).strip()
                employees = (
                    m.get("workflow_employees")
                    if isinstance(m.get("workflow_employees"), list)
                    else []
                )
                menu = m.get("frontend_menu") or m.get("menu") or m.get("menus")
                menu_overrides = m.get("menu_overrides")
                item = {
                    "id": mid,
                    "name": name,
                    "version": m.get("version") or "",
                    "author": m.get("author") or "",
                    "description": m.get("description") or "",
                    "primary": bool(m.get("primary")),
                    "industry": m.get("industry") if isinstance(m.get("industry"), dict) else {},
                    "frontend_menu": menu if isinstance(menu, list) else [],
                    "menu": menu if isinstance(menu, list) else [],
                    "menu_overrides": menu_overrides if isinstance(menu_overrides, list) else [],
                    "workflow_employees": _enrich_workflow_employees(
                        mid,
                        employees,
                        market_profiles,
                        market_connected=market_connected,
                    ),
                }
            else:
                mid = str(getattr(m, "id", None) or getattr(m, "mod_id", "") or "").strip()
                name = str(getattr(m, "name", None) or getattr(m, "title", None) or mid).strip()
                employees = getattr(m, "workflow_employees", [])
                if not isinstance(employees, list):
                    employees = []
                menu = getattr(m, "frontend_menu", [])
                menu_overrides = getattr(m, "frontend_menu_overrides", [])
                item = {
                    "id": mid,
                    "name": name,
                    "version": str(getattr(m, "version", "") or ""),
                    "author": str(getattr(m, "author", "") or ""),
                    "description": str(getattr(m, "description", "") or ""),
                    "primary": bool(getattr(m, "primary", False)),
                    "industry": getattr(m, "industry", {})
                    if isinstance(getattr(m, "industry", {}), dict)
                    else {},
                    "frontend_menu": menu if isinstance(menu, list) else [],
                    "menu": menu if isinstance(menu, list) else [],
                    "menu_overrides": menu_overrides if isinstance(menu_overrides, list) else [],
                    "workflow_employees": _enrich_workflow_employees(
                        mid,
                        employees,
                        market_profiles,
                        market_connected=market_connected,
                    ),
                }
            if mid:
                items.append(item)
        _upsert_admin_duty_mod_item(
            items,
            market_profiles,
            market_connected=market_connected,
        )
        return items[:100]
    except OPERATIONAL_ERRORS as exc:
        logger.warning("mobile mods list: %s", exc)
        items: list[dict[str, Any]] = []
        _upsert_admin_duty_mod_item(
            items,
            market_profiles,
            market_connected=market_connected,
        )
        return items


ADMIN_MOBILE_FEATURES: list[dict[str, str]] = [
    {
        "id": "admin-status",
        "title": "管理驾驶舱",
        "description": "查看管理端运行状态、市场服务和关键健康指标。",
        "category": "overview",
        "method": "GET",
        "api_path": "/api/admin/status",
    },
    {
        "id": "admin-catalog",
        "title": "能力包目录",
        "description": "维护 MOD 与员工包上架、删除和目录同步。",
        "category": "catalog",
        "method": "GET",
        "api_path": "/api/admin/catalog",
    },
    {
        "id": "admin-duty-employees",
        "title": "值班员工池",
        "description": "查看管理端内部 duty AI 员工和岗位分区。",
        "category": "employees",
        "method": "GET",
        "api_path": "/api/mobile/v1/admin/employees",
    },
    {
        "id": "admin-duty-graph",
        "title": "值班拓扑",
        "description": "检查员工密钥、执行拓扑和 duty graph 健康状态。",
        "category": "employees",
        "method": "GET",
        "api_path": "/api/admin/duty-graph/health",
    },
    {
        "id": "admin-execution-capability",
        "title": "执行能力矩阵",
        "description": "汇总 AI 员工的执行能力、工具权限和运行边界。",
        "category": "employees",
        "method": "POST",
        "api_path": "/api/admin/employees/execution-capabilities",
    },
    {
        "id": "admin-autonomy-dashboard",
        "title": "自治任务看板",
        "description": "查看员工自治建议、简报任务和最近调度结果。",
        "category": "automation",
        "method": "GET",
        "api_path": "/api/admin/employee-autonomy/dashboard",
    },
    {
        "id": "admin-autonomy-suggestions",
        "title": "自治建议审核",
        "description": "审核员工提出的自动化建议和派发结果。",
        "category": "automation",
        "method": "GET",
        "api_path": "/api/admin/employee-autonomy/suggestions",
    },
    {
        "id": "admin-change-requests",
        "title": "变更请求",
        "description": "审批管理端变更请求并追踪执行状态。",
        "category": "governance",
        "method": "GET",
        "api_path": "/api/admin/change-requests",
    },
    {
        "id": "admin-ai-accounts",
        "title": "AI 账号池",
        "description": "管理模型账号、密钥轮换和可用性标记。",
        "category": "accounts",
        "method": "GET",
        "api_path": "/api/admin/ai-accounts",
    },
    {
        "id": "admin-users",
        "title": "用户与企业授权",
        "description": "管理用户、企业标记、管理员权限与可分配 MOD。",
        "category": "users",
        "method": "GET",
        "api_path": "/api/admin/users",
    },
    {
        "id": "admin-user-mods",
        "title": "企业 MOD 授权",
        "description": "查看和调整企业用户可用的 MOD 与能力包。",
        "category": "users",
        "method": "GET",
        "api_path": "/api/admin/users/{user_id}/mods",
    },
    {
        "id": "admin-wallets",
        "title": "钱包与交易",
        "description": "查看钱包余额、交易流水和账单核对状态。",
        "category": "billing",
        "method": "GET",
        "api_path": "/api/admin/wallets",
    },
    {
        "id": "admin-action-items",
        "title": "运维待办",
        "description": "跟踪管理端待办、Digest 事项和处理统计。",
        "category": "ops",
        "method": "GET",
        "api_path": "/api/admin/action-items",
    },
    {
        "id": "admin-ops-audit",
        "title": "操作审计",
        "description": "查看管理端关键操作、审批令牌和 staged changes。",
        "category": "ops",
        "method": "GET",
        "api_path": "/api/admin/ops/audit",
    },
]


def _mobile_session_meta(request: Request) -> dict[str, Any]:
    from app.application.session_account_meta import load_session_account_meta
    from app.infrastructure.auth.dependencies import session_id_from_request
    from app.security.mobile_jwt import verify_mobile_jwt

    sid = ""
    jwt_meta: dict[str, Any] = {}
    authorization = request.headers.get("Authorization") or ""
    if authorization.startswith("Bearer "):
        payload = verify_mobile_jwt(authorization[7:].strip())
        if payload:
            sid = str(payload.get("session_id") or "").strip()
            account_kind = str(payload.get("account_kind") or "").strip()
            jwt_meta = {
                "session_id": sid,
                "account_kind": account_kind,
                "market_is_admin": account_kind == "admin",
                "username": str(payload.get("username") or "").strip(),
            }
    if not sid:
        try:
            sid = session_id_from_request(request)
        except (AttributeError, TypeError):
            # Keep direct service-level callers and compatibility shims usable;
            # a real Starlette Request always exposes cookies.
            sid = ""
    if sid:
        meta = load_session_account_meta(sid)
        if meta:
            return meta
    return jwt_meta


def _require_mobile_admin(
    request: Request, user: Any
) -> tuple[dict[str, Any], JSONResponse | None]:
    if user is None:
        return {}, JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    meta = _mobile_session_meta(request) or {}
    role = str(getattr(user, "role", "") or "").strip()
    jwt_or_session_admin = meta.get("account_kind") == "admin" and (
        bool(meta.get("market_is_admin")) or role in {"admin", "super_admin", "owner"}
    )
    if not jwt_or_session_admin:
        return meta, JSONResponse(
            format_mobile_response(None, "需要管理端管理员账号", success=False, code=403),
            status_code=403,
        )
    return meta, None


def _require_mobile_admin_or_enterprise(
    request: Request, user: Any
) -> tuple[dict[str, Any], JSONResponse | None]:
    """企业端 + 管理端都可访问的 Codex 超级员工专用鉴权。"""
    if user is None:
        return {}, JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    meta = _mobile_session_meta(request) or {}
    role = str(getattr(user, "role", "") or "").strip().lower()
    account_kind = str(meta.get("account_kind") or "").strip().lower()
    if not account_kind:
        account_kind = "enterprise" if role == "enterprise" else "personal"
    if account_kind == "enterprise":
        return meta, None
    if account_kind in {"admin", "admin_portal"} and (
        bool(meta.get("market_is_admin")) or role in {"admin", "admin_portal", "super_admin", "owner"}
    ):
        return meta, None
    return meta, JSONResponse(
        format_mobile_response(None, "需要管理端管理员账号", success=False, code=403),
        status_code=403,
    )


def _mobile_request_user_id(request: Request, user: Any) -> int:
    authorization = request.headers.get("Authorization") or ""
    if authorization.startswith("Bearer "):
        try:
            from app.security.mobile_jwt import user_id_from_mobile_bearer

            uid = user_id_from_mobile_bearer(authorization)
            if uid:
                return int(uid)
        except (ImportError, ValueError, TypeError):
            pass
    for attr in ("id", "user_id"):
        try:
            uid = getattr(user, attr, None)
        except (AttributeError, TypeError):
            continue
        try:
            uid_int = int(uid or 0)
        except (TypeError, ValueError):
            uid_int = 0
        if uid_int > 0:
            return uid_int
    return 0


def _candidate_duty_registry_paths() -> list[Path]:
    roots: list[Path] = []
    env_root = os.environ.get("MODSTORE_DEPLOY_ROOT", "").strip()
    if env_root:
        roots.append(Path(env_root))
    here = Path(__file__).resolve()
    roots.extend(
        [
            here.parents[3] / "成都修茈科技有限公司" / "MODstore_deploy",
            Path.cwd() / "成都修茈科技有限公司" / "MODstore_deploy",
        ]
    )
    out: list[Path] = []
    for root in roots:
        out.append(root / "modstore_server" / "catalog_data" / "duty_employee_registry.json")
    return out


def _load_admin_duty_records() -> list[dict[str, Any]]:
    for path in _candidate_duty_registry_paths():
        try:
            if not path.is_file():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            packages = raw.get("packages") if isinstance(raw, dict) else []
            if isinstance(packages, list):
                return [p for p in packages if isinstance(p, dict)]
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("mobile admin duty registry read failed: %s", exc)
    return []


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _market_profile_text(profile: dict[str, Any], key: str) -> str:
    return _compact_text(profile.get(key))


def _market_profile_keys(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for key in ("pkg_id", "id", "name"):
        value = _compact_text(row.get(key))
        if value:
            keys.append(value.lower())
    return keys


def _admin_employee_match_keys(raw: dict[str, Any], employee_id: str, name: str) -> list[str]:
    keys = [employee_id, name]
    stored = _compact_text(raw.get("stored_filename"))
    if stored:
        keys.append(stored)
        base = stored.removesuffix(".xcemp")
        keys.append(base)
        parts = base.rsplit("-", 1)
        if len(parts) == 2 and parts[1][:1].isdigit():
            keys.append(parts[0])
    out: list[str] = []
    seen: set[str] = set()
    for key in keys:
        normalized = key.strip().lower()
        if normalized and normalized not in seen:
            out.append(normalized)
            seen.add(normalized)
    return out


def _index_market_ai_employee_profiles(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in items:
        if not isinstance(row, dict):
            continue
        material = _compact_text(row.get("material_category")).lower()
        artifact = _compact_text(row.get("artifact")).lower()
        if material and material != "ai_employee":
            continue
        if artifact and artifact not in {"mod", "employee_pack", "ai_employee"}:
            continue
        for key in _market_profile_keys(row):
            out.setdefault(key, row)
    return out


async def _load_market_ai_employee_profile_index() -> tuple[dict[str, dict[str, Any]], bool, str]:
    now = time.monotonic()
    ttl = float(os.environ.get("XCAGI_MOBILE_MARKET_PROFILE_CACHE_TTL", "300") or 300)
    cached_profiles = _MARKET_AI_EMPLOYEE_CACHE.get("profiles")
    if (
        isinstance(cached_profiles, dict)
        and cached_profiles
        and now < float(_MARKET_AI_EMPLOYEE_CACHE.get("expires_at") or 0)
    ):
        return (
            cached_profiles,
            bool(_MARKET_AI_EMPLOYEE_CACHE.get("connected")),
            str(_MARKET_AI_EMPLOYEE_CACHE.get("error") or ""),
        )

    try:
        import httpx

        from app.infrastructure.mods.catalog_client import market_catalog_list_url

        timeout = float(os.environ.get("XCAGI_MOBILE_MARKET_PROFILE_TIMEOUT", "6") or 6)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                market_catalog_list_url(),
                params={"material_category": "ai_employee", "limit": 200, "offset": 0},
            )
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("items") if isinstance(payload, dict) else []
        profiles = _index_market_ai_employee_profiles(items if isinstance(items, list) else [])
        _MARKET_AI_EMPLOYEE_CACHE.update(
            {
                "expires_at": now + ttl,
                "profiles": profiles,
                "connected": True,
                "error": "",
            }
        )
        return profiles, True, ""
    except Exception as exc:  # noqa: BLE001  # pragma: no cover - network availability is environment-specific
        error = _compact_text(exc)
        if isinstance(cached_profiles, dict) and cached_profiles:
            _MARKET_AI_EMPLOYEE_CACHE.update(
                {
                    "expires_at": now + min(ttl, 60),
                    "connected": False,
                    "error": error,
                }
            )
            return cached_profiles, False, error
        _MARKET_AI_EMPLOYEE_CACHE.update(
            {
                "expires_at": now + min(ttl, 60),
                "profiles": {},
                "connected": False,
                "error": error,
            }
        )
        return {}, False, error


def _apply_market_profile(
    item: dict[str, Any],
    profile: dict[str, Any] | None,
    *,
    market_connected: bool,
) -> None:
    if not profile:
        item.update(
            {
                "profile_source": "admin",
                "market_connected": False,
                "market_pkg_id": "",
                "market_name": "",
                "market_description": "",
                "market_version": "",
                "market_author": "",
                "market_industry": "",
                "market_material_category": "",
                "market_license_scope": "",
                "market_security_level": "",
            }
        )
        return
    item.update(
        {
            "profile_source": "ai_market",
            "market_connected": bool(market_connected),
            "market_pkg_id": _market_profile_text(profile, "pkg_id")
            or _market_profile_text(profile, "id"),
            "market_name": _market_profile_text(profile, "name"),
            "market_description": _market_profile_text(profile, "description"),
            "market_version": _market_profile_text(profile, "version"),
            "market_author": _market_profile_text(profile, "author")
            or _market_profile_text(profile, "publisher")
            or _market_profile_text(profile, "author_id"),
            "market_industry": _market_profile_text(profile, "industry"),
            "market_material_category": _market_profile_text(profile, "material_category"),
            "market_license_scope": _market_profile_text(profile, "license_scope"),
            "market_security_level": _market_profile_text(profile, "security_level"),
        }
    )


def _admin_employee_items(
    market_profiles: dict[str, dict[str, Any]] | None = None,
    *,
    market_connected: bool = False,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in _load_admin_duty_records():
        employee_id = str(raw.get("id") or raw.get("pkg_id") or "").strip()
        if not employee_id:
            continue
        name = _compact_text(raw.get("name") or employee_id)
        area = _compact_text(raw.get("yuangon_area") or raw.get("industry"))
        item = {
            "id": employee_id,
            "name": name,
            "label": name,
            "title": name,
            "panel_title": name,
            "description": _compact_text(raw.get("description")),
            "panel_summary": _compact_text(raw.get("description")),
            "version": str(raw.get("version") or "").strip(),
            "industry": _compact_text(raw.get("industry")),
            "yuangon_area": area,
            "employee_scope": _compact_text(raw.get("employee_scope") or "duty"),
            "employee_source": _compact_text(raw.get("employee_source") or "duty_roster"),
            "is_duty_employee": bool(raw.get("is_duty_employee", True)),
            "is_store_employee": bool(raw.get("is_store_employee", False)),
            "status": "on_duty",
            "api_base_path": f"/api/admin/employees/{employee_id}",
            "phone_channel": "admin-duty",
            "workflow_placeholder": False,
            "stored_filename": _compact_text(raw.get("stored_filename")),
            "file_size": raw.get("file_size") or 0,
        }
        profile = None
        if market_profiles:
            for key in _admin_employee_match_keys(raw, employee_id, name):
                profile = market_profiles.get(key)
                if profile:
                    break
        _apply_market_profile(item, profile, market_connected=market_connected)
        items.append(item)
    return sorted(items, key=lambda item: str(item.get("id") or ""))


def _admin_duty_mod_item(
    market_profiles: dict[str, dict[str, Any]] | None = None,
    *,
    market_connected: bool = False,
) -> dict[str, Any] | None:
    employees = _admin_employee_items(market_profiles, market_connected=market_connected)
    if not employees:
        return None
    return {
        "id": "admin-duty-employees",
        "name": "管理端编制员工",
        "version": "local",
        "author": "XCAGI 管理端",
        "description": f"{len(employees)} 位管理端编制 AI 员工，来自本机 duty registry。",
        "primary": True,
        "industry": {"id": "admin", "name": "管理端"},
        "frontend_menu": [],
        "menu": [],
        "menu_overrides": [],
        "workflow_employees": employees,
    }


def _upsert_admin_duty_mod_item(
    items: list[dict[str, Any]],
    market_profiles: dict[str, dict[str, Any]] | None = None,
    *,
    market_connected: bool = False,
) -> None:
    duty_mod = _admin_duty_mod_item(market_profiles, market_connected=market_connected)
    if not duty_mod:
        return
    duty_id = str(duty_mod.get("id") or "")
    for item in items:
        if str(item.get("id") or "") != duty_id:
            continue
        if not item.get("workflow_employees"):
            item["workflow_employees"] = duty_mod["workflow_employees"]
        return
    items.insert(0, duty_mod)


@extension_router.get("/admin/employees")
async def mobile_admin_employees(request: Request, user=Depends(get_mobile_user)):
    _, err = _require_mobile_admin(request, user)
    if err is not None:
        return err
    market_profiles, market_connected, market_error = await _load_market_ai_employee_profile_index()
    items = _admin_employee_items(market_profiles, market_connected=market_connected)
    return format_mobile_response(
        data={
            "items": items,
            "count": len(items),
            "market_connected": market_connected,
            "market_profile_count": len(market_profiles),
            "market_error": market_error,
        }
    )


@extension_router.get("/admin/features")
async def mobile_admin_features(request: Request, user=Depends(get_mobile_user)):
    _, err = _require_mobile_admin(request, user)
    if err is not None:
        return err
    return format_mobile_response(
        data={"items": ADMIN_MOBILE_FEATURES, "count": len(ADMIN_MOBILE_FEATURES)}
    )


@extension_router.get("/admin/home")
async def mobile_admin_home(request: Request, user=Depends(get_mobile_user)):
    meta, err = _require_mobile_admin(request, user)
    if err is not None:
        return err
    market_profiles, market_connected, market_error = await _load_market_ai_employee_profile_index()
    employees = _admin_employee_items(market_profiles, market_connected=market_connected)
    return format_mobile_response(
        data={
            "account_kind": meta.get("account_kind") or "admin",
            "employees": employees,
            "employee_count": len(employees),
            "features": ADMIN_MOBILE_FEATURES,
            "feature_count": len(ADMIN_MOBILE_FEATURES),
            "market_connected": market_connected,
            "market_profile_count": len(market_profiles),
            "market_error": market_error,
        }
    )


@extension_router.get("/admin/codex-super-employee/messages")
async def mobile_admin_codex_super_employee_messages(
    request: Request,
    limit: int = Query(default=80, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的 Codex 超级员工对话记录。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        messages = CodexSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return format_mobile_response(data={"messages": messages})
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_admin_codex_super_employee_messages")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/admin/codex-super-employee/messages")
async def mobile_admin_codex_super_employee_invoke(
    request: Request,
    body: CodexSuperEmployeeMobileMessageBody,
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的软件内 Codex 调用入口。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    text = (body.message or body.body or "").strip()
    context = dict(body.context or {})
    context.setdefault("source", "mobile_im")
    context.setdefault("client_surface", "mobile")
    context.setdefault("target_devices", ["all"])
    try:
        result = CodexSuperEmployeeService().invoke(
            user_id=uid,
            message=text,
            context=context,
        )
        return format_mobile_response(data=result)
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400),
            status_code=400,
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_admin_codex_super_employee_invoke")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.get("/mods")
async def mobile_mods_summary(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    market_profiles, market_connected, market_error = await _load_market_ai_employee_profile_index()
    return format_mobile_response(
        data={
            "items": _mobile_mod_items(market_profiles, market_connected=market_connected),
            "market_connected": market_connected,
            "market_profile_count": len(market_profiles),
            "market_error": market_error,
        }
    )


@extension_router.get("/platform-shell")
async def mobile_platform_shell(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    installed = [m["id"] for m in _mobile_mod_items()]
    from app.mod_sdk.platform_shell import build_platform_shell_payload

    return format_mobile_response(data=build_platform_shell_payload(installed))


@extension_router.get("/home")
async def mobile_home(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    market_profiles, market_connected, market_error = await _load_market_ai_employee_profile_index()
    mod_items = _mobile_mod_items(market_profiles, market_connected=market_connected)
    installed = [m["id"] for m in mod_items]
    from app.mod_sdk.platform_shell import build_platform_shell_payload

    sync_data: dict[str, Any] = {}
    try:
        from app.db.xcmax_sync import SyncDb

        sync_data = SyncDb().get_status()
    except OPERATIONAL_ERRORS as exc:
        sync_data = {"error": str(exc)}
    return format_mobile_response(
        data={
            "mods": mod_items,
            "market_connected": market_connected,
            "market_profile_count": len(market_profiles),
            "market_error": market_error,
            "platform_shell": build_platform_shell_payload(installed),
            "sync": sync_data,
        },
    )


class SyncPullBody(BaseModel):
    since_cursor: int = Field(default=0, ge=0)


class SyncPushItem(BaseModel):
    entity_type: str = Field(..., min_length=1, max_length=64)
    entity_id: str = Field(..., min_length=1, max_length=128)
    operation: str = Field(default="update", max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)


class SyncPushBody(BaseModel):
    items: list[SyncPushItem] = Field(default_factory=list)


class SyncAckBody(BaseModel):
    cursor: int = Field(default=0, ge=0)


def _approval_items(limit: int = 100) -> list[dict[str, Any]]:
    from app.db.models.approval import ApprovalRequest
    from app.db.session import get_db

    with get_db() as db:
        rows = (
            db.query(ApprovalRequest).order_by(ApprovalRequest.created_at.desc()).limit(limit).all()
        )
        return [
            {
                "id": r.id,
                "title": r.title,
                "status": r.status,
                "request_no": r.request_no,
            }
            for r in rows
        ]


def _shipment_items(limit: int = 100) -> list[dict[str, Any]]:
    from app.db.models.shipment import ShipmentRecord
    from app.db.session import get_db

    with get_db() as db:
        rows = db.query(ShipmentRecord).order_by(ShipmentRecord.id.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "order_number": getattr(r, "order_number", None) or getattr(r, "shipment_no", None),
                "status": getattr(r, "status", None),
            }
            for r in rows
        ]


def _ai_conversation_changes(user: Any, limit: int = 100) -> list[dict[str, Any]]:
    """查询当前用户最近的 AI 对话消息，供移动端增量同步。"""
    uid = int(getattr(user, "id", 0) or 0)
    if uid <= 0:
        return []
    try:
        from app.db.models.ai import AIConversation, AIConversationSession
        from app.db.session import get_db

        with get_db() as db:
            rows = (
                db.query(AIConversation)
                .join(
                    AIConversationSession,
                    AIConversation.session_id == AIConversationSession.session_id,
                )
                .filter(AIConversationSession.user_id == uid)
                .order_by(AIConversation.id.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "session_id": r.session_id,
                    "role": r.role,
                    "content": r.content,
                    "intent": r.intent or "",
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in reversed(rows)
            ]
    except OPERATIONAL_ERRORS as exc:
        logger.warning("ai_conversation_changes: %s", exc)
        return []


@extension_router.get("/sync/status")
async def mobile_sync_status(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.db.xcmax_sync import SyncDb, _ensure_schema, _get_conn

        db = SyncDb()
        st = dict(db.get_status())
        with _get_conn() as conn:
            _ensure_schema(conn)
            st["inbox_pending"] = conn.execute(
                "SELECT COUNT(*) FROM sync_inbox WHERE status='pending'",
            ).fetchone()[0]
    except OPERATIONAL_ERRORS as exc:
        st = {"error": str(exc), "healthy": False}
    return format_mobile_response(data=st)


@extension_router.post("/sync/pull")
async def mobile_sync_pull(body: SyncPullBody, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.db.xcmax_sync import SyncDb

        sync_db = SyncDb()
        changes = sync_db.get_changes(since_cursor=body.since_cursor, limit=200)
        cursor = sync_db.get_status().get("local_cursor") or body.since_cursor
        if cursor:
            sync_db.update_remote_cursor(int(cursor))
        im_entity_types = {"im_message", "im_read_state"}
        im_changes = [c for c in changes if str(c.get("entity_type") or "") in im_entity_types]
        ai_changes = _ai_conversation_changes(user, limit=100)
        return format_mobile_response(
            data={
                "cursor": cursor,
                "changes": changes,
                "im_changes": im_changes,
                "im_change_count": len(im_changes),
                "ai_changes": ai_changes,
                "ai_change_count": len(ai_changes),
                "approvals": _approval_items(),
                "shipments": _shipment_items(),
            },
        )
    except OPERATIONAL_ERRORS as exc:
        logger.warning("mobile_sync_pull: %s", exc)
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/sync/push")
async def mobile_sync_push(body: SyncPushBody, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    actor = getattr(user, "username", None) or f"user-{getattr(user, 'id', 0)}"
    written = 0
    try:
        from app.db.xcmax_sync import SyncDb

        sync_db = SyncDb()
        for item in body.items[:50]:
            sync_db.append_change(
                item.entity_type,
                item.entity_id,
                item.operation,
                item.payload,
                actor=actor,
                origin_node="mobile",
            )
            written += 1
        apply_result: dict[str, Any] = {}
        try:
            from app.application.xcmax_sync_app import apply_inbox

            apply_result = apply_inbox(limit=written + 50) or {}
        except OPERATIONAL_ERRORS as ae:
            apply_result = {"error": str(ae)}
        return format_mobile_response(data={"written": written, "apply": apply_result})
    except OPERATIONAL_ERRORS as exc:
        logger.warning("mobile_sync_push: %s", exc)
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/sync/ack")
async def mobile_sync_ack(body: SyncAckBody, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.db.xcmax_sync import SyncDb

        sync_db = SyncDb()
        sync_db.update_remote_cursor(int(body.cursor))
        return format_mobile_response(data={"acked": int(body.cursor)})
    except OPERATIONAL_ERRORS as exc:
        logger.warning("mobile_sync_ack: %s", exc)
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.get("/sync/conflicts")
async def mobile_sync_conflicts(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    items: list[dict[str, Any]] = []
    try:
        from app.db.xcmax_sync import _ensure_schema, _get_conn

        with _get_conn() as conn:
            _ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT id, entity_type, entity_id, conflict_note, received_at
                FROM sync_inbox WHERE status='conflict' ORDER BY id DESC LIMIT 50
                """,
            ).fetchall()
            items = [dict(r) for r in rows]
    except OPERATIONAL_ERRORS as exc:
        return format_mobile_response(data={"items": [], "error": str(exc)})
    return format_mobile_response(data={"items": items})


class AuthQrConfirmBody(BaseModel):
    qr_id: str = Field(..., min_length=8)
    username: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=256)
    account_kind: str = Field(default="enterprise", max_length=32)


@extension_router.post("/auth/qr/confirm")
async def mobile_auth_qr_confirm(body: AuthQrConfirmBody, request: Request):
    """手机确认 PC 扫码登录。"""
    from app.application.auth_app_service import get_auth_app_service
    from app.application.enterprise_login_flow import run_market_first_login
    from app.application.session_account_meta import normalize_account_kind
    from app.fastapi_routes.domains.auth.routes import (
        _jit_create_local_user_for_enterprise,
        _market_user_email_from_raw,
    )
    from app.fastapi_routes.market_account import login_market_with_password
    from app.mod_sdk.product_skus import resolve_product_sku
    from app.security.auth_qr_login import confirm_auth_qr, get_auth_qr

    rec = get_auth_qr(body.qr_id)
    if not rec or rec.get("status") == "expired":
        return JSONResponse(
            format_mobile_response(None, "二维码已过期", success=False, code=400),
            status_code=400,
        )

    username = (body.username or "").strip()
    password = body.password or ""
    auth_app_service = get_auth_app_service()
    sku = resolve_product_sku()
    fields_set = getattr(body, "model_fields_set", getattr(body, "__fields_set__", set()))
    qr_account_kind = str(rec.get("account_kind") or "").strip()
    body_account_kind = body.account_kind if "account_kind" in fields_set else qr_account_kind
    account_kind = normalize_account_kind(
        body_account_kind,
        default=qr_account_kind or ("enterprise" if sku == "enterprise" else "personal"),
    )

    authorization = request.headers.get("Authorization") or ""
    if authorization.startswith("Bearer ") and not username:
        from app.security.mobile_jwt import user_id_from_mobile_bearer

        uid = user_id_from_mobile_bearer(authorization)
        if uid:
            from app.db.models.user import User
            from app.db.session import get_db

            with get_db() as db:
                row = db.query(User).filter(User.id == int(uid)).first()
                if row:
                    username = str(row.username or "")

    if not username or not password:
        return JSONResponse(
            format_mobile_response(None, "请提供账号与密码确认登录", success=False, code=400),
            status_code=400,
        )

    result, err = await run_market_first_login(
        username=username,
        password=password,
        account_kind=account_kind,
        market_result=None,
        auth_app_service=auth_app_service,
        sku=sku,
        jit_create_fn=_jit_create_local_user_for_enterprise,
        market_user_email_from_raw=_market_user_email_from_raw,
        login_market_fn=login_market_with_password,
    )
    if err:
        msg = "登录失败"
        if hasattr(err, "body") and err.body:
            try:
                import json

                msg = json.loads(err.body.decode("utf-8")).get("message") or msg
            except OPERATIONAL_ERRORS:
                pass
        return JSONResponse(
            format_mobile_response(None, msg, success=False, code=401),
            status_code=401,
        )
    session_id = str((result or {}).get("session_id") or "")
    if not session_id:
        return JSONResponse(
            format_mobile_response(None, "会话创建失败", success=False, code=500),
            status_code=500,
        )
    ok = confirm_auth_qr(body.qr_id.strip(), session_id=session_id, login_payload=result or {})
    if not ok:
        return JSONResponse(
            format_mobile_response(None, "二维码无效", success=False, code=400),
            status_code=400,
        )
    return format_mobile_response(data={"confirmed": True, "qr_id": body.qr_id.strip()})


class OidcExchangeBody(BaseModel):
    code: str = Field(..., min_length=4)
    state: str = Field(..., min_length=8)


@extension_router.post("/auth/oidc/exchange")
async def mobile_auth_oidc_exchange(body: OidcExchangeBody):
    """Android Custom Tabs OIDC 回调换 mobile JWT。"""
    from app.application.auth_app_service import get_auth_app_service
    from app.application.enterprise_login_flow import finalize_enterprise_login
    from app.application.session_account_meta import normalize_account_kind
    from app.infrastructure.auth.oidc_provider import exchange_code_for_userinfo, verify_oidc_state
    from app.mod_sdk.product_skus import resolve_product_sku
    from app.security.mobile_jwt import issue_mobile_tokens

    ok, _rt = verify_oidc_state(body.state)
    if not ok:
        return JSONResponse(
            format_mobile_response(None, "OIDC state 无效", success=False, code=400),
            status_code=400,
        )
    try:
        profile = await exchange_code_for_userinfo(body.code)
    except OPERATIONAL_ERRORS as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=502),
            status_code=502,
        )
    auth_app_service = get_auth_app_service()
    auth_result = auth_app_service.authenticate_oidc_user(profile)
    if not auth_result.get("success"):
        return JSONResponse(
            format_mobile_response(
                None,
                str(auth_result.get("message") or "OIDC 登录失败"),
                success=False,
                code=401,
            ),
            status_code=401,
        )
    sku = resolve_product_sku()
    account_kind = normalize_account_kind(
        None, default="enterprise" if sku == "enterprise" else "personal"
    )
    username = str((auth_result.get("user") or {}).get("username") or "")
    session_id = auth_result.get("session_id")
    payload = await finalize_enterprise_login(
        result=auth_result,
        session_id=str(session_id) if session_id else None,
        market_result={"success": False},
        account_kind=account_kind,
        username=username,
        sku=sku,
        skip_market_sync=True,
    )
    user_raw = payload.get("user") or {}
    tokens = issue_mobile_tokens(
        user_id=int(user_raw["id"]),
        session_id=str(session_id),
        account_kind=str(payload.get("account_kind") or account_kind),
        username=username,
    )
    return format_mobile_response(
        data={
            "user": user_raw,
            "session_id": session_id,
            "account_kind": payload.get("account_kind") or account_kind,
            **tokens,
        },
    )


# ── 专属客服接口（企业版手机端） ──


def _mobile_cs_source_id(user: Any) -> str:
    uid = _safe_user_id(user)
    return f"mobile:{uid or 'anonymous'}"


def _mobile_cs_source_name(user: Any) -> str:
    display = (
        _safe_user_text(user, "display_name") or _safe_user_text(user, "username") or "移动端用户"
    )
    return f"手机端 {display}"


def _safe_user_id(user: Any) -> int:
    try:
        raw = getattr(user, "id", None)
        return int(raw or 0)
    except (AttributeError, TypeError, ValueError):
        pass
    raw = getattr(user, "__dict__", {}).get("id")
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    try:
        from sqlalchemy import inspect as sa_inspect

        identity = sa_inspect(user).identity or ()
        return int(identity[0]) if identity else 0
    except Exception:  # noqa: BLE001
        return 0


def _safe_user_text(user: Any, key: str) -> str:
    try:
        return str(getattr(user, key, "") or "").strip()
    except (AttributeError, TypeError):
        return str(getattr(user, "__dict__", {}).get(key) or "").strip()


def _coerce_user_cs_reply(result: dict[str, Any], fallback: str) -> str:
    data = result.get("data") if isinstance(result, dict) else None
    if isinstance(data, dict):
        error = str(data.get("error") or "").strip()
        if data.get("ok") is False or error:
            logger.info("user-cs employee returned non-fatal error for mobile cs: %s", error[:200])
            return fallback
        items = data.get("items")
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                for key in ("message_text", "reply", "answer", "summary"):
                    val = str(first.get(key) or "").strip()
                    if val:
                        return val
            elif isinstance(first, str) and first.strip():
                return first.strip()
        summary = str(data.get("summary") or "").strip()
        if summary:
            return summary
    error = str((result or {}).get("error") or "").strip() if isinstance(result, dict) else ""
    if error:
        logger.info("user-cs employee failed for mobile cs: %s", error[:200])
    return fallback


def _service_request_to_cs_messages(row: Any) -> list[dict[str, Any]]:
    created = row.created_at.isoformat() if getattr(row, "created_at", None) else ""
    updated = row.updated_at.isoformat() if getattr(row, "updated_at", None) else created
    messages = [
        {
            "message_id": f"sr_{row.id}_user",
            "sender": "user",
            "body": row.description or row.title or "",
            "timestamp": created,
            "msg_type": "text",
        }
    ]
    extra: dict[str, Any] = {}
    if row.extra_data:
        try:
            raw = json.loads(row.extra_data)
            if isinstance(raw, dict):
                extra = raw
        except (TypeError, json.JSONDecodeError):
            extra = {}
    reply = str(extra.get("ai_reply") or row.response or "").strip()
    if reply:
        messages.append(
            {
                "message_id": f"sr_{row.id}_cs",
                "sender": "cs",
                "body": reply,
                "timestamp": updated,
                "msg_type": "text",
            }
        )
    return messages


def _persist_mobile_cs_request(
    user: Any,
    *,
    message_id: str,
    msg_body: str,
    reply: str,
    backend: str,
    employee_result: dict[str, Any],
) -> tuple[int, bool, str]:
    from app.db.models.service_request import ServiceRequest
    from app.db.session import get_db

    username = _safe_user_text(user, "username")
    extra = {
        "message_id": message_id,
        "mobile_user_id": _safe_user_id(user),
        "username": username,
        "ai_reply": reply,
        "backend": backend,
        "employee_result": employee_result,
    }
    try:
        with get_db() as db:
            ServiceRequest.__table__.create(db.get_bind(), checkfirst=True)
            row = ServiceRequest(
                source_instance_id=_mobile_cs_source_id(user),
                source_instance_name=_mobile_cs_source_name(user),
                request_type="mobile_ai_customer_service",
                title=msg_body[:80] or "小C助理咨询",
                description=msg_body,
                priority="normal",
                status="pending",
                extra_data=json.dumps(extra, ensure_ascii=False),
            )
            db.add(row)
            db.flush()
            return int(row.id), True, ""
    except OPERATIONAL_ERRORS as exc:
        logger.warning("mobile cs service request persist skipped: %s", exc)
        return 0, False, str(exc)[:300]


@extension_router.get("/cs/info")
async def get_cs_info(request: Request, user=Depends(get_mobile_user)):
    """返回当前用户的小C/智能客服信息。"""
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.services.user_cs_employee_runner import EMPLOYEE_MOD_ID

    return format_mobile_response(
        data={
            "cs_available": True,
            "cs_name": "小C助理",
            "cs_avatar": None,
            "cs_online": True,
            "backend": EMPLOYEE_MOD_ID,
        }
    )


@extension_router.post("/cs/messages")
async def post_cs_message(request: Request, body: dict, user=Depends(get_mobile_user)):
    """发送消息到企业桌面端同源智能客服通道。"""
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    msg_body = str(body.get("body", "") or "").strip()
    if not msg_body:
        return JSONResponse(
            format_mobile_response(None, "消息不能为空", success=False, code=400),
            status_code=400,
        )
    from app.services.user_cs_employee_runner import EMPLOYEE_MOD_ID, run_user_cs_employee

    message_id = f"cs_{uuid.uuid4().hex[:12]}"
    username = _safe_user_text(user, "username")
    display = _safe_user_text(user, "display_name") or username
    fallback_reply = (
        "我已收到，会同步到企业智能客服工作台继续跟进。"
        "你也可以补充业务背景、目标客户、期望交付时间，我会一起整理给客服侧。"
    )
    employee_result = await run_user_cs_employee(
        {
            "handler": "llm_md",
            "action": "mobile_ai_customer_service",
            "channel": "mobile",
            "client_name": display,
            "market_user_id": _safe_user_id(user),
            "form_url": "https://xiu-ci.com/market/about",
            "message": msg_body,
            "brief": (
                "手机端用户正在和小C助理对话。请以 XCAGI 企业智能客服身份直接回复："
                "先回答用户当前问题；如果需要进一步采集需求，再给出2-3个追问和需求提交链接。"
                f"\n\n用户消息：{msg_body}"
            ),
        }
    )
    reply = _coerce_user_cs_reply(employee_result, fallback_reply)
    now = datetime.utcnow().isoformat()
    request_id, persisted, persist_error = _persist_mobile_cs_request(
        user,
        message_id=message_id,
        msg_body=msg_body,
        reply=reply,
        backend=EMPLOYEE_MOD_ID,
        employee_result=employee_result,
    )
    return format_mobile_response(
        data={
            "message_id": message_id,
            "request_id": request_id,
            "reply": reply,
            "backend": EMPLOYEE_MOD_ID,
            "persisted": persisted,
            "persist_error": persist_error,
            "timestamp": now,
        }
    )


@extension_router.get("/cs/messages")
async def get_cs_messages(
    request: Request, since: str | None = None, user=Depends(get_mobile_user)
):
    """拉取小C/智能客服消息。"""
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.db.models.service_request import ServiceRequest
    from app.db.session import get_db

    source_id = _mobile_cs_source_id(user)
    try:
        with get_db() as db:
            ServiceRequest.__table__.create(db.get_bind(), checkfirst=True)
            rows = (
                db.query(ServiceRequest)
                .filter(ServiceRequest.source_instance_id == source_id)
                .filter(ServiceRequest.request_type == "mobile_ai_customer_service")
                .order_by(ServiceRequest.created_at.asc(), ServiceRequest.id.asc())
                .limit(100)
                .all()
            )
            messages = [msg for row in rows for msg in _service_request_to_cs_messages(row)]
        error = ""
    except OPERATIONAL_ERRORS as exc:
        logger.warning("mobile cs message history unavailable: %s", exc)
        messages = []
        error = str(exc)[:300]
    if since:
        messages = [m for m in messages if str(m.get("timestamp") or "") > since]
    return format_mobile_response(data={"messages": messages, "persist_error": error})
