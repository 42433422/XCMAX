"""移动端 API 扩展：代理列表、设备注册、QR 配对。

本模块为路由处理入口，纯计算辅助函数与模型已按业务领域拆分至
``mobile_extensions`` 子包。为保证向后兼容（测试 patch / 直接调用），
所有公共符号均在此重新导出。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.application.ai_group_chat_service import AiGroupChatService
from app.application.claude_super_employee_service import ClaudeSuperEmployeeService
from app.application.codex_super_employee_service import CodexSuperEmployeeService
from app.application.cursor_super_employee_service import CursorSuperEmployeeService
from app.application.execution_scope import factory_context
from app.application.facades.mobile_relay_facade import MobileRelayService
from app.application.trae_super_employee_service import TraeSuperEmployeeService
from app.fastapi_routes.mobile_api import get_mobile_user
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _admin_employee_match_keys,
    _apply_market_profile,
    _compact_text,
    _enrich_workflow_employees,
    _load_admin_duty_records,
    _load_market_ai_employee_profile_index,
    _mobile_request_user_id,
    _mobile_session_meta,
    _require_mobile_admin,
    _require_mobile_admin_or_enterprise,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _index_market_ai_employee_profiles as _index_market_ai_employee_profiles,
)
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _mobile_session_meta as _mobile_session_meta,
)
from app.fastapi_routes.mobile_extensions.constants import (
    ADMIN_MOBILE_FEATURES,
)
from app.fastapi_routes.mobile_extensions.cs_helpers import (
    _mobile_cs_source_id,
    _mobile_cs_source_name,
    _safe_user_id,
    _safe_user_text,
)

# ── 子模块导入 ──
from app.fastapi_routes.mobile_extensions.models import (
    AiCircleCommentBody,
    AiCirclePostBody,
    AiGroupCreateBody,
    AiGroupMemberBody,
    AiGroupMessageBody,
    AuthQrConfirmBody,
    ClaudeSuperEmployeeMobileMessageBody,
    CodexSuperEmployeeMobileMessageBody,
    CursorSuperEmployeeMobileMessageBody,
    DeviceRegisterBody,
    MobileServiceBridgeRespondBody,
    OidcExchangeBody,
    PairingExchangeBody,
    PairingIssueBody,
    PairingLookupBody,
    RelayDesktopCompleteBody,
    RelayDesktopPollBody,
    RelayDesktopRegisterBody,
    RelayMobileBindAccountBody,
    RelayMobileConfirmBody,
    RelayMobileConfirmCodeBody,
    RelayTaskCreateBody,
    SyncAckBody,
    SyncPullBody,
    SyncPushBody,
    TraeSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.models import (
    SyncPushItem as SyncPushItem,
)
from app.fastapi_routes.mobile_extensions.pairing_helpers import (
    _enrich_pairing_payload,
    _guess_lan_ipv4,
    _host_is_private_or_loopback,
    _pairing_issue_port,
)
from app.fastapi_routes.mobile_extensions.relay_helpers import (
    _mobile_user_identity,
    _mobile_user_public_dict,
    _relay_admin_fallback_user,
    _relay_mobile_auth_payload,
)
from app.mod_sdk.assistant_ssot import dedicated_cs_label
from app.security.mobile_pairing import (
    consume_by_shortcode,
    consume_pairing_nonce,
    issue_pairing_nonce,
    lookup_by_shortcode,
)
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
    except Exception as exc:
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


# ── 设备管理 ──


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


@extension_router.get("/notifications/pending")
async def mobile_notifications_pending(
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    """自建推送后台通道:返回未送达的离线通知并标记 delivered（客户端 WorkManager 轮询）。"""
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    _ensure_outbox_table()
    import json as _json

    from app.db.models.mobile_notification import MobileNotificationOutbox
    from app.db.session import get_db
    from app.utils.time import utc_now_naive

    items: list[dict] = []
    with get_db() as db:
        rows = (
            db.query(MobileNotificationOutbox)
            .filter(
                MobileNotificationOutbox.user_id == user.id,
                MobileNotificationOutbox.delivered.is_(False),
            )
            .order_by(MobileNotificationOutbox.created_at.asc())
            .limit(limit)
            .all()
        )
        now = utc_now_naive()
        for r in rows:
            try:
                data = _json.loads(r.data_json or "{}")
            except (ValueError, TypeError):
                data = {}
            items.append(
                {
                    "id": r.id,
                    "title": r.title,
                    "body": r.body,
                    "route": r.route,
                    "channel": r.channel,
                    "data": data,
                }
            )
            r.delivered = True
            r.delivered_at = now
    return format_mobile_response(data={"notifications": items})


# ── 配对 ──


@extension_router.post("/pairing/issue")
async def mobile_pairing_issue(body: PairingIssueBody, request: Request):
    """桌面或运维签发配对 QR 载荷（开发/内网）。"""
    host = _pairing_issue_host(body.host or (request.url.hostname or ""))
    port = _pairing_issue_port(request, int(body.port))
    payload = issue_pairing_nonce(host, port)
    data = _enrich_pairing_payload(payload)
    relay = _register_desktop_relay_for_pairing(host, port)
    if relay:
        data["relay"] = relay
        data["relay_id"] = relay.get("relay_id")
        data["relay_base_url"] = relay.get("relay_base_url")
        data["relay_binding_mode"] = "account_auth"
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
    data = {
        **_enrich_pairing_payload(rec),
        **_relay_mobile_auth_payload(user_public),
        "hint": "已返回可保存的 api_base_url，手机端可直接绑定该设备。",
    }
    relay = _cached_desktop_relay_for_account_binding()
    if relay:
        data["relay"] = relay
        data["relay_id"] = relay.get("relay_id")
        data["relay_base_url"] = relay.get("relay_base_url")
        data["relay_binding_mode"] = "account_auth"
    return format_mobile_response(data=data)


# ── 服务桥接 ──


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
        return format_mobile_response(
            data=paginate_list([r.to_dict() for r in items], total, page, per_page)
        )


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


# ── 中继服务 ──


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


@extension_router.post("/relay/mobile/bind-account")
async def mobile_relay_bind_account(
    body: RelayMobileBindAccountBody,
    user=Depends(get_mobile_user),
):
    uid, username = _mobile_user_identity(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        desktop = MobileRelayService().bind_mobile_by_account(
            user_id=uid,
            username=username,
            relay_id=body.relay_id,
        )
        if not desktop:
            return JSONResponse(
                format_mobile_response(None, "未找到可绑定的电脑执行端", success=False, code=404),
                status_code=404,
            )
        user_public = _mobile_user_public_dict(user)
        return format_mobile_response(
            data={
                "desktop": desktop,
                "relay_id": desktop.get("relay_id"),
                **_relay_mobile_auth_payload(user_public, desktop),
            }
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_relay_bind_account")
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


# ── 管理端 ──


@extension_router.get("/admin/employees")
async def mobile_admin_employees(request: Request, user=Depends(get_mobile_user)):
    _, err = _require_mobile_admin(request, user)
    if err is not None:
        return err
    market_profiles, market_connected, market_error = await _load_market_ai_employee_profile_index()
    uid = _mobile_request_user_id(request, user)
    im_summary: dict[str, dict[str, Any]] = {}
    if uid > 0:
        try:
            from app.application.im_app_service import ImApplicationService
            from app.db import SessionLocal

            db = SessionLocal()
            try:
                raw_items = _admin_employee_items(
                    market_profiles, market_connected=market_connected
                )
                im_summary = ImApplicationService(db).employee_im_summary(uid, raw_items)
            finally:
                db.close()
        except RECOVERABLE_ERRORS:
            logger.debug("employee_im_summary skipped for /admin/employees", exc_info=True)
    items = _admin_employee_items(
        market_profiles, market_connected=market_connected, im_summary=im_summary
    )
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


# ── 管理端客服收件箱(企业客户↔企业专属客服,手机 Bearer + admin 守卫)──


@extension_router.get("/im/cs/inbox")
async def mobile_im_cs_inbox(request: Request, user=Depends(get_mobile_user)):
    """运营者手机:列出所有企业客户的专属客服会话。"""
    _, err = _require_mobile_admin(request, user)
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
        return format_mobile_response(data={"conversations": conversations})
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile cs inbox failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.get("/im/cs/inbox/{conversation_id}/messages")
async def mobile_im_cs_inbox_messages(
    conversation_id: int, request: Request, user=Depends(get_mobile_user)
):
    """运营者手机:读某客服会话历史(fromCustomer 区分客户/客服)。"""
    _, err = _require_mobile_admin(request, user)
    if err is not None:
        return err
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db

    try:
        with get_db() as db:
            svc = ImApplicationService(db)
            cs_id = int(svc.enterprise_cs_user_id() or 0)
            raw = svc.cs_inbox_messages(conversation_id)
        messages = [
            {
                "messageId": str(m.get("id") or ""),
                "fromCustomer": int(m.get("sender_user_id") or 0) != cs_id,
                "senderName": str(m.get("sender_display_name") or ""),
                "body": str(m.get("body") or ""),
                "timestamp": str(m.get("created_at") or ""),
            }
            for m in raw
        ]
        return format_mobile_response(data={"messages": messages})
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile cs inbox messages failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.post("/im/cs/inbox/{conversation_id}/reply")
async def mobile_im_cs_inbox_reply(
    conversation_id: int, body: dict, request: Request, user=Depends(get_mobile_user)
):
    """运营者手机:以「企业专属客服」身份回复客户。"""
    _, err = _require_mobile_admin(request, user)
    if err is not None:
        return err
    text = str(body.get("body") or "").strip()
    if not text:
        return JSONResponse(
            format_mobile_response(None, "消息不能为空", success=False, code=400), status_code=400
        )
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db

    try:
        with get_db() as db:
            result = ImApplicationService(db).cs_reply(conversation_id, text)
        sent = result.get("message") or {}
        return format_mobile_response(
            data={
                "messageId": str(sent.get("id") or ""),
                "timestamp": str(sent.get("created_at") or ""),
            }
        )
    except (ValueError, PermissionError) as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile cs inbox reply failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.get("/admin/home")
async def mobile_admin_home(request: Request, user=Depends(get_mobile_user)):
    meta, err = _require_mobile_admin(request, user)
    if err is not None:
        return err
    market_profiles, market_connected, market_error = await _load_market_ai_employee_profile_index()
    employees = _admin_employee_items(market_profiles, market_connected=market_connected)
    # 把员工与老板的 direct IM 会话摘要合并进员工项，让 App 在现有员工列表里直接看到/点进 IM 会话。
    # employee_im_summary 会自动为尚无 IM 用户/会话的员工 ensure 虚拟用户 + 创建空 direct 会话，
    # 确保老板首次点击员工聊天页时 im_conv_id > 0，前端能正常走 IM 消息通道。
    uid = _mobile_request_user_id(request, user)
    im_summary: dict[str, dict[str, Any]] = {}
    if uid > 0 and employees:
        try:
            from app.application.im_app_service import ImApplicationService
            from app.db import SessionLocal

            db = SessionLocal()
            try:
                im_summary = ImApplicationService(db).employee_im_summary(uid, employees)
            finally:
                db.close()
        except RECOVERABLE_ERRORS:
            logger.debug("employee_im_summary skipped", exc_info=True)
    employees = _admin_employee_items(
        market_profiles, market_connected=market_connected, im_summary=im_summary
    )
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
    """移动端管理员信息页的 Codex 超级员工对话记录（仅管理端）。"""
    _, err = _require_mobile_admin(request, user)
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
    """移动端管理员信息页的软件内 Codex 调用入口（仅管理端）。"""
    _, err = _require_mobile_admin(request, user)
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
    # 本路由已收口为仅管理端可达；管理账号铸造工厂授权。
    if (
        str((_mobile_session_meta(request) or {}).get("account_kind") or "").strip().lower()
        == "admin"
    ):
        _wsid = str(getattr(body, "workspace_id", "") or context.get("workspace_id") or "xcmax")
        context = factory_context(workspace_id=_wsid, base=context)
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


@extension_router.get("/admin/claude-super-employee/messages")
async def mobile_admin_claude_super_employee_messages(
    request: Request,
    limit: int = Query(default=80, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的 Claude 超级员工对话记录（仅管理端）。"""
    _, err = _require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = _mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        messages = ClaudeSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return format_mobile_response(data={"messages": messages})
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_admin_claude_super_employee_messages")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/admin/claude-super-employee/messages")
async def mobile_admin_claude_super_employee_invoke(
    request: Request,
    body: ClaudeSuperEmployeeMobileMessageBody,
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的软件内 Claude 调用入口（仅管理端）。"""
    _, err = _require_mobile_admin(request, user)
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
    # 本路由已收口为仅管理端可达；管理账号铸造工厂授权。
    if (
        str((_mobile_session_meta(request) or {}).get("account_kind") or "").strip().lower()
        == "admin"
    ):
        _wsid = str(getattr(body, "workspace_id", "") or context.get("workspace_id") or "xcmax")
        context = factory_context(workspace_id=_wsid, base=context)
    try:
        result = ClaudeSuperEmployeeService().invoke(
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
        logger.exception("mobile_admin_claude_super_employee_invoke")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.get("/admin/cursor-super-employee/messages")
async def mobile_admin_cursor_super_employee_messages(
    request: Request,
    limit: int = Query(default=80, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的 Cursor 超级员工对话记录（仅管理端）。"""
    _, err = _require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = _mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        messages = CursorSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return format_mobile_response(data={"messages": messages})
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_admin_cursor_super_employee_messages")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/admin/cursor-super-employee/messages")
async def mobile_admin_cursor_super_employee_invoke(
    request: Request,
    body: CursorSuperEmployeeMobileMessageBody,
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的软件内 Cursor 调用入口（仅管理端）。"""
    _, err = _require_mobile_admin(request, user)
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
    context.setdefault("device_scope", "all_devices")
    context.setdefault("target_devices", ["all"])
    try:
        result = CursorSuperEmployeeService().invoke(
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
        logger.exception("mobile_admin_cursor_super_employee_invoke")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.get("/admin/trae-super-employee/messages")
async def mobile_admin_trae_super_employee_messages(
    request: Request,
    limit: int = Query(default=80, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的 Trae 超级员工对话记录（仅管理端）。"""
    _, err = _require_mobile_admin(request, user)
    if err is not None:
        return err
    uid = _mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    try:
        messages = TraeSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return format_mobile_response(data={"messages": messages})
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_admin_trae_super_employee_messages")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/admin/trae-super-employee/messages")
async def mobile_admin_trae_super_employee_invoke(
    request: Request,
    body: TraeSuperEmployeeMobileMessageBody,
    user=Depends(get_mobile_user),
):
    """移动端管理员信息页的软件内 Trae 调用入口（仅管理端）。"""
    _, err = _require_mobile_admin(request, user)
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
    context.setdefault("device_scope", "all_devices")
    context.setdefault("target_devices", ["all"])
    if (
        str((_mobile_session_meta(request) or {}).get("account_kind") or "").strip().lower()
        == "admin"
    ):
        _wsid = str(getattr(body, "workspace_id", "") or context.get("workspace_id") or "xcmax")
        context = factory_context(workspace_id=_wsid, base=context)
    try:
        result = TraeSuperEmployeeService().invoke(
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
        logger.exception("mobile_admin_trae_super_employee_invoke")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


# ── AI 群聊（微信式多 AI 群组）──


def _mobile_group_uid(request: Request, user) -> int:
    return _mobile_request_user_id(request, user)


def _mobile_group_mode(request: Request) -> str:
    """从 session 判定群聊模式：admin（6 部门 + 上岗员工）或 enterprise（4 部门 + 上架/未上架）。"""
    meta = _mobile_session_meta(request) or {}
    return (
        "admin" if str(meta.get("account_kind") or "").strip().lower() == "admin" else "enterprise"
    )


def _clean_mobile_git_branch(raw: Any) -> str:
    branch = str(raw or "").strip()
    if branch.startswith("refs/heads/"):
        branch = branch.removeprefix("refs/heads/")
    if branch.startswith("refs/remotes/"):
        branch = branch.removeprefix("refs/remotes/")
    if branch.startswith("origin/"):
        branch = branch.removeprefix("origin/")
    branch = re.sub(r"[^A-Za-z0-9._/-]+", "-", branch)[:180].strip("/.")
    if not branch or branch in {"HEAD", "origin/HEAD", ".", ".."}:
        return ""
    if ".." in branch or "//" in branch or "@{" in branch or branch.endswith(".lock"):
        return ""
    return branch


def _mobile_branch_context_from_body(body: AiGroupMessageBody) -> str:
    context_raw = getattr(body, "context", {})
    context = context_raw if isinstance(context_raw, dict) else {}
    return _clean_mobile_git_branch(
        getattr(body, "branch_context", "")
        or getattr(body, "branch", "")
        or context.get("branch_context")
        or context.get("branch")
    )


def _mobile_git_repo_root() -> Path | None:
    candidates: list[Path] = []
    for key in (
        "XCMAX_REPO_ROOT",
        "FHD_REPO_ROOT",
        "DEVFLEET_REPO_ROOT",
        "CODEX_WORKSPACE",
        "WORKSPACE_ROOT",
    ):
        value = str(os.environ.get(key) or "").strip()
        if value:
            candidates.append(Path(value).expanduser())
    candidates.append(Path.cwd())
    candidates.extend(Path(__file__).resolve().parents)
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            roots = [candidate, *candidate.parents] if candidate.exists() else [candidate]
        except RuntimeError:
            roots = [candidate]
        for root in roots:
            if root in seen:
                continue
            seen.add(root)
            if (root / ".git").exists():
                return root
    return None


def _git_no_prompt_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_ASKPASS", "true")
    return env


def _mobile_git_branches_from_repo(repo: Path) -> list[dict[str, Any]]:
    current = ""
    try:
        cur = subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=10,
            env=_git_no_prompt_env(),
            check=False,
        )
        if cur.returncode == 0:
            current = _clean_mobile_git_branch(cur.stdout)
    except Exception:  # noqa: BLE001
        current = ""
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "for-each-ref",
                "--format=%(refname:short)",
                "refs/heads",
                "refs/remotes/origin",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            env=_git_no_prompt_env(),
            check=False,
        )
    except Exception:  # noqa: BLE001
        return []
    if result.returncode != 0:
        return []
    branches: dict[str, dict[str, Any]] = {}
    for line in result.stdout.splitlines():
        raw = line.strip()
        if not raw or raw == "origin/HEAD":
            continue
        remote = raw.startswith("origin/")
        name = _clean_mobile_git_branch(raw)
        if not name:
            continue
        row = branches.setdefault(name, {"name": name, "current": False, "remote": False})
        row["current"] = bool(row["current"] or name == current)
        row["remote"] = bool(row["remote"] or remote)
    return _sort_mobile_git_branches(branches.values())


def _mobile_git_branches_from_remote() -> list[dict[str, Any]]:
    remote_url = str(
        os.environ.get("XCMAX_GIT_REMOTE_URL")
        or os.environ.get("FHD_GIT_REMOTE_URL")
        or "https://github.com/42433422/XCMAX.git"
    ).strip()
    if not remote_url:
        return []
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", remote_url],
            capture_output=True,
            text=True,
            timeout=15,
            env=_git_no_prompt_env(),
            check=False,
        )
    except Exception:  # noqa: BLE001
        return []
    if result.returncode != 0:
        return []
    branches: dict[str, dict[str, Any]] = {}
    for line in result.stdout.splitlines():
        if "refs/heads/" not in line:
            continue
        name = _clean_mobile_git_branch(line.rsplit("refs/heads/", 1)[-1])
        if name:
            branches[name] = {"name": name, "current": False, "remote": True}
    return _sort_mobile_git_branches(branches.values())


def _sort_mobile_git_branches(rows) -> list[dict[str, Any]]:
    branches = list(rows)
    branches.sort(
        key=lambda item: (
            not bool(item.get("current")),
            0 if item.get("name") in {"main", "master"} else 1,
            str(item.get("name") or "").lower(),
        )
    )
    return branches[:200]


@extension_router.get("/git/branches")
async def mobile_git_branches(request: Request, user=Depends(get_mobile_user)):
    """列出手机端可选工作分支：优先本地 repo，部署包无 .git 时退到远端 heads。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    try:
        repo = _mobile_git_repo_root()
        branches = _mobile_git_branches_from_repo(repo) if repo else []
        if not branches:
            branches = _mobile_git_branches_from_remote()
        return format_mobile_response(data={"branches": branches})
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_git_branches")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.get("/ai-groups")
async def mobile_ai_groups_list(request: Request, user=Depends(get_mobile_user)):
    """列出当前用户的 AI 群聊（首次自动按 6 个部门种出 6 个群）。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        groups = AiGroupChatService(mode=_mobile_group_mode(request)).list_groups(user_id=uid)
        return format_mobile_response(data={"groups": groups})
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_ai_groups_list")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.get("/ai-groups/candidates")
async def mobile_ai_group_candidates(request: Request, user=Depends(get_mobile_user)):
    """可拉入群聊的 AI 员工候选（普通员工 + 超级员工）。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        candidates = AiGroupChatService(mode=_mobile_group_mode(request)).list_member_candidates()
        return format_mobile_response(
            data={
                "candidates": candidates,
                "items": candidates,
                "count": len(candidates),
            }
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_ai_group_candidates")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.post("/ai-groups")
async def mobile_ai_groups_create(
    request: Request, body: AiGroupCreateBody, user=Depends(get_mobile_user)
):
    """创建自定义 AI 群聊。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).create_group(
            user_id=uid, name=body.name
        )
        return format_mobile_response(data={"group": group})
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_ai_groups_create")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.get("/ai-groups/{group_id}/messages")
async def mobile_ai_group_messages(
    request: Request,
    group_id: str,
    limit: int = Query(default=100, ge=1, le=300),
    user=Depends(get_mobile_user),
):
    """拉取某个 AI 群聊的历史消息。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        messages = AiGroupChatService(mode=_mobile_group_mode(request)).get_messages(
            user_id=uid, group_id=group_id, limit=limit
        )
        return format_mobile_response(data={"messages": messages})
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_ai_group_messages")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.post("/ai-groups/{group_id}/messages")
async def mobile_ai_group_post(
    request: Request, group_id: str, body: AiGroupMessageBody, user=Depends(get_mobile_user)
):
    """在 AI 群聊里发消息：群成员各回一条；@ 了具体成员则只有 TA 回复。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        branch_context = _mobile_branch_context_from_body(body)
        result = await AiGroupChatService(mode=_mobile_group_mode(request)).post_message(
            user_id=uid,
            group_id=group_id,
            text=body.message,
            sender_name=body.sender_name or "我",
            mentions=body.mentions,
            dispatch=bool(body.dispatch),
            branch_context=branch_context,
            context=body.context if isinstance(getattr(body, "context", None), dict) else {},
        )
        return format_mobile_response(data=result)
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_ai_group_post")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.post("/ai-groups/{group_id}/members")
async def mobile_ai_group_add_member(
    request: Request, group_id: str, body: AiGroupMemberBody, user=Depends(get_mobile_user)
):
    """把一个 AI 员工拉进群。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).add_member(
            user_id=uid,
            group_id=group_id,
            member={
                "employee_id": body.employee_id,
                "mod_id": body.mod_id,
                "name": body.name,
                "avatar": body.avatar,
                "summary": body.summary,
            },
        )
        return format_mobile_response(data={"group": group})
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_ai_group_add_member")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.delete("/ai-groups/{group_id}/members/{employee_id}")
async def mobile_ai_group_remove_member(
    request: Request, group_id: str, employee_id: str, user=Depends(get_mobile_user)
):
    """把一个 AI 员工移出群。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).remove_member(
            user_id=uid, group_id=group_id, employee_id=employee_id
        )
        return format_mobile_response(data={"group": group})
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_ai_group_remove_member")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.put("/ai-groups/{group_id}/pin")
async def mobile_ai_group_toggle_pin(
    request: Request, group_id: str, user=Depends(get_mobile_user)
):
    """切换群聊置顶状态。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).toggle_pinned(
            user_id=uid, group_id=group_id
        )
        return format_mobile_response(data={"group": group})
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_ai_group_toggle_pin")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.post("/ai-groups/{group_id}/mark-unread")
async def mobile_ai_group_mark_unread(
    request: Request, group_id: str, user=Depends(get_mobile_user)
):
    """标为未读（显示小红点）。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).mark_unread(
            user_id=uid, group_id=group_id
        )
        return format_mobile_response(data={"group": group})
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_ai_group_mark_unread")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.post("/ai-groups/{group_id}/mark-read")
async def mobile_ai_group_mark_read(request: Request, group_id: str, user=Depends(get_mobile_user)):
    """清除未读标记。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).mark_read(
            user_id=uid, group_id=group_id
        )
        return format_mobile_response(data={"group": group})
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_ai_group_mark_read")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.put("/ai-groups/{group_id}/followed")
async def mobile_ai_group_toggle_followed(
    request: Request, group_id: str, user=Depends(get_mobile_user)
):
    """切换是否关注（不再关注则不显示未读）。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).toggle_followed(
            user_id=uid, group_id=group_id
        )
        return format_mobile_response(data={"group": group})
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_ai_group_toggle_followed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.put("/ai-groups/{group_id}/hidden")
async def mobile_ai_group_toggle_hidden(
    request: Request, group_id: str, user=Depends(get_mobile_user)
):
    """切换是否隐藏（不显示/恢复显示该聊天）。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).toggle_hidden(
            user_id=uid, group_id=group_id
        )
        return format_mobile_response(data={"group": group})
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_ai_group_toggle_hidden")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.delete("/ai-groups/{group_id}")
async def mobile_ai_group_delete(request: Request, group_id: str, user=Depends(get_mobile_user)):
    """删除群聊。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        result = AiGroupChatService(mode=_mobile_group_mode(request)).delete_group(
            user_id=uid, group_id=group_id
        )
        return format_mobile_response(data=result)
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_ai_group_delete")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


# ── 会话状态管理（非群聊的个人 AI 会话） ──


def _conversation_state_uid(user: Any) -> int:
    uid = int(getattr(user, "id", 0) or 0)
    return uid if uid > 0 else 0


@extension_router.put("/conversations/{conversation_id}/pin")
async def mobile_conversation_toggle_pin(conversation_id: str, user=Depends(get_mobile_user)):
    uid = _conversation_state_uid(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.application.conversation_state_service import ConversationStateService

        return format_mobile_response(
            data=ConversationStateService().toggle_pinned(
                user_id=uid, conversation_id=conversation_id
            )
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_conversation_toggle_pin")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.post("/conversations/{conversation_id}/mark-unread")
async def mobile_conversation_mark_unread(conversation_id: str, user=Depends(get_mobile_user)):
    uid = _conversation_state_uid(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.application.conversation_state_service import ConversationStateService

        return format_mobile_response(
            data=ConversationStateService().mark_unread(
                user_id=uid, conversation_id=conversation_id
            )
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_conversation_mark_unread")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.post("/conversations/{conversation_id}/mark-read")
async def mobile_conversation_mark_read(conversation_id: str, user=Depends(get_mobile_user)):
    uid = _conversation_state_uid(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.application.conversation_state_service import ConversationStateService

        return format_mobile_response(
            data=ConversationStateService().mark_read(user_id=uid, conversation_id=conversation_id)
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_conversation_mark_read")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.put("/conversations/{conversation_id}/followed")
async def mobile_conversation_toggle_followed(conversation_id: str, user=Depends(get_mobile_user)):
    uid = _conversation_state_uid(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.application.conversation_state_service import ConversationStateService

        return format_mobile_response(
            data=ConversationStateService().toggle_followed(
                user_id=uid, conversation_id=conversation_id
            )
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_conversation_toggle_followed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.put("/conversations/{conversation_id}/hidden")
async def mobile_conversation_toggle_hidden(conversation_id: str, user=Depends(get_mobile_user)):
    uid = _conversation_state_uid(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.application.conversation_state_service import ConversationStateService

        return format_mobile_response(
            data=ConversationStateService().toggle_hidden(
                user_id=uid, conversation_id=conversation_id
            )
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_conversation_toggle_hidden")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


@extension_router.delete("/conversations/{conversation_id}")
async def mobile_conversation_delete(conversation_id: str, user=Depends(get_mobile_user)):
    uid = _conversation_state_uid(user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.application.conversation_state_service import ConversationStateService

        return format_mobile_response(
            data=ConversationStateService().delete(user_id=uid, conversation_id=conversation_id)
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile_conversation_delete")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500), status_code=500
        )


# ── MOD / 平台 / 首页 ──


@extension_router.get("/circle/posts")
async def mobile_ai_circle_posts(
    limit: int = Query(default=50, ge=1, le=100),
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.application.ai_circle_service import list_posts

    try:
        import importlib

        employee_circle_sync = importlib.import_module("app.application.employee_circle_sync")

        await employee_circle_sync.sync_modstore_reports()
    except Exception:  # noqa: BLE001 - 同步失败不影响交流圈展示
        logger.warning("circle: modstore report sync skipped", exc_info=True)

    uid, _, _ = _ai_circle_user(user)
    posts = list_posts(user_id=uid, limit=limit)
    profiles = _ai_circle_employee_profiles()
    for post in posts:
        profile = profiles.get(str(post.get("employee_id") or ""))
        if profile:
            post["author_name"] = profile["name"]
            post["author_avatar"] = profile["avatar"] or post.get("author_avatar")
    return format_mobile_response(data={"items": posts, "count": len(posts)})


@extension_router.post("/circle/posts")
async def mobile_ai_circle_create_post(
    body: AiCirclePostBody,
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.application.ai_circle_service import create_user_post

    uid, name, avatar = _ai_circle_user(user)
    try:
        post_id = create_user_post(user_id=uid, author_name=name, avatar=avatar, body=body.body)
        return format_mobile_response(data={"id": post_id}, message="发布成功")
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )


@extension_router.post("/circle/posts/{post_id}/like")
async def mobile_ai_circle_toggle_like(post_id: int, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.application.ai_circle_service import toggle_like

    uid, _, _ = _ai_circle_user(user)
    try:
        liked = toggle_like(post_id=post_id, user_id=uid)
        return format_mobile_response(data={"liked": liked})
    except LookupError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=404), status_code=404
        )


@extension_router.post("/circle/posts/{post_id}/comments")
async def mobile_ai_circle_add_comment(
    post_id: int,
    body: AiCircleCommentBody,
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.application.ai_circle_service import add_comment

    uid, name, _ = _ai_circle_user(user)
    try:
        comment_id = add_comment(post_id=post_id, user_id=uid, author_name=name, body=body.body)
        return format_mobile_response(data={"id": comment_id}, message="评论成功")
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )
    except LookupError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=404), status_code=404
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


@extension_router.get("/onboarding/industries", response_model=dict[str, Any])
async def mobile_onboarding_industries(request: Request, user=Depends(get_mobile_user)):
    """返回移动端首次开通可选行业目录。"""
    if user is None:
        return _mobile_unauthorized_response()
    try:
        from app.mod_sdk.industry_baseline import build_onboarding_industry_catalog_for_request

        data = await build_onboarding_industry_catalog_for_request(request)
        return format_mobile_response(data=data)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile onboarding industries failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.get("/onboarding/industry-baseline", response_model=dict[str, Any])
async def mobile_industry_baseline(
    request: Request,
    industry_id: str = Query(default="通用"),
    user=Depends(get_mobile_user),
):
    """返回指定行业的移动端初始化方案。"""
    if user is None:
        return _mobile_unauthorized_response()
    try:
        from app.mod_sdk.industry_baseline import build_industry_baseline_plan_for_request

        data = await build_industry_baseline_plan_for_request(request, industry_id)
        return format_mobile_response(data=data)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile industry baseline failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/onboarding/select-industry", response_model=dict[str, Any])
async def mobile_select_onboarding_industry(
    body: dict[str, Any],
    request: Request,
    user=Depends(get_mobile_user),
):
    """Persist the mobile onboarding industry selection to the shared workspace SSOT."""
    if user is None:
        return _mobile_unauthorized_response()
    industry_id = str(body.get("industry_id") or body.get("industryId") or "").strip()
    industry_mod_id = str(body.get("industry_mod_id") or body.get("industryModId") or "").strip()
    if not industry_id:
        return JSONResponse(
            format_mobile_response(None, "缺少 industry_id", success=False, code=400),
            status_code=400,
        )
    try:
        from app.application.tenant_workspace_prefs import bind_selected_industry_for_user
        from app.fastapi_routes.market_account import (
            grant_market_enterprise_entitlements_for_session,
        )

        data = bind_selected_industry_for_user(
            user,
            industry_id,
            industry_mod_id=industry_mod_id,
        )
        try:
            market_entitlements = await grant_market_enterprise_entitlements_for_session(
                _mobile_session_id_from_request(request),
                industry_id,
            )
        except RECOVERABLE_ERRORS as exc:
            logger.exception("mobile select onboarding industry market sync failed")
            market_entitlements = {"success": False, "message": str(exc)}
        if not market_entitlements.get("success"):
            logger.warning(
                "mobile onboarding industry saved while market entitlement sync failed: "
                "industry=%s message=%s",
                industry_id,
                market_entitlements.get("message"),
            )
        return format_mobile_response(
            data={**(data or {}), "market_entitlements": market_entitlements},
            message="行业已绑定到当前账号",
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile select onboarding industry failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/mod-store/install-host-foundation", response_model=dict[str, Any])
async def mobile_install_host_foundation(
    edition: str | None = Query(default=None),
    user=Depends(get_mobile_user),
):
    """为移动端账号安装宿主基础能力包。"""
    if user is None:
        return _mobile_unauthorized_response()
    try:
        from app.fastapi_routes.mod_store_routes import _install_host_foundation_internal

        result = await _install_host_foundation_internal(edition)
        return format_mobile_response(
            data=result.data,
            message=result.message,
            success=bool(result.success),
            code=200 if result.success else 409,
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile install host foundation failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/mod-store/install-industry-seed", response_model=dict[str, Any])
async def mobile_install_industry_seed(body: dict[str, Any], user=Depends(get_mobile_user)):
    """按行业安装移动端初始化种子包。"""
    if user is None:
        return _mobile_unauthorized_response()
    raw = str(body.get("industry_id") or body.get("industryId") or body.get("mod_id") or "").strip()
    if not raw:
        return JSONResponse(
            format_mobile_response(None, "缺少 industry_id", success=False, code=400),
            status_code=400,
        )
    try:
        from app.mod_sdk.industry_seed import install_industry_seed_with_fallback

        data = await install_industry_seed_with_fallback(raw)
        if data.get("success"):
            # 选行业即把所选行业持久化到账号(否则账号 industry_id 停留在注册默认「通用」)。
            selected_industry = str(data.get("industry_id") or "").strip()
            if selected_industry:
                from app.application.account_registration import set_account_industry

                set_account_industry(str(getattr(user, "username", "") or ""), selected_industry)
        return format_mobile_response(
            data=data,
            message=str(data.get("message") or ""),
            success=bool(data.get("success")),
            code=200 if data.get("success") else 409,
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile install industry seed failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/mod-store/install", response_model=dict[str, Any])
async def mobile_install_mod(body: dict[str, Any], user=Depends(get_mobile_user)):
    """从移动端安装指定市场 Mod。"""
    if user is None:
        return _mobile_unauthorized_response()
    mod_id = str(body.get("mod_id") or body.get("pkg_id") or body.get("package_file") or "").strip()
    if not mod_id:
        return JSONResponse(
            format_mobile_response(None, "缺少 mod_id", success=False, code=400),
            status_code=400,
        )
    try:
        from app.fastapi_routes.mod_store_routes import _install_from_catalog

        result = await _install_from_catalog(mod_id, "", activate=True)
        return format_mobile_response(
            data=result.data,
            message=result.message,
            success=bool(result.success),
            code=200 if result.success else 409,
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile install mod failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post(
    "/mod-store/install-customer-delivery-seed",
    response_model=dict[str, Any],
)
async def mobile_install_customer_delivery_seed(
    body: dict[str, Any],
    user=Depends(get_mobile_user),
):
    """安装客户交付场景的移动端种子包。"""
    if user is None:
        return _mobile_unauthorized_response()
    mod_id = str(body.get("mod_id") or body.get("pkg_id") or "").strip()
    industry_id = str(body.get("industry_id") or body.get("industryId") or "").strip()
    if not mod_id:
        return JSONResponse(
            format_mobile_response(None, "缺少 mod_id", success=False, code=400),
            status_code=400,
        )
    try:
        from app.mod_sdk.customer_delivery_seed import install_customer_delivery_seed_package

        data = await install_customer_delivery_seed_package(
            mod_id=mod_id,
            industry_id=industry_id,
        )
        return format_mobile_response(
            data=data,
            message=str(data.get("message") or ""),
            success=bool(data.get("success")),
            code=200 if data.get("success") else 409,
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile install customer delivery seed failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


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


# ── 侧栏菜单对齐（探索 Tab 配对后动态显示桌面端工具） ──

_CORE_NAV_ITEMS: list[dict[str, str]] = [
    {"key": "chat", "name": "智能对话", "icon": "fa-comments-o", "path": "/chat"},
    {"key": "im", "name": "信息", "icon": "fa-envelope-o", "path": "/im"},
    {"key": "ai-ecosystem", "name": "智能生态", "icon": "fa-sitemap", "path": "/ai-ecosystem"},
    {
        "key": "employee-workflow",
        "name": "员工工作台",
        "icon": "fa-users",
        "path": "/employee-workflow",
    },
    {"key": "products", "name": "业务对象", "icon": "fa-cubes", "path": "/products"},
    {"key": "customers", "name": "组织管理", "icon": "fa-users", "path": "/customers"},
    {"key": "orders", "name": "业务单据", "icon": "fa-file-text-o", "path": "/orders"},
    {
        "key": "shipment-records",
        "name": "业务记录",
        "icon": "fa-industry",
        "path": "/shipment-records",
    },
    {"key": "materials", "name": "资源库", "icon": "fa-archive", "path": "/materials"},
    {"key": "data-sources", "name": "数据来源", "icon": "fa-database", "path": "/data-sources"},
    {"key": "print", "name": "模板与打印", "icon": "fa-print", "path": "/print"},
    {"key": "settings", "name": "系统设置", "icon": "fa-cog", "path": "/settings"},
]

_ADMIN_NAV_ITEM = {
    "key": "admin-entitlements",
    "name": "用户管理",
    "icon": "fa-shield",
    "path": "/admin-entitlements",
}

# 角色 → 可见核心 key 白名单（None 表示全部可见）
_ROLE_VISIBLE_KEYS: dict[str, set[str] | None] = {
    "admin": None,  # 全部
    "enterprise": {
        "chat",
        "im",
        "ai-ecosystem",
        "employee-workflow",
        "products",
        "customers",
        "orders",
        "shipment-records",
        "materials",
        "data-sources",
        "print",
        "settings",
    },
    "personal": {"chat", "im", "ai-ecosystem", "settings"},
}


@extension_router.get("/nav-menu")
async def mobile_nav_menu(user=Depends(get_mobile_user)):
    """返回当前用户可见的侧栏菜单项（核心菜单 + Mod 菜单）。

    供手机端"探索"Tab 配对后动态渲染工具列表，与桌面端侧栏对齐。
    """
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )

    # 判断角色
    user_role = str(getattr(user, "role", "") or "").strip().lower()
    is_admin = user_role in {"admin", "super_admin", "owner"}
    account_kind = "admin" if is_admin else "enterprise"

    # 也可以从 session 获取 account_kind，这里简化用 role 判断
    visible_keys = _ROLE_VISIBLE_KEYS.get(account_kind)

    # 核心菜单
    items: list[dict[str, Any]] = []
    for item in _CORE_NAV_ITEMS:
        if visible_keys is not None and item["key"] not in visible_keys:
            continue
        items.append({**item, "source": "core"})

    # 管理员追加用户管理
    if is_admin:
        items.append({**_ADMIN_NAV_ITEM, "source": "core"})

    # Mod 菜单
    try:
        mod_items = _mobile_mod_items()
        for mod in mod_items:
            mod_id = str(mod.get("id") or "").strip()
            mod_name = str(mod.get("name") or mod_id).strip()
            frontend_menu = mod.get("frontend_menu") or mod.get("menu") or []
            if not isinstance(frontend_menu, list):
                continue
            for menu_entry in frontend_menu:
                if not isinstance(menu_entry, dict):
                    continue
                menu_id = str(menu_entry.get("id") or menu_entry.get("key") or "").strip()
                if not menu_id:
                    continue
                menu_label = str(
                    menu_entry.get("label") or menu_entry.get("name") or mod_name
                ).strip()
                menu_path = str(
                    menu_entry.get("path") or menu_entry.get("url") or f"/mod/{mod_id}"
                ).strip()
                menu_icon = str(
                    menu_entry.get("icon") or menu_entry.get("iconClass") or "fa-cube"
                ).strip()
                items.append(
                    {
                        "key": f"mod-{menu_id}" if not menu_id.startswith("mod-") else menu_id,
                        "name": menu_label,
                        "icon": menu_icon,
                        "path": menu_path,
                        "source": "mod",
                        "mod_id": mod_id,
                    }
                )
    except OPERATIONAL_ERRORS as exc:
        logger.warning("nav-menu mod items failed: %s", exc)

    return format_mobile_response(data={"items": items, "account_kind": account_kind})


# ── 同步 ──


def _mobile_sync_runtime_contract() -> dict[str, Any]:
    return {
        "source": "cloud",
        "sync_mode": "cloud",
        "standalone_supported": True,
        "desktop_required": False,
        "executor_required": False,
        "mobile_flow_parity": True,
        "offline_cache_supported": True,
        "desktop_executor": {
            "required": False,
            "role": "optional_local_executor",
            "required_for": ["local_files", "local_cli", "local_printing", "lan_devices"],
        },
    }


async def _mobile_sync_circle_posts(user: Any, *, limit: int = 50) -> list[dict[str, Any]]:
    try:
        import importlib

        from app.application.ai_circle_service import list_posts

        employee_circle_sync = importlib.import_module("app.application.employee_circle_sync")
        try:
            await employee_circle_sync.sync_modstore_reports()
        except Exception:  # noqa: BLE001 - 交流圈同步是拉取增强项，不能拖垮整次手机同步
            logger.warning("mobile sync: circle modstore report sync skipped", exc_info=True)

        uid, _, _ = _ai_circle_user(user)
        posts = list_posts(user_id=uid, limit=limit)
        profiles = _ai_circle_employee_profiles()
        for post in posts:
            profile = profiles.get(str(post.get("employee_id") or ""))
            if profile:
                post["author_name"] = profile["name"]
                post["author_avatar"] = profile["avatar"] or post.get("author_avatar")
        return posts
    except Exception as exc:  # noqa: BLE001 - 手机同步的其他数据不能被交流圈投影拖垮
        logger.warning("mobile sync: circle posts skipped: %s", exc)
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
    st.update(_mobile_sync_runtime_contract())
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
        circle_posts = await _mobile_sync_circle_posts(user, limit=50)
        approvals = _safe_mobile_sync_items("approvals", _approval_items)
        shipments = _safe_mobile_sync_items("shipments", _shipment_items)
        return format_mobile_response(
            data={
                **_mobile_sync_runtime_contract(),
                "cursor": cursor,
                "changes": changes,
                "im_changes": im_changes,
                "im_change_count": len(im_changes),
                "ai_changes": ai_changes,
                "ai_change_count": len(ai_changes),
                "circle_posts": circle_posts,
                "circle_post_count": len(circle_posts),
                "approvals": approvals,
                "shipments": shipments,
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


# ── 认证 ──


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
                import json as _json

                msg = _json.loads(err.body.decode("utf-8")).get("message") or msg
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


@extension_router.post("/auth/oidc/exchange")
async def mobile_auth_oidc_exchange(body: OidcExchangeBody):
    """Android Custom Tabs OIDC 回调换 mobile JWT。"""
    from app.application.auth_app_service import get_auth_app_service
    from app.application.enterprise_login_flow import finalize_auth_after_oidc
    from app.application.session_account_meta import normalize_account_kind
    from app.infrastructure.auth.oidc_provider import (
        exchange_oidc_authorization,
        verify_oidc_state,
    )
    from app.mod_sdk.product_skus import resolve_product_sku
    from app.security.mobile_jwt import issue_mobile_tokens

    ok, _rt = verify_oidc_state(body.state)
    if not ok:
        return JSONResponse(
            format_mobile_response(None, "OIDC state 无效", success=False, code=400),
            status_code=400,
        )
    try:
        oidc_session = await exchange_oidc_authorization(body.code)
        profile = (
            oidc_session.get("profile") if isinstance(oidc_session.get("profile"), dict) else {}
        )
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
    payload = await finalize_auth_after_oidc(
        auth_result=auth_result,
        oidc_profile=profile,
        oidc_access_token=str(oidc_session.get("access_token") or ""),
        account_kind=account_kind,
        sku=sku,
    )
    user_raw = payload.get("user") or {}
    tokens = issue_mobile_tokens(
        user_id=int(user_raw["id"]),
        session_id=str(session_id),
        account_kind=str(payload.get("account_kind") or account_kind),
        username=username,
    )
    data: dict[str, Any] = {
        "user": user_raw,
        "session_id": session_id,
        "account_kind": payload.get("account_kind") or account_kind,
        **tokens,
    }
    for key in (
        "market_access_token",
        "market_refresh_token",
        "company_brand",
        "market_is_admin",
        "market_is_enterprise",
    ):
        if key in payload and payload[key] is not None:
            data[key] = payload[key]
    return format_mobile_response(data=data)


# ── 联系人固定区组成（surface SSOT 派生） ──


@extension_router.get("/contacts/fixed")
async def get_mobile_fixed_contacts(request: Request, user=Depends(get_mobile_user)):
    """返回手机端联系人固定区(按端 SSOT 派生)。

    top/bottom 以平台员工为界:渲染顺序 = top + 平台员工(动态) + bottom。
    管理端不含专属客服(由 surface SSOT 自动 gating);两端均含小C与超级员工。
    """
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.application.surface_contacts import mobile_fixed_contacts

    return format_mobile_response(data=mobile_fixed_contacts(_mobile_group_mode(request)))


# ── 专属客服接口（企业版手机端） ──


@extension_router.get("/cs/info")
async def get_cs_info(request: Request, user=Depends(get_mobile_user)):
    """返回当前用户的小C/智能客服信息。"""
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    return format_mobile_response(
        data={
            "cs_available": True,
            "cs_name": "企业专属客服",
            "cs_avatar": None,
            "cs_online": True,
            "backend": "enterprise-cs",
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
    # 专属客服 = 企业客户↔运营者管理端的真实 IM 通道(与桌面端同源 enterprise-cs),不再复用小C LLM。
    # 客户消息写入 IM,运营者在管理端「客服收件箱」收到并以「企业专属客服」身份回复。
    uid = _mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db

    try:
        with get_db() as db:
            svc = ImApplicationService(db)
            cs = svc._ensure_enterprise_dedicated_cs_user()
            if cs is None or int(cs.id) == uid:
                return JSONResponse(
                    format_mobile_response(None, "客服通道不可用", success=False, code=500),
                    status_code=500,
                )
            conv = svc.get_or_create_direct(uid, int(cs.id))
            result = svc.send_message(int(conv["id"]), uid, msg_body)
        sent = result.get("message") or {}
        return format_mobile_response(
            data={
                "message_id": str(sent.get("id") or ""),
                # 真实客服:无 LLM 自动回复;客户端见空 reply 即 loadMessages 刷新等运营者回复。
                "reply": "",
                "backend": "enterprise-cs",
                "timestamp": str(sent.get("created_at") or ""),
            }
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile cs send via IM failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
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
    # 从 enterprise-cs 真实 IM 会话拉取消息(客户发的 + 运营者以「企业专属客服」回复的)。
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db

    uid = _mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    error = ""
    messages: list[dict[str, Any]] = []
    try:
        with get_db() as db:
            svc = ImApplicationService(db)
            cs = svc._ensure_enterprise_dedicated_cs_user()
            if cs is not None and int(cs.id) != uid:
                conv = svc.get_or_create_direct(uid, int(cs.id))
                raw = svc.list_messages(int(conv["id"]), uid, limit=100)
                messages = [
                    {
                        "messageId": str(m.get("id") or ""),
                        # 发送者是自己=user,否则=客服(运营者以 enterprise-cs 身份回复)。
                        "sender": "user" if int(m.get("sender_user_id") or 0) == uid else "cs",
                        "body": str(m.get("body") or ""),
                        "timestamp": str(m.get("created_at") or ""),
                    }
                    for m in raw
                ]
    except OPERATIONAL_ERRORS as exc:
        logger.warning("mobile cs message history (IM) unavailable: %s", exc)
        error = str(exc)[:300]
    if since:
        messages = [m for m in messages if str(m.get("timestamp") or "") > since]
    return format_mobile_response(data={"messages": messages, "persist_error": error})


# ── 钱包 / 余额 ──

_MOBILE_PAYMENT_CHANNELS: tuple[dict[str, str], ...] = (
    {
        "id": "mobile_h5",
        "title": "手机网页",
        "description": "统一收银台，适合 App 内或手机浏览器打开",
    },
    {
        "id": "alipay",
        "title": "支付宝",
        "description": "支付宝 H5 / 跳转支付，取决于市场侧配置",
    },
    {
        "id": "wechat_h5",
        "title": "微信支付",
        "description": "微信 H5 支付，取决于市场侧配置",
    },
)


def _normalize_mobile_payment_channel(raw: Any) -> str:
    value = str(raw or "").strip().lower().replace("-", "_")
    aliases = {
        "": "mobile_h5",
        "mobile": "mobile_h5",
        "h5": "mobile_h5",
        "wap": "mobile_h5",
        "alipay_h5": "alipay",
        "zhifubao": "alipay",
        "wechat": "wechat_h5",
        "weixin": "wechat_h5",
        "weixin_h5": "wechat_h5",
    }
    value = aliases.get(value, value)
    allowed = {item["id"] for item in _MOBILE_PAYMENT_CHANNELS}
    return value if value in allowed else "mobile_h5"


def _mobile_checkout_sign_body(body: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if body.get("plan_id"):
        out["plan_id"] = str(body.get("plan_id"))
    wallet_recharge = body.get("wallet_recharge")
    if wallet_recharge is True or str(wallet_recharge).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        out["wallet_recharge"] = True
        try:
            out["total_amount"] = float(body.get("total_amount") or 0)
        except (TypeError, ValueError):
            out["total_amount"] = 0.0
        out["subject"] = str(body.get("subject") or "钱包充值")
    for key in ("out_trade_no", "metadata"):
        if key in body:
            out[key] = body[key]
    return out


@extension_router.get("/payment/plans", response_model=dict[str, Any])
async def mobile_payment_plans(request: Request, user=Depends(get_mobile_user)):
    """返回移动端可购买套餐与支付渠道。"""
    if user is None:
        return _mobile_unauthorized_response()
    try:
        from app.fastapi_routes.market_account import _market_base_url, _proxy_json

        payload = await _proxy_json(
            "GET",
            "/api/payment/plans",
            authorization=_mobile_market_authorization(request, user),
            return_error_payload=True,
        )
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            status = int(payload.get("status_code") or 502)
            return JSONResponse(
                format_mobile_response(
                    payload.get("payload"), "套餐加载失败", success=False, code=status
                ),
                status_code=status,
            )
        if isinstance(payload, dict):
            payload = {
                **payload,
                "market_base_url": _market_base_url(),
                "payment_channels": list(_MOBILE_PAYMENT_CHANNELS),
            }
        return format_mobile_response(data=payload)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile payment plans failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.post("/payment/checkout", response_model=dict[str, Any])
async def mobile_payment_checkout(
    request: Request,
    body: dict[str, Any],
    user=Depends(get_mobile_user),
):
    """创建移动端支付订单并返回渠道下单参数。"""
    if user is None:
        return _mobile_unauthorized_response()
    authorization = _mobile_market_authorization(request, user)
    if not authorization:
        return JSONResponse(
            format_mobile_response(None, "尚未绑定市场账号；请重新登录", success=False, code=401),
            status_code=401,
        )
    try:
        from app.fastapi_routes.market_account import _proxy_json

        checkout_body = dict(body or {})
        checkout_body["channel"] = _normalize_mobile_payment_channel(checkout_body.get("channel"))
        checkout_body["client"] = str(checkout_body.get("client") or "android").strip()
        checkout_body.setdefault("return_url", "xcagi://payment/complete")
        signed = await _proxy_json(
            "POST",
            "/api/payment/sign-checkout",
            json_body=_mobile_checkout_sign_body(checkout_body),
            authorization=authorization,
            return_error_payload=True,
        )
        if isinstance(signed, dict) and signed.get("__proxy_error__"):
            status = int(signed.get("status_code") or 502)
            return JSONResponse(
                format_mobile_response(
                    signed.get("payload"), "支付签名失败", success=False, code=status
                ),
                status_code=status,
            )
        if isinstance(signed, dict):
            checkout_body.update(signed)
        payload = await _proxy_json(
            "POST",
            "/api/payment/checkout",
            json_body=checkout_body,
            authorization=authorization,
            return_error_payload=True,
        )
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            status = int(payload.get("status_code") or 502)
            return JSONResponse(
                format_mobile_response(
                    payload.get("payload"), "支付下单失败", success=False, code=status
                ),
                status_code=status,
            )
        return format_mobile_response(data=payload, message="下单成功")
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile payment checkout failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.get("/payment/query/{out_trade_no}", response_model=dict[str, Any])
async def mobile_payment_query(
    request: Request,
    out_trade_no: str,
    user=Depends(get_mobile_user),
):
    """查询移动端支付订单状态。"""
    if user is None:
        return _mobile_unauthorized_response()
    try:
        from app.fastapi_routes.market_account import _proxy_json

        payload = await _proxy_json(
            "GET",
            f"/api/payment/query/{out_trade_no}",
            authorization=_mobile_market_authorization(request, user),
            return_error_payload=True,
        )
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            status = int(payload.get("status_code") or 502)
            return JSONResponse(
                format_mobile_response(
                    payload.get("payload"), "订单查询失败", success=False, code=status
                ),
                status_code=status,
            )
        return format_mobile_response(data=payload)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mobile payment query failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@extension_router.get("/wallet/balance")
async def mobile_wallet_balance(request: Request, user=Depends(get_mobile_user)):
    """返回当前用户的市场钱包余额与会员信息（供移动端"我"页面展示）。

    数据来源：market ``/api/wallet/overview`` + ``/api/payment/my-plan``。
    任一上游不可用时返回降级空值，保持 200 以便客户端渲染占位 UI。
    """
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.fastapi_routes.market_account import (
        _auth_header,
        _market_base_url,
        _proxy_json,
        latest_session_market_token,
        session_market_token,
    )
    from app.security.mobile_jwt import verify_mobile_jwt

    # 1) 解析移动端 session_id，优先用 session 绑定的 market token
    sid = ""
    auth_hdr = request.headers.get("Authorization") or ""
    if auth_hdr.startswith("Bearer "):
        payload = verify_mobile_jwt(auth_hdr[7:].strip())
        if payload:
            sid = str(payload.get("session_id") or "")
    if not sid:
        from app.infrastructure.auth.dependencies import session_id_from_request

        sid = session_id_from_request(request)
    market_token = ""
    if sid:
        market_token = session_market_token(sid)
    if not market_token:
        # 多用户环境按 user_id 过滤，防止串号（fallback 仅用于单用户桌面模式）
        market_token = latest_session_market_token(user_id=getattr(user, "id", None))
    if not market_token:
        return format_mobile_response(
            data={
                "balance": None,
                "currency": "CNY",
                "membership_level": None,
                "experience": None,
                "byok_configured": False,
                "synced": False,
                "message": "尚未绑定市场账号",
            }
        )
    authorization = _auth_header(market_token)

    # 2) 拉取钱包概览
    wallet_payload = await _proxy_json(
        "GET", "/api/wallet/overview", authorization=authorization, return_error_payload=True
    )
    if isinstance(wallet_payload, dict) and wallet_payload.get("__proxy_error__"):
        # 降级：尝试 /api/wallet/balance
        wallet_payload = await _proxy_json(
            "GET", "/api/wallet/balance", authorization=authorization, return_error_payload=True
        )
    wallet_obj: dict[str, Any] = {}
    if isinstance(wallet_payload, dict) and not wallet_payload.get("__proxy_error__"):
        wallet_obj = (
            wallet_payload.get("wallet")
            if isinstance(wallet_payload.get("wallet"), dict)
            else wallet_payload
        )
    elif isinstance(wallet_payload, dict) and wallet_payload.get("__proxy_error__"):
        logger.warning(
            "mobile_wallet_balance: wallet overview unavailable: %s",
            wallet_payload.get("payload"),
        )

    # 3) 拉取套餐/会员信息
    plan_payload = await _proxy_json(
        "GET", "/api/payment/my-plan", authorization=authorization, return_error_payload=True
    )
    plan_obj: dict[str, Any] = {}
    if isinstance(plan_payload, dict) and not plan_payload.get("__proxy_error__"):
        plan_obj = plan_payload if isinstance(plan_payload, dict) else {}
    elif isinstance(plan_payload, dict) and plan_payload.get("__proxy_error__"):
        logger.warning(
            "mobile_wallet_balance: my-plan unavailable: %s",
            plan_payload.get("payload"),
        )

    # 4) 拉取 BYOK 状态
    llm_payload = await _proxy_json(
        "GET", "/api/llm/status", authorization=authorization, return_error_payload=True
    )
    byok_count = 0
    if isinstance(llm_payload, dict) and not llm_payload.get("__proxy_error__"):
        providers = llm_payload.get("providers") or []
        byok_count = len(
            [p for p in providers if isinstance(p, dict) and p.get("has_user_override")]
        )

    # 5) 组装简化余额信息
    balance_raw = wallet_obj.get("balance")
    try:
        balance_val = float(balance_raw) if balance_raw is not None else None
    except (TypeError, ValueError):
        balance_val = None
    membership = plan_obj.get("membership") if isinstance(plan_obj, dict) else None
    membership_level = None
    if isinstance(membership, dict):
        membership_level = (
            membership.get("level") or membership.get("name") or membership.get("tier")
        )
    elif isinstance(membership, str):
        membership_level = membership
    experience = None
    if isinstance(membership, dict):
        experience = membership.get("experience") or membership.get("exp")

    return format_mobile_response(
        data={
            "balance": balance_val,
            "currency": str(wallet_obj.get("currency") or "CNY"),
            "membership_level": membership_level,
            "experience": experience,
            "byok_configured": byok_count > 0,
            "byok_count": byok_count,
            "synced": balance_val is not None,
            "market_base_url": _market_base_url(),
        }
    )


# ──────────────────────────────────────────────────────────────────────
# 员工任务中心：手机端拉员工 Phase-D 主动提问 + 老板回答
# 通过 httpx 代理调 MODstore 后端 admin_employee_autonomy_api：
#   GET  /api/admin/employee-autonomy/questions
#   POST /api/admin/employee-autonomy/questions/{id}/answer
# 认证：MODSTORE_AUTH_TOKEN 环境变量（与 ModstoreAdapter 一致）
# ──────────────────────────────────────────────────────────────────────


def _modstore_platform_base() -> str:
    """获取 MODstore 后端 base url（如 http://127.0.0.1:8765）。"""
    return os.environ.get("MODSTORE_PLATFORM_URL", "http://localhost:8000").rstrip("/")


def _modstore_admin_token() -> str:
    """获取调 MODstore admin API 用的 Bearer token。"""
    return os.environ.get("MODSTORE_AUTH_TOKEN", "").strip()


async def _modstore_admin_proxy(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """通用代理：调 MODstore 后端 admin API。

    返回 {"ok": bool, "status": int, "data": ..., "error": str}。
    """
    import httpx

    url = f"{_modstore_platform_base()}{path}"
    headers = {"Accept": "application/json"}
    token = _modstore_admin_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, params=params, json=json_body, headers=headers)
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            data = {"raw": resp.text[:500]}
        if resp.is_success:
            return {"ok": True, "status": resp.status_code, "data": data}
        return {
            "ok": False,
            "status": resp.status_code,
            "error": str(data.get("detail") or data.get("error") or resp.text[:200])[:300],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": 0,
            "error": f"无法连接 MODstore 后端：{_compact_text(exc)[:200]}",
        }


@extension_router.get("/admin/employee-pending-questions")
async def mobile_admin_employee_pending_questions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    include_history: bool = Query(default=False),
    employee_id: str | None = Query(default=None),
    user=Depends(get_mobile_user),
):
    """拉员工 Phase-D 主动提问列表（pending 优先）。

    GET /api/mobile/v1/admin/employee-pending-questions
      ?limit=50&include_history=false&employee_id=llm-ops-engineer

    返回 {"items": [...], "count": N, "market_connected": bool}
    每个 item 含：id / employee_id / task / question / status / asked_at / answer / answered_at
    """
    meta, err = _require_mobile_admin(request, user)
    if err is not None:
        return err

    params: dict[str, Any] = {"limit": limit, "include_expired": bool(include_history)}
    if employee_id:
        params["employee_id"] = employee_id

    out = await _modstore_admin_proxy(
        "GET",
        "/api/admin/employee-autonomy/questions",
        params=params,
    )
    if not out.get("ok"):
        return format_mobile_response(
            None,
            f"拉员工提问失败：{out.get('error') or '未知错误'}",
            success=False,
            code=out.get("status") or 502,
        )
    data = out.get("data") if isinstance(out.get("data"), dict) else {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    return format_mobile_response(
        data={
            "items": items,
            "count": int(data.get("count") or len(items)),
            "market_connected": bool(out.get("ok")),
        }
    )


@extension_router.post("/admin/employee-pending-questions/{question_id}/answer")
async def mobile_admin_employee_pending_question_answer(
    question_id: int,
    body: dict[str, Any],
    request: Request,
    user=Depends(get_mobile_user),
):
    """老板回答员工的 Phase-D 提问。

    POST /api/mobile/v1/admin/employee-pending-questions/{id}/answer
    body: {"answer": "先做 A，因为..."}

    成功后员工执行管道被阻塞的 ask_human_blocking() 会拿到答案继续执行。
    """
    meta, err = _require_mobile_admin(request, user)
    if err is not None:
        return err

    answer_text = str((body or {}).get("answer") or "").strip()
    if not answer_text:
        return format_mobile_response(None, "answer 字段不能为空", success=False, code=400)

    out = await _modstore_admin_proxy(
        "POST",
        f"/api/admin/employee-autonomy/questions/{int(question_id)}/answer",
        json_body={"answer": answer_text},
    )
    if not out.get("ok"):
        return format_mobile_response(
            None,
            f"回答失败：{out.get('error') or '未知错误'}",
            success=False,
            code=out.get("status") or 502,
        )
    data = out.get("data") if isinstance(out.get("data"), dict) else {}
    return format_mobile_response(data=data)


# ──────────────────────────────────────────────────────────────────────
# 员工 chat（手机端流式）：让老板在 app 里直接和员工对话
# ──────────────────────────────────────────────────────────────────────


def _sse_line(payload: dict) -> bytes:
    """构造 SSE event line：data: {json}\\n\\n"""
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")


def _chunk_employee_reply(text: str) -> list[str]:
    """把员工完整回复切成 SSE chunk（按句号/换行，每块 <= 120 字）。"""
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?\n])", text)
    chunks: list[str] = []
    buf = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) > 120:
            if buf:
                chunks.append(buf)
            if len(p) > 120:
                chunks.append(p)
                buf = ""
            else:
                buf = p
        else:
            buf += p
    if buf:
        chunks.append(buf)
    return chunks or [text]


def _extract_employee_reply_text(result: dict) -> str:
    """从 execute_employee_task_local 返回值里提取回复文本。

    返回结构（参考 executor.py 范式）：{success: bool, result: {outputs: [...]}}
    """
    if not isinstance(result, dict):
        return ""
    if not result.get("success"):
        msg = result.get("message") or result.get("error")
        return f"⚠️ 员工执行失败：{msg or '未知错误'}"
    r = result.get("result") or {}
    if not isinstance(r, dict):
        return str(r) if r else ""
    outputs = r.get("outputs") or []
    if isinstance(outputs, list):
        for out in outputs:
            if not isinstance(out, dict):
                continue
            text = out.get("output") or out.get("summary") or out.get("text")
            if text:
                return str(text)
    for k in ("response", "output", "message", "text", "answer"):
        v = r.get(k)
        if v:
            return str(v)
    return str(r) if r else ""


@extension_router.post("/employees/{employee_id}/chat/stream")
async def mobile_employee_chat_stream(
    employee_id: str,
    request: Request,
    user=Depends(get_mobile_user),
    body: dict[str, Any] = Body(default_factory=dict),
):
    """员工 chat 流式接口（手机端）。

    POST /api/mobile/v1/employees/{employee_id}/chat/stream
    body: {"message": "...", "conversation_id": "employee:modId:employeeId"}

    内部调 execute_employee_task_local 跑员工 agent loop，
    然后把完整结果按句号 chunk emit 成 SSE token 流（伪流式）。
    """
    pid = str(employee_id or "").strip()
    if not pid:
        return JSONResponse(
            format_mobile_response(None, "employee_id 必填", success=False, code=400),
            status_code=400,
        )
    message = str((body or {}).get("message") or "").strip()
    if not message:
        return JSONResponse(
            format_mobile_response(None, "message 必填", success=False, code=400),
            status_code=400,
        )

    user_id = 0
    try:
        user_id = int(getattr(user, "id", 0) or 0)
    except (TypeError, ValueError):
        user_id = 0

    conversation_id = str((body or {}).get("conversation_id") or "").strip()
    payload = {
        "trigger": "mobile_chat",
        "source": "mobile",
        "conversation_id": conversation_id,
        "client_surface": "mobile",
    }

    async def sse_gen():
        try:
            yield _sse_line({"type": "token", "text": f"已连接员工 {pid}，正在思考..."})
            from app.application.employee_runtime.executor import execute_employee_task_local

            result = await asyncio.to_thread(
                execute_employee_task_local,
                pid,
                message,
                payload,
                user_id=user_id,
                workspace_root=None,
                session_id=f"mobile_chat_{user_id}",
            )
            final_text = _extract_employee_reply_text(result)
            if not final_text:
                final_text = "（员工未返回内容）"
            for chunk in _chunk_employee_reply(final_text):
                yield _sse_line({"type": "token", "text": chunk})
                await asyncio.sleep(0.05)
            yield _sse_line({"type": "done", "result": {"response": final_text}})
        except Exception as exc:
            logger.exception("mobile_employee_chat_stream failed: %s", exc)
            yield _sse_line({"type": "error", "message": f"员工对话失败：{exc}"})

    return StreamingResponse(
        sse_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
