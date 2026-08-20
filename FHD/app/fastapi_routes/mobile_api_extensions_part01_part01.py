# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.mobile_api_extensions")


def _mobile_session_id_from_request(request: _facade().Request) -> str:
    auth_raw = request.headers.get("Authorization") or ""
    auth_hdr = auth_raw if isinstance(auth_raw, str) else ""
    if auth_hdr.startswith("Bearer "):
        try:
            from app.security.mobile_jwt import verify_mobile_jwt

            payload = verify_mobile_jwt(auth_hdr[7:].strip()) or {}
            sid = str(payload.get("session_id") or "").strip()
            if sid:
                return sid
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception("mobile session id parse failed")
    sid_raw = request.headers.get("X-Session-ID") or ""
    return sid_raw.strip() if isinstance(sid_raw, str) else ""


def _mobile_market_authorization(
    request: _facade().Request, user: _facade().Any | None = None
) -> str:
    from app.fastapi_routes.market_account import (
        _auth_header,
        latest_session_market_token,
        session_market_token,
    )

    sid = _facade()._mobile_session_id_from_request(request)
    token = session_market_token(sid) if sid else ""
    if not token:
        token = latest_session_market_token(user_id=getattr(user, "id", None))
    return _auth_header(token)


def _mobile_unauthorized_response() -> _facade().JSONResponse:
    return _facade().JSONResponse(
        _facade().format_mobile_response(None, "未授权", success=False, code=401), status_code=401
    )


def _ai_circle_user(user: _facade().Any) -> tuple[int, str, str | None]:
    uid = int(getattr(user, "id", 0) or 0)
    name = str(
        getattr(user, "display_name", "") or getattr(user, "username", "") or "企业成员"
    ).strip()
    avatar = getattr(user, "wx_avatar_url", None)
    return (uid, name, str(avatar).strip() if avatar else None)


def _ai_circle_employee_profiles() -> dict[str, dict[str, str]]:
    profiles: dict[str, dict[str, str]] = {}
    for mod in _facade()._mobile_mod_items():
        mod_avatar = str(mod.get("avatar_url") or "").strip()
        for employee in mod.get("workflow_employees") or []:
            if not isinstance(employee, dict):
                continue
            employee_id = str(employee.get("id") or "").strip()
            if not employee_id:
                continue
            profiles[employee_id] = {
                "name": str(
                    employee.get("label") or employee.get("panel_title") or employee_id
                ).strip(),
                "avatar": str(employee.get("market_avatar") or mod_avatar).strip(),
            }
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
                _facade().cast("Table", MobileDeviceToken.__table__).create(bind, checkfirst=True)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("mobile_device_tokens ensure: %s", exc)


def _ensure_outbox_table() -> None:
    try:
        from sqlalchemy import inspect

        from app.db.models.mobile_notification import MobileNotificationOutbox
        from app.db.session import get_db

        with get_db() as db:
            bind = db.get_bind()
            insp = inspect(bind)
            if not insp.has_table(MobileNotificationOutbox.__tablename__):
                _facade().cast("Table", MobileNotificationOutbox.__table__).create(
                    bind, checkfirst=True
                )
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("mobile_notification_outbox ensure: %s", exc)


def _resolve_mobile_relay_user(
    user: _facade().Any, *, prefer_admin: bool = False
) -> dict[str, _facade().Any]:
    """Resolve the mobile user for physical QR/device-code relay binding.

    A relay pairing code already proves physical access to the desktop settings
    screen, so first-time mobile binding must not require a pre-existing mobile
    JWT. Prefer an existing admin account; create a local relay admin only when
    the database has no active users yet.
    """
    uid, _ = _facade()._mobile_user_identity(user)
    role = str(getattr(user, "role", "") or "").strip()
    if uid > 0 and (not prefer_admin or role in {"admin", "super_admin", "owner"}):
        return _facade()._mobile_user_public_dict(user)
    from app.db.models import User
    from app.db.session import get_db

    try:
        with get_db() as db:
            row = None
            if prefer_admin or uid <= 0:
                row = (
                    db.query(User)
                    .filter(User.is_active == True)
                    .filter(User.role.in_(["admin", "super_admin", "owner"]))
                    .order_by(User.id.asc())
                    .first()
                )
            if row is None:
                row = db.query(User).filter(User.is_active == True).order_by(User.id.asc()).first()
            if row is None:
                now = _facade().datetime.utcnow()
                row = User(
                    username=f"mobile_relay_{_facade().uuid.uuid4().hex[:8]}",
                    password=_facade().uuid.uuid4().hex,
                    display_name="移动端设备绑定",
                    email="",
                    role="admin",
                    is_active=True,
                    created_at=now,
                    last_login=now,
                )
                db.add(row)
                db.flush()
            public = _facade()._mobile_user_public_dict(row)
            if hasattr(db, "expunge"):
                db.expunge(row)
            return public
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("mobile relay admin fallback: %s", exc)
        if prefer_admin:
            return _facade()._relay_admin_fallback_user()
        raise


def _register_desktop_relay_for_pairing(host: str, port: int) -> dict[str, _facade().Any] | None:
    enabled = (_facade().os.environ.get("XCAGI_RELAY_PAIRING_ENABLED") or "1").strip().lower()
    if enabled in {"0", "false", "off", "no"}:
        return None
    if not _facade()._host_is_private_or_loopback(host):
        return None
    try:
        from app.application.facades.mobile_relay_facade import register_desktop_relay

        relay = register_desktop_relay(host=host, port=port)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("desktop relay registration skipped: %s", exc)
        return None
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning(
            "desktop relay registration skipped after unexpected failure: %s", exc
        )
        return None
    if not relay:
        return None
    public_relay = dict(relay)
    public_relay.pop("desktop_token", None)
    return public_relay


def _cached_desktop_relay_for_account_binding() -> dict[str, _facade().Any] | None:
    """Return the local desktop's cloud relay id for account-auth binding."""
    try:
        from app.application.facades.mobile_relay_facade import cached_desktop_relay_payload

        relay = cached_desktop_relay_payload()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("cached desktop relay unavailable: %s", exc)
        return None
    if not relay:
        return None
    if relay.get("paired") is not True:
        return None
    relay_id = str(relay.get("relay_id") or "").strip()
    if not relay_id:
        return None
    return {
        "relay_id": relay_id,
        "relay_base_url": str(relay.get("relay_base_url") or "").strip(),
        "expires_at": str(relay.get("expires_at") or "").strip(),
        "exp": int(relay.get("exp") or 0),
        "binding_mode": "account_auth",
    }


def _pairing_issue_host(requested: str) -> str:
    host = str(requested or "").strip() or "127.0.0.1"
    if host in ("127.0.0.1", "localhost", "0.0.0.0"):
        return _facade()._guess_lan_ipv4()
    return host


def _mobile_bridge_request_statuses() -> tuple[str, ...]:
    return ("pending", "processing", "resolved", "closed")


def _approval_items(limit: int = 100) -> list[dict[str, _facade().Any]]:
    from app.db.models.approval import ApprovalRequest
    from app.db.session import get_db

    with get_db() as db:
        rows = (
            db.query(ApprovalRequest).order_by(ApprovalRequest.created_at.desc()).limit(limit).all()
        )
        return [
            {"id": r.id, "title": r.title, "status": r.status, "request_no": r.request_no}
            for r in rows
        ]


def _shipment_items(limit: int = 100) -> list[dict[str, _facade().Any]]:
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


def _safe_mobile_sync_items(name: str, loader) -> list[dict[str, _facade().Any]]:
    try:
        return _facade().cast("list[dict[str, Any]]", loader())
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("mobile sync: %s skipped: %s", name, exc)
        return []


def _ai_conversation_changes(
    user: _facade().Any, limit: int = 100
) -> list[dict[str, _facade().Any]]:
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
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("ai_conversation_changes: %s", exc)
        return []
