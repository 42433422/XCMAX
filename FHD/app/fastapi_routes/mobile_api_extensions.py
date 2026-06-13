"""移动端 API 扩展：代理列表、设备注册、QR 配对。"""

from __future__ import annotations

import logging
import socket
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.fastapi_routes.mobile_api import get_mobile_user
from app.security.mobile_pairing import (
    consume_by_shortcode,
    consume_pairing_nonce,
    issue_pairing_nonce,
    lookup_by_shortcode,
)
from app.utils.mobile_api import format_mobile_response, paginate_list
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

extension_router = APIRouter(tags=["mobile-api-ext"])


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
    except RECOVERABLE_ERRORS as exc:
        logger.warning("mobile_device_tokens ensure: %s", exc)


class DeviceRegisterBody(BaseModel):
    fcm_token: str = Field(..., min_length=8)
    push_provider: str = Field(default="fcm", max_length=16)
    push_token: str = Field(default="", max_length=512)
    product_sku: str = Field(default="personal", max_length=32)
    device_label: str = Field(default="", max_length=200)
    platform: str = Field(default="android", max_length=32)


class PairingExchangeBody(BaseModel):
    nonce: str = Field(default="", min_length=0)
    code: str = Field(default="", max_length=6)


class PairingLookupBody(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class PairingIssueBody(BaseModel):
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=5000, ge=1, le=65535)


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


@extension_router.post("/pairing/issue")
async def mobile_pairing_issue(body: PairingIssueBody):
    """桌面或运维签发配对 QR 载荷（开发/内网）。"""
    host = _pairing_issue_host(body.host)
    port = int(body.port)
    payload = issue_pairing_nonce(host, port)
    return format_mobile_response(data=payload)


@extension_router.post("/pairing/lookup")
async def mobile_pairing_lookup(body: PairingLookupBody):
    """手机通过 6 位配对码查询完整连接信息（不消费）。"""
    rec = lookup_by_shortcode(body.code.strip())
    if not rec:
        return JSONResponse(
            format_mobile_response(None, "配对码无效或已过期", success=False, code=404),
            status_code=404,
        )
    return format_mobile_response(
        data={
            "host": rec["host"],
            "port": rec["port"],
            "nonce": rec["nonce"],
            "exp": rec.get("exp", 0),
        }
    )


@extension_router.post("/pairing/exchange")
async def mobile_pairing_exchange(body: PairingExchangeBody):
    # 支持两种方式：nonce（旧）或 shortCode（新）
    nonce_val = body.nonce.strip()
    code_val = body.code.strip()
    if code_val:
        rec = consume_by_shortcode(code_val)
    elif nonce_val:
        rec = consume_pairing_nonce(nonce_val)
    else:
        rec = None
    if not rec:
        return JSONResponse(
            format_mobile_response(None, "配对码无效或已过期", success=False, code=400),
            status_code=400,
        )
    return format_mobile_response(
        data={
            "host": rec["host"],
            "port": rec["port"],
            "shortCode": rec.get("shortCode", ""),
            "hint": "配对成功，App 已获取连接信息",
        },
    )


def _mobile_mod_items() -> list[dict[str, str]]:
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        items: list[dict[str, str]] = []
        for m in get_mod_manager().list_all_mods() or []:
            if isinstance(m, dict):
                mid = str(m.get("id") or m.get("mod_id") or "").strip()
                name = str(m.get("name") or m.get("title") or mid).strip()
            else:
                mid = str(getattr(m, "id", None) or getattr(m, "mod_id", "") or "").strip()
                name = str(getattr(m, "name", None) or getattr(m, "title", None) or mid).strip()
            if mid:
                items.append({"id": mid, "name": name})
        return items[:100]
    except RECOVERABLE_ERRORS as exc:
        logger.warning("mobile mods list: %s", exc)
        return []


@extension_router.get("/mods")
async def mobile_mods_summary(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    return format_mobile_response(data={"items": _mobile_mod_items()})


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
    installed = [m["id"] for m in _mobile_mod_items()]
    from app.mod_sdk.platform_shell import build_platform_shell_payload

    sync_data: dict[str, Any] = {}
    try:
        from app.db.xcmax_sync import SyncDb

        sync_data = SyncDb().get_status()
    except RECOVERABLE_ERRORS as exc:
        sync_data = {"error": str(exc)}
    return format_mobile_response(
        data={
            "mods": _mobile_mod_items(),
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
    except RECOVERABLE_ERRORS as exc:
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
        return format_mobile_response(
            data={
                "cursor": cursor,
                "changes": changes,
                "im_changes": im_changes,
                "im_change_count": len(im_changes),
                "approvals": _approval_items(),
                "shipments": _shipment_items(),
            },
        )
    except RECOVERABLE_ERRORS as exc:
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
        except RECOVERABLE_ERRORS as ae:
            apply_result = {"error": str(ae)}
        return format_mobile_response(data={"written": written, "apply": apply_result})
    except RECOVERABLE_ERRORS as exc:
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
    except RECOVERABLE_ERRORS as exc:
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
    except RECOVERABLE_ERRORS as exc:
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
    account_kind = normalize_account_kind(
        body.account_kind,
        default="enterprise" if sku == "enterprise" else "personal",
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
            except RECOVERABLE_ERRORS:
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
    except RECOVERABLE_ERRORS as exc:
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
    account_kind = normalize_account_kind(
        body.account_kind,
        default="enterprise" if sku == "enterprise" else "personal",
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
        try:
            payload = err.body.decode("utf-8") if hasattr(err, "body") else str(err)
        except RECOVERABLE_ERRORS:
            payload = "登录失败"
        return JSONResponse(
            format_mobile_response(None, payload, success=False, code=401),
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
    except RECOVERABLE_ERRORS as exc:
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
