"""移动端 API 扩展：代理列表、设备注册、QR 配对。

本模块为路由处理入口，纯计算辅助函数与模型已按业务领域拆分至
``mobile_extensions`` 子包。为保证向后兼容（测试 patch / 直接调用），
所有公共符号均在此重新导出。
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

# ── 测试 patch / mext 代理用 re-export（子路由经 mext 回引本模块符号）──
from app.application.ai_group_chat_service import AiGroupChatService as AiGroupChatService
from app.application.claude_super_employee_service import (
    ClaudeSuperEmployeeService as ClaudeSuperEmployeeService,
)
from app.application.codex_super_employee_service import (
    CodexSuperEmployeeService as CodexSuperEmployeeService,
)
from app.application.cursor_super_employee_service import (
    CursorSuperEmployeeService as CursorSuperEmployeeService,
)
from app.application.execution_scope import factory_context as factory_context
from app.application.facades.mobile_relay_facade import MobileRelayService as MobileRelayService
from app.application.trae_super_employee_service import (
    TraeSuperEmployeeService as TraeSuperEmployeeService,
)
from app.fastapi_routes.mobile_api import get_mobile_user
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _admin_employee_match_keys,
    _apply_market_profile,
    _compact_text,
    _enrich_workflow_employees,
    _load_admin_duty_records,
    _mobile_session_meta,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _index_market_ai_employee_profiles as _index_market_ai_employee_profiles,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _load_market_ai_employee_profile_index as _load_market_ai_employee_profile_index,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _mobile_request_user_id as _mobile_request_user_id,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _mobile_session_meta as _mobile_session_meta,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _require_mobile_admin as _require_mobile_admin,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _require_mobile_admin_or_enterprise as _require_mobile_admin_or_enterprise,
)
from app.fastapi_routes.mobile_extensions.constants import (
    ADMIN_MOBILE_FEATURES as ADMIN_MOBILE_FEATURES,
)
from app.fastapi_routes.mobile_extensions.cs_helpers import (
    _mobile_cs_source_id,
    _mobile_cs_source_name,
    _safe_user_id,
    _safe_user_text,
)

# ── 子模块导入 ──
from app.fastapi_routes.mobile_extensions.models import (
    AiCircleCommentBody as AiCircleCommentBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    AiCirclePostBody as AiCirclePostBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    AiGroupCreateBody as AiGroupCreateBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    AiGroupMemberBody as AiGroupMemberBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    AiGroupMessageBody as AiGroupMessageBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    AuthQrConfirmBody as AuthQrConfirmBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    ClaudeSuperEmployeeMobileMessageBody as ClaudeSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    CodexSuperEmployeeMobileMessageBody as CodexSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    CursorSuperEmployeeMobileMessageBody as CursorSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    DeviceRegisterBody as DeviceRegisterBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    MobileServiceBridgeRespondBody as MobileServiceBridgeRespondBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    OidcExchangeBody as OidcExchangeBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    PairingExchangeBody as PairingExchangeBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    PairingIssueBody as PairingIssueBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    PairingLookupBody as PairingLookupBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    RelayDesktopCompleteBody as RelayDesktopCompleteBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    RelayDesktopPollBody as RelayDesktopPollBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    RelayDesktopRegisterBody as RelayDesktopRegisterBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    RelayMobileBindAccountBody as RelayMobileBindAccountBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    RelayTaskCreateBody as RelayTaskCreateBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    SyncAckBody as SyncAckBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    SyncPullBody as SyncPullBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    SyncPushBody as SyncPushBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    SyncPushItem as SyncPushItem,
)
from app.fastapi_routes.mobile_extensions.models import (
    TraeSuperEmployeeMobileMessageBody as TraeSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.pairing_helpers import (
    _enrich_pairing_payload as _enrich_pairing_payload,
)
from app.fastapi_routes.mobile_extensions.pairing_helpers import (
    _guess_lan_ipv4,
    _host_is_private_or_loopback,
)
from app.fastapi_routes.mobile_extensions.pairing_helpers import (
    _pairing_issue_port as _pairing_issue_port,
)
from app.fastapi_routes.mobile_extensions.pairing_helpers import (
    _pairing_reachable_port as _pairing_reachable_port,
)
from app.fastapi_routes.mobile_extensions.relay_helpers import (
    _mobile_user_identity,
    _mobile_user_public_dict,
    _relay_admin_fallback_user,
)
from app.fastapi_routes.mobile_extensions.relay_helpers import (
    _relay_mobile_auth_payload as _relay_mobile_auth_payload,
)
from app.mod_sdk.assistant_ssot import dedicated_cs_label
from app.security.mobile_pairing import consume_by_shortcode as consume_by_shortcode
from app.security.mobile_pairing import consume_pairing_nonce as consume_pairing_nonce
from app.security.mobile_pairing import issue_pairing_nonce as issue_pairing_nonce
from app.security.mobile_pairing import lookup_by_shortcode as lookup_by_shortcode
from app.utils.mobile_api import format_mobile_response, paginate_list
from app.utils.operational_errors import RECOVERABLE_ERRORS

OPERATIONAL_ERRORS = RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

extension_router = APIRouter(tags=["mobile-api-ext"])


def _mobile_session_id_from_request(request: Request) -> str:
    auth_raw = request.headers.get("Authorization") or ""
    auth_hdr = auth_raw if isinstance(auth_raw, str) else ""
    if auth_hdr.startswith("Bearer "):
        try:
            from app.security.mobile_jwt import verify_mobile_jwt

            payload = verify_mobile_jwt(auth_hdr[7:].strip()) or {}
            sid = str(payload.get("session_id") or "").strip()
            if sid:
                return sid
        except OPERATIONAL_ERRORS:
            logger.exception("mobile session id parse failed")
    sid_raw = request.headers.get("X-Session-ID") or ""
    return sid_raw.strip() if isinstance(sid_raw, str) else ""


def _mobile_market_authorization(request: Request, user: Any | None = None) -> str:
    from app.fastapi_routes.market_account import (
        _auth_header,
        latest_session_market_token,
        session_market_token,
    )

    sid = _mobile_session_id_from_request(request)
    token = session_market_token(sid) if sid else ""
    if not token:
        token = latest_session_market_token(user_id=getattr(user, "id", None))
    return _auth_header(token)


def _mobile_unauthorized_response() -> JSONResponse:
    return JSONResponse(
        format_mobile_response(None, "未授权", success=False, code=401),
        status_code=401,
    )


def _ai_circle_user(user: Any) -> tuple[int, str, str | None]:
    uid = int(getattr(user, "id", 0) or 0)
    name = str(
        getattr(user, "display_name", "") or getattr(user, "username", "") or "企业成员"
    ).strip()
    avatar = getattr(user, "wx_avatar_url", None)
    return uid, name, str(avatar).strip() if avatar else None


def _ai_circle_employee_profiles() -> dict[str, dict[str, str]]:
    profiles: dict[str, dict[str, str]] = {}
    for mod in _mobile_mod_items():
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


# ── 设备表初始化 ──


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


def _ensure_outbox_table() -> None:
    try:
        from sqlalchemy import inspect

        from app.db.models.mobile_notification import MobileNotificationOutbox
        from app.db.session import get_db

        with get_db() as db:
            bind = db.get_bind()
            insp = inspect(bind)
            if not insp.has_table(MobileNotificationOutbox.__tablename__):
                MobileNotificationOutbox.__table__.create(bind, checkfirst=True)
    except OPERATIONAL_ERRORS as exc:
        logger.warning("mobile_notification_outbox ensure: %s", exc)


# ── 中继用户解析（使用 RECOVERABLE_ERRORS，需留在主模块以支持测试 patch） ──


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


def _register_desktop_relay_for_pairing(host: str, port: int) -> dict[str, Any] | None:
    enabled = (os.environ.get("XCAGI_RELAY_PAIRING_ENABLED") or "1").strip().lower()
    if enabled in {"0", "false", "off", "no"}:
        return None
    if not _host_is_private_or_loopback(host):
        return None
    try:
        from app.application.facades.mobile_relay_facade import register_desktop_relay

        relay = register_desktop_relay(host=host, port=port)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("desktop relay registration skipped: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 — pairing must never block mobile login
        logger.warning("desktop relay registration skipped after unexpected failure: %s", exc)
        return None
    if not relay:
        return None
    public_relay = dict(relay)
    public_relay.pop("desktop_token", None)
    return public_relay


def _cached_desktop_relay_for_account_binding() -> dict[str, Any] | None:
    """Return the local desktop's cloud relay id for account-auth binding."""
    try:
        from app.application.facades.mobile_relay_facade import cached_desktop_relay_payload

        relay = cached_desktop_relay_payload()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("cached desktop relay unavailable: %s", exc)
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


# ── 配对主机解析（调用被测试 patch 的 _guess_lan_ipv4，须留在主模块） ──


def _pairing_issue_host(requested: str) -> str:
    host = str(requested or "").strip() or "127.0.0.1"
    if host in ("127.0.0.1", "localhost", "0.0.0.0"):
        return _guess_lan_ipv4()
    return host


# ── 服务桥接状态 ──


def _mobile_bridge_request_statuses() -> tuple[str, ...]:
    return ("pending", "processing", "resolved", "closed")


# ── 同步辅助函数（被测试 patch，须留在主模块） ──


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


def _safe_mobile_sync_items(name: str, loader) -> list[dict[str, Any]]:
    try:
        return loader()
    except Exception as exc:  # noqa: BLE001 - 单个业务表缺失不能拖垮手机拉同步
        logger.warning("mobile sync: %s skipped: %s", name, exc)
        return []


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
    except Exception as exc:  # noqa: BLE001 - AI 对话表缺失不能拖垮手机拉同步
        logger.warning("ai_conversation_changes: %s", exc)
        return []


# ── MOD 列表（被测试 patch，须留在主模块） ──


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
                    "avatar_url": m.get("avatar") or m.get("logo") or m.get("icon") or "",
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
                    "avatar_url": str(
                        getattr(m, "avatar", "")
                        or getattr(m, "logo", "")
                        or getattr(m, "icon", "")
                        or ""
                    ),
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


# ── 管理端编制员工（调用被测试 patch 的 _load_admin_duty_records，须留在主模块） ──


def _admin_roster_ids_by_department_order() -> list[str]:
    try:
        from app.mod_sdk.employee_ssot import derive_admin_duty_roster

        admin = derive_admin_duty_roster()
    except RECOVERABLE_ERRORS:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for dept in admin.get("departments") or []:
        if not isinstance(dept, dict):
            continue
        for employee in dept.get("employees") or []:
            if not isinstance(employee, dict):
                continue
            eid = str(employee.get("id") or "").strip()
            if eid and eid not in seen:
                seen.add(eid)
                out.append(eid)
    for eid in admin.get("planned_employee_ids") or []:
        eid = str(eid or "").strip()
        if eid and eid not in seen:
            seen.add(eid)
            out.append(eid)
    return out


def _admin_roster_area_labels() -> dict[str, str]:
    try:
        from app.mod_sdk.duty_roster import load_duty_roster_document

        doc = load_duty_roster_document()
    except RECOVERABLE_ERRORS:
        return {}
    out: dict[str, str] = {}
    areas = doc.get("areas") if isinstance(doc, dict) else {}
    if not isinstance(areas, dict):
        return out
    for _area_key, area in areas.items():
        if not isinstance(area, dict):
            continue
        label = _compact_text(area.get("label"))
        for eid in area.get("ids") or []:
            sid = str(eid or "").strip()
            if sid and label and sid not in out:
                out[sid] = label
    return out


def _admin_employee_manifest(employee_id: str) -> dict[str, Any]:
    eid = str(employee_id or "").strip()
    if not eid:
        return {}
    manifest = Path(__file__).resolve().parents[2] / "mods" / "_employees" / eid / "manifest.json"
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _admin_duty_records_from_roster() -> list[dict[str, Any]]:
    registry = _load_admin_duty_records()
    roster_ids = _admin_roster_ids_by_department_order()
    if not roster_ids:
        return registry
    registry_by_id: dict[str, dict[str, Any]] = {}
    for raw in registry:
        eid = str(raw.get("id") or raw.get("pkg_id") or "").strip()
        if eid and eid not in registry_by_id:
            registry_by_id[eid] = raw

    registry_ids = set(registry_by_id)
    roster_id_set = set(roster_ids)
    if registry_ids and not (registry_ids & roster_id_set):
        # Compatibility for direct unit tests that patch only the registry seam.
        return registry

    area_labels = _admin_roster_area_labels()
    records: list[dict[str, Any]] = []
    for eid in roster_ids:
        raw = dict(registry_by_id.get(eid) or {})
        manifest = _admin_employee_manifest(eid)
        employee_meta = (
            manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
        )
        raw.setdefault("id", eid)
        raw.setdefault("pkg_id", eid)
        raw.setdefault("name", manifest.get("name") or employee_meta.get("label") or eid)
        raw.setdefault("description", manifest.get("description") or "")
        raw.setdefault("version", manifest.get("version") or "")
        raw.setdefault("yuangon_area", area_labels.get(eid, ""))
        raw.setdefault("employee_scope", "duty")
        raw.setdefault("employee_source", "duty_roster")
        raw.setdefault("is_duty_employee", True)
        raw.setdefault("is_store_employee", False)
        records.append(raw)
    return records


def _admin_employee_items(
    market_profiles: dict[str, dict[str, Any]] | None = None,
    *,
    market_connected: bool = False,
    im_summary: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in _admin_duty_records_from_roster():
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
        if im_summary:
            summary = im_summary.get(employee_id)
            if summary:
                item.update(summary)
        items.append(item)
    return items


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
        "description": f"{len(employees)} 位管理端编制 AI 员工，来自 duty_roster.json。",
        "primary": True,
        "industry": {"id": "管理端", "name": "管理端"},
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


# ── 客服持久化（使用 OPERATIONAL_ERRORS，须留在主模块） ──


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
                title=msg_body[:80] or f"{dedicated_cs_label()}咨询",
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


# ════════════════════════════════════════════════════════════════════
# 路由处理函数
# ════════════════════════════════════════════════════════════════════


# ── 审批 / 客户 / 发货 ──


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
    from app.infrastructure.tenant_scope import apply_tenant_filter

    with get_db() as db:
        q = apply_tenant_filter(db.query(Customer), Customer)
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


# ── 员工 & 部门 SSOT（手机端只读派生，与桌面/网页同一份 config/duty_roster.json）──
def _employee_ssot_payload() -> dict[str, Any]:
    """管理端 6 部门上岗 + 企业端 4 部门上架/未上架，自动派生自 SSOT。"""
    from app.application.ops_closure_status import _installed_employee_pack_ids
    from app.mod_sdk.employee_ssot import derive_employee_ssot

    installed: set[str] = set()
    try:
        installed = _installed_employee_pack_ids()
    except OPERATIONAL_ERRORS as exc:
        logger.warning("mobile employee-ssot: 读取已安装 employee_pack 失败: %s", exc)
    return derive_employee_ssot(installed_ids=installed)


@extension_router.get("/employee-ssot")
async def mobile_employee_ssot(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    return format_mobile_response(data=_employee_ssot_payload())
# ── 子路由模块（实现见 mobile_extensions.*）──
from app.fastapi_routes.mobile_extensions.device_notify_routes import (  # noqa: E402, I001
    device_notify_router as device_notify_router,
    mobile_device_register as mobile_device_register,
    mobile_device_unregister as mobile_device_unregister,
    mobile_notifications_pending as mobile_notifications_pending,
    mobile_lan_android_update as mobile_lan_android_update,
    mobile_lan_android_update_notify as mobile_lan_android_update_notify,
    _lan_releases_root as _lan_releases_root,
    _lan_public_base_url as _lan_public_base_url,
    _is_loopback_request as _is_loopback_request,
)
extension_router.include_router(device_notify_router)

from app.fastapi_routes.mobile_extensions.relay_pairing_routes import (  # noqa: E402, I001
    relay_pairing_router as relay_pairing_router,
    mobile_pairing_issue as mobile_pairing_issue,
    mobile_pairing_lookup as mobile_pairing_lookup,
    mobile_pairing_exchange as mobile_pairing_exchange,
    mobile_service_bridge_requests as mobile_service_bridge_requests,
    mobile_service_bridge_request_respond as mobile_service_bridge_request_respond,
    mobile_relay_desktop_register as mobile_relay_desktop_register,
    mobile_relay_bind_account as mobile_relay_bind_account,
    mobile_relay_desktops as mobile_relay_desktops,
    mobile_relay_create_task as mobile_relay_create_task,
    mobile_relay_task_status as mobile_relay_task_status,
    mobile_relay_task_cancel as mobile_relay_task_cancel,
    mobile_relay_desktop_poll as mobile_relay_desktop_poll,
    mobile_relay_desktop_complete as mobile_relay_desktop_complete,
)
extension_router.include_router(relay_pairing_router)

from app.fastapi_routes.mobile_extensions.admin_mobile_routes import (  # noqa: E402, I001
    admin_mobile_router as admin_mobile_router,
    mobile_admin_employees as mobile_admin_employees,
    mobile_admin_features as mobile_admin_features,
    mobile_im_cs_inbox as mobile_im_cs_inbox,
    mobile_im_cs_inbox_messages as mobile_im_cs_inbox_messages,
    mobile_im_cs_inbox_reply as mobile_im_cs_inbox_reply,
    mobile_admin_home as mobile_admin_home,
)
extension_router.include_router(admin_mobile_router)

from app.fastapi_routes.mobile_extensions.super_employee_routes import (  # noqa: E402, I001
    super_employee_router as super_employee_router,
    mobile_admin_codex_super_employee_messages as mobile_admin_codex_super_employee_messages,
    mobile_admin_codex_super_employee_invoke as mobile_admin_codex_super_employee_invoke,
    mobile_admin_claude_super_employee_messages as mobile_admin_claude_super_employee_messages,
    mobile_admin_claude_super_employee_invoke as mobile_admin_claude_super_employee_invoke,
    mobile_admin_cursor_super_employee_messages as mobile_admin_cursor_super_employee_messages,
    mobile_admin_cursor_super_employee_invoke as mobile_admin_cursor_super_employee_invoke,
    mobile_admin_trae_super_employee_messages as mobile_admin_trae_super_employee_messages,
    mobile_admin_trae_super_employee_invoke as mobile_admin_trae_super_employee_invoke,
    mobile_admin_factory_workspaces as mobile_admin_factory_workspaces,
    mobile_admin_codex_super_employee_stream as mobile_admin_codex_super_employee_stream,
    mobile_admin_claude_super_employee_stream as mobile_admin_claude_super_employee_stream,
    mobile_admin_cursor_super_employee_stream as mobile_admin_cursor_super_employee_stream,
    mobile_admin_trae_super_employee_stream as mobile_admin_trae_super_employee_stream,
    _super_employee_service_for_tool as _super_employee_service_for_tool,
    _stream_super_employee_invoke as _stream_super_employee_invoke,
)
extension_router.include_router(super_employee_router)

from app.fastapi_routes.mobile_extensions.ai_group_routes import (  # noqa: E402, I001
    ai_group_router as ai_group_router,
    mobile_git_branches as mobile_git_branches,
    mobile_ai_groups_list as mobile_ai_groups_list,
    mobile_ai_group_candidates as mobile_ai_group_candidates,
    mobile_ai_groups_create as mobile_ai_groups_create,
    mobile_ai_group_messages as mobile_ai_group_messages,
    mobile_ai_group_post as mobile_ai_group_post,
    mobile_ai_group_add_member as mobile_ai_group_add_member,
    mobile_ai_group_remove_member as mobile_ai_group_remove_member,
    mobile_ai_group_toggle_pin as mobile_ai_group_toggle_pin,
    mobile_ai_group_mark_unread as mobile_ai_group_mark_unread,
    mobile_ai_group_mark_read as mobile_ai_group_mark_read,
    mobile_ai_group_toggle_followed as mobile_ai_group_toggle_followed,
    mobile_ai_group_toggle_hidden as mobile_ai_group_toggle_hidden,
    mobile_ai_group_delete as mobile_ai_group_delete,
    mobile_conversation_toggle_pin as mobile_conversation_toggle_pin,
    mobile_conversation_mark_unread as mobile_conversation_mark_unread,
    mobile_conversation_mark_read as mobile_conversation_mark_read,
    mobile_conversation_toggle_followed as mobile_conversation_toggle_followed,
    mobile_conversation_toggle_hidden as mobile_conversation_toggle_hidden,
    mobile_conversation_delete as mobile_conversation_delete,
    _mobile_group_uid as _mobile_group_uid,
    _mobile_group_mode as _mobile_group_mode,
    _clean_mobile_git_branch as _clean_mobile_git_branch,
    _mobile_branch_context_from_body as _mobile_branch_context_from_body,
    _mobile_git_repo_root as _mobile_git_repo_root,
    _git_no_prompt_env as _git_no_prompt_env,
    _mobile_git_branches_from_repo as _mobile_git_branches_from_repo,
    _mobile_git_branches_from_remote as _mobile_git_branches_from_remote,
    _sort_mobile_git_branches as _sort_mobile_git_branches,
    _conversation_state_uid as _conversation_state_uid,
)
extension_router.include_router(ai_group_router)

from app.fastapi_routes.mobile_extensions.sync_home_routes import (  # noqa: E402, I001
    sync_home_router as sync_home_router,
    mobile_ai_circle_posts as mobile_ai_circle_posts,
    mobile_ai_circle_create_post as mobile_ai_circle_create_post,
    mobile_ai_circle_toggle_like as mobile_ai_circle_toggle_like,
    mobile_ai_circle_add_comment as mobile_ai_circle_add_comment,
    mobile_mods_summary as mobile_mods_summary,
    mobile_platform_shell as mobile_platform_shell,
    mobile_onboarding_industries as mobile_onboarding_industries,
    mobile_industry_baseline as mobile_industry_baseline,
    mobile_select_onboarding_industry as mobile_select_onboarding_industry,
    mobile_install_host_foundation as mobile_install_host_foundation,
    mobile_install_industry_seed as mobile_install_industry_seed,
    mobile_install_mod as mobile_install_mod,
    mobile_install_customer_delivery_seed as mobile_install_customer_delivery_seed,
    mobile_home as mobile_home,
    mobile_nav_menu as mobile_nav_menu,
    mobile_sync_status as mobile_sync_status,
    mobile_sync_pull as mobile_sync_pull,
    mobile_sync_push as mobile_sync_push,
    mobile_sync_ack as mobile_sync_ack,
    mobile_sync_conflicts as mobile_sync_conflicts,
    _mobile_sync_runtime_contract as _mobile_sync_runtime_contract,
    _mobile_sync_circle_posts as _mobile_sync_circle_posts,
)
extension_router.include_router(sync_home_router)

from app.fastapi_routes.mobile_extensions.auth_payment_routes import (  # noqa: E402, I001
    auth_payment_router as auth_payment_router,
    mobile_auth_qr_confirm as mobile_auth_qr_confirm,
    mobile_auth_oidc_exchange as mobile_auth_oidc_exchange,
    get_mobile_fixed_contacts as get_mobile_fixed_contacts,
    get_cs_info as get_cs_info,
    post_cs_message as post_cs_message,
    get_cs_messages as get_cs_messages,
    mobile_payment_plans as mobile_payment_plans,
    mobile_payment_checkout as mobile_payment_checkout,
    mobile_payment_query as mobile_payment_query,
    mobile_wallet_balance as mobile_wallet_balance,
    _normalize_mobile_payment_channel as _normalize_mobile_payment_channel,
    _mobile_checkout_sign_body as _mobile_checkout_sign_body,
)
extension_router.include_router(auth_payment_router)
# ── 员工任务中心 / 员工 chat SSE（实现见 mobile_extensions.employee_routes）──
from app.fastapi_routes.mobile_extensions.employee_routes import (  # noqa: E402, I001
    _chunk_employee_reply as _chunk_employee_reply,
    _extract_employee_failure_text as _extract_employee_failure_text,
    _extract_employee_reply_text as _extract_employee_reply_text,
    _modstore_admin_proxy as _modstore_admin_proxy,
    _modstore_admin_token as _modstore_admin_token,
    _modstore_platform_base as _modstore_platform_base,
    _sse_line as _sse_line,
    employee_router as employee_router,
    mobile_admin_employee_pending_question_answer as mobile_admin_employee_pending_question_answer,
    mobile_admin_employee_pending_questions as mobile_admin_employee_pending_questions,
    mobile_employee_chat_stream as mobile_employee_chat_stream,
)

extension_router.include_router(employee_router)

