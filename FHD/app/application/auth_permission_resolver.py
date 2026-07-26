"""统一权限解析：Mod entitlement + RBAC + account_kind。"""

from __future__ import annotations

import logging
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

ENTERPRISE_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "enterprise_owner": frozenset({"*"}),
    "enterprise_admin": frozenset(
        {"enterprise.read", "enterprise.write", "enterprise.manage_users", "employee.invoke"}
    ),
    "enterprise_operator": frozenset({"enterprise.read", "enterprise.write", "employee.invoke"}),
    "enterprise_viewer": frozenset({"enterprise.read"}),
}


def _normalize_account_kind(raw: Any) -> str:
    kind = str(raw or "").strip().lower()
    if kind in {"personal", "enterprise", "admin"}:
        return kind
    return "personal"


def resolve_enterprise_role(user: Any, session_meta: dict[str, Any] | None = None) -> str:
    meta = session_meta or {}
    explicit = str(meta.get("enterprise_role") or meta.get("rbac_role") or "").strip()
    if explicit:
        return explicit
    role = str(getattr(user, "role", "") or "").strip().lower()
    if role in ENTERPRISE_ROLE_PERMISSIONS:
        return role
    tier = str(getattr(user, "tier", "") or "").strip().lower()
    if tier == "enterprise":
        return "enterprise_owner"
    return "enterprise_viewer"


def resolve_permissions(
    *,
    user: Any,
    account_kind: str | None = None,
    session_meta: dict[str, Any] | None = None,
    mod_id: str | None = None,
    route: str | None = None,
) -> dict[str, Any]:
    """返回权限决策摘要，供路由/UI 共用。"""
    from app.application.session_account_meta import derive_account_kind_from_user

    # Login hints and session/JWT snapshots are context only. User.tier is the
    # identity authority for every permission decision.
    del account_kind
    kind = derive_account_kind_from_user(tier=getattr(user, "tier", None))
    meta = session_meta or {}
    enterprise_role = resolve_enterprise_role(user, meta) if kind == "enterprise" else ""
    perms = set(ENTERPRISE_ROLE_PERMISSIONS.get(enterprise_role, frozenset()))

    mod_allowed = True
    mod_reason = ""
    mid = str(mod_id or "").strip()
    if mid and kind == "enterprise":
        try:
            from app.enterprise.mod_entitlements import is_mod_visible_for_enterprise

            # Entitlements are restored into the authenticated desktop session
            # cache before this shared resolver runs.  Use the same visibility
            # SSOT as Mod discovery instead of calling a non-existent per-user
            # helper and failing every enterprise Mod closed.
            mod_allowed = is_mod_visible_for_enterprise(mid)
            if not mod_allowed:
                mod_reason = "mod_entitlement_required"
        except RECOVERABLE_ERRORS as exc:
            logger.warning("mod entitlement check failed mod=%s: %s", mid, exc)
            mod_allowed = False
            mod_reason = "mod_entitlement_check_failed"

    route_allowed = True
    route_reason = ""
    r = str(route or "").strip()
    if (r.startswith("/api/admin") or r.startswith("/api/xcmax-admin")) and kind != "admin":
        route_allowed = False
        route_reason = "admin_only"
    elif "employee" in r and r.endswith("/execute"):
        if kind == "admin":
            route_allowed = True
        else:
            route_allowed = "employee.invoke" in perms or "*" in perms
            if not route_allowed:
                route_reason = "employee_invoke_denied"

    personal_blocked_shell = False
    admin_blocked_shell = False
    shell = str(meta.get("client_shell") or meta.get("shell") or "").strip().lower()
    if kind == "personal" and shell in {"desktop", "mobile", "android"}:
        personal_blocked_shell = True
    # 桌面进程整机禁 admin（不依赖未接线的 client_shell=desktop）
    if kind == "admin":
        try:
            from app.application.desktop_admin_gate import is_desktop_runtime

            admin_blocked_shell = bool(is_desktop_runtime())
        except Exception:  # noqa: BLE001
            admin_blocked_shell = shell in {"desktop"}

    return {
        "account_kind": kind,
        "enterprise_role": enterprise_role,
        "permissions": sorted(perms),
        "mod_id": mid or None,
        "mod_allowed": mod_allowed,
        "mod_reason": mod_reason,
        "route": r or None,
        "route_allowed": route_allowed,
        "route_reason": route_reason,
        "personal_shell_blocked": personal_blocked_shell,
        "admin_shell_blocked": admin_blocked_shell,
        "allowed": route_allowed
        and mod_allowed
        and not personal_blocked_shell
        and not admin_blocked_shell,
    }


def require_allowed(**kwargs: Any) -> None:
    decision = resolve_permissions(**kwargs)
    if not decision.get("allowed"):
        from fastapi import HTTPException

        reason = (
            decision.get("route_reason")
            or decision.get("mod_reason")
            or ("personal_shell_blocked" if decision.get("personal_shell_blocked") else None)
            or ("admin_shell_blocked" if decision.get("admin_shell_blocked") else None)
            or "forbidden"
        )
        raise HTTPException(status_code=403, detail=str(reason))
