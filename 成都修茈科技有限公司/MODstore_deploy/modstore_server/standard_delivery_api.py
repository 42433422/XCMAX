"""Purchased-account SSOT projected as standard desktop deliveries."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from modstore_server.account_license_plans import account_license_plan
from modstore_server.api.deps import get_db, require_admin
from modstore_server.db.delivery_commerce import UpdateInstallationReceipt
from modstore_server.models import Entitlement, User, UserPlan

router = APIRouter(prefix="/api/admin/customer-deliveries", tags=["admin-delivery"])

_INSTALLATION_ID_SPLIT_RE = re.compile(r"[\s,;]+")


def configured_internal_installation_ids() -> set[str]:
    """Return founder/internal desktop installation IDs without exposing them.

    A login on one of these installations may activate an account, but it must
    never be treated as customer-side delivery evidence.
    """

    raw = os.environ.get("MODSTORE_INTERNAL_INSTALLATION_IDS", "")
    return {
        token.casefold()
        for token in _INSTALLATION_ID_SPLIT_RE.split(raw.strip())
        if 16 <= len(token) <= 64
    }


def _is_internal_installation(installation_id: str, internal_ids: set[str]) -> bool:
    return installation_id.strip().casefold() in internal_ids


def _iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    normalized: datetime = value
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=UTC)
    return str(normalized.astimezone(UTC).isoformat())


def _receipt_payload(
    receipt: UpdateInstallationReceipt,
    internal_ids: set[str],
) -> dict[str, Any]:
    installation_id = str(receipt.installation_id or "")
    return {
        "installation_id": installation_id,
        "platform": str(receipt.platform or ""),
        "installed_version": str(receipt.installed_version or ""),
        "installed_build_sha": str(receipt.installed_build_sha or ""),
        "status": str(receipt.status or ""),
        "source": str(receipt.source or ""),
        "reported_at": _iso(receipt.reported_at),
        "error": str(receipt.error or ""),
        "device_scope": (
            "internal"
            if _is_internal_installation(installation_id, internal_ids)
            else "customer"
        ),
    }


def _entitlement_plan_id(row: Entitlement) -> str:
    try:
        payload = json.loads(str(row.metadata_json or "{}"))
    except (TypeError, ValueError):
        payload = {}
    return str(payload.get("plan_id") or "").strip() if isinstance(payload, dict) else ""


def _purchased_plan_rows(db: Session, license_type: str) -> list[UserPlan]:
    rows = (
        db.query(UserPlan)
        .filter(UserPlan.is_active.is_(True))
        .order_by(UserPlan.user_id.asc(), UserPlan.id.desc())
        .all()
    )
    latest_by_user: dict[int, UserPlan] = {}
    for row in rows:
        plan = account_license_plan(str(row.plan_id or "")) or {}
        if str(plan.get("license_type") or "") != license_type:
            continue
        latest_by_user.setdefault(int(row.user_id), row)
    return list(latest_by_user.values())


def _build_delivery_rows(db: Session, license_type: str) -> list[dict[str, Any]]:
    """Return one real desktop delivery per active purchased account.

    Account creation starts the delivery.  It completes automatically only when
    the same purchased account has both a successful customer-side desktop
    installation receipt and a successful first login timestamp.  Receipts from
    configured founder/internal installations are retained as evidence but are
    excluded from delivery completion.
    """

    plan_rows = _purchased_plan_rows(db, license_type)
    user_ids = [int(row.user_id) for row in plan_rows]
    if not user_ids:
        return []

    users = {int(row.id): row for row in db.query(User).filter(User.id.in_(user_ids)).all()}
    entitlements = (
        db.query(Entitlement)
        .filter(
            Entitlement.user_id.in_(user_ids),
            Entitlement.entitlement_type == "plan",
            Entitlement.is_active.is_(True),
        )
        .order_by(Entitlement.user_id.asc(), Entitlement.id.desc())
        .all()
    )
    entitlement_by_key: dict[tuple[int, str], Entitlement] = {}
    for row in entitlements:
        entitlement_by_key.setdefault((int(row.user_id), _entitlement_plan_id(row)), row)

    receipts = (
        db.query(UpdateInstallationReceipt)
        .filter(UpdateInstallationReceipt.user_id.in_(user_ids))
        .order_by(
            UpdateInstallationReceipt.reported_at.desc(),
            UpdateInstallationReceipt.id.desc(),
        )
        .all()
    )
    internal_ids = configured_internal_installation_ids()
    latest_receipt_by_user: dict[int, UpdateInstallationReceipt] = {}
    latest_customer_receipt_by_user: dict[int, UpdateInstallationReceipt] = {}
    installed_receipt_by_user: dict[int, UpdateInstallationReceipt] = {}
    installed_devices_by_user: dict[int, set[str]] = {}
    internal_devices_by_user: dict[int, set[str]] = {}
    for receipt in receipts:
        uid = int(receipt.user_id)
        latest_receipt_by_user.setdefault(uid, receipt)
        installation_id = str(receipt.installation_id or "").strip()
        is_internal = _is_internal_installation(installation_id, internal_ids)
        if not is_internal:
            latest_customer_receipt_by_user.setdefault(uid, receipt)
        if str(receipt.status or "") == "installed":
            if is_internal:
                internal_devices_by_user.setdefault(uid, set()).add(installation_id)
                continue
            installed_receipt_by_user.setdefault(uid, receipt)
            installed_devices_by_user.setdefault(uid, set()).add(installation_id)

    result: list[dict[str, Any]] = []
    for plan_row in plan_rows:
        uid = int(plan_row.user_id)
        user = users.get(uid)
        if user is None:
            continue
        plan_id = str(plan_row.plan_id or "")
        plan = account_license_plan(plan_id) or {}
        entitlement = entitlement_by_key.get((uid, plan_id))
        order_no = str(getattr(entitlement, "source_order_id", "") or "").strip()
        installed = installed_receipt_by_user.get(uid)
        latest = latest_customer_receipt_by_user.get(uid) or latest_receipt_by_user.get(uid)
        first_login_at = getattr(user, "first_login_at", None)
        install_ok = installed is not None
        first_login_ok = first_login_at is not None
        if install_ok and first_login_ok:
            status = "completed"
            status_label = "安装并首次登录完成"
        elif install_ok:
            status = "pending_first_login"
            status_label = "已安装，待首次登录"
        else:
            status = "pending_install"
            status_label = (
                "内部本机已排除，待客户设备安装"
                if internal_devices_by_user.get(uid)
                else "账号已创建，待客户设备安装"
            )
        completed_at = ""
        if installed is not None and first_login_at is not None:
            completed_at = max(
                _iso(installed.reported_at),
                _iso(first_login_at),
            )
        receipt_payload = _receipt_payload(latest, internal_ids) if latest is not None else None
        installed_receipt_payload = (
            _receipt_payload(installed, internal_ids) if installed is not None else None
        )
        result.append(
            {
                "delivery_no": f"STD-{order_no or f'U{uid}-P{plan_row.id}'}",
                "delivery_type": "standard_desktop",
                "license_type": license_type,
                "expires_at": _iso(plan_row.expires_at),
                "status": status,
                "status_label": status_label,
                "started_at": _iso(getattr(user, "created_at", None)),
                "activated_at": _iso(plan_row.started_at),
                "completed_at": completed_at,
                "account": {
                    "id": uid,
                    "username": str(user.username or ""),
                    "email": str(user.email or ""),
                    "is_enterprise": bool(getattr(user, "is_enterprise", False)),
                    "account_state": str(getattr(user, "account_state", "") or ""),
                    "first_login_at": _iso(first_login_at),
                    "last_login_at": _iso(getattr(user, "last_login_at", None)),
                },
                "plan": {
                    "id": plan_id,
                    "title": str(plan.get("title") or plan_id),
                    "account_tier": str(plan.get("account_tier") or "normal"),
                    "license_type": license_type,
                    "amount_cents": int(plan.get("amount_cents") or 0),
                },
                "order": {
                    "order_no": order_no,
                    "status": "entitlement_granted" if entitlement else "",
                    "total_amount": "",
                    "paid_at": _iso(getattr(entitlement, "granted_at", None)),
                    "entitlement_id": int(entitlement.id) if entitlement else None,
                },
                "install": {
                    "ok": install_ok,
                    "installed_devices": len(installed_devices_by_user.get(uid, set())),
                    "customer_installed_devices": len(installed_devices_by_user.get(uid, set())),
                    "internal_devices_excluded": len(internal_devices_by_user.get(uid, set())),
                    "scope": "customer_external_desktop",
                    "latest_receipt": receipt_payload,
                    "latest_installed_receipt": installed_receipt_payload,
                },
                "first_login": {"ok": first_login_ok, "at": _iso(first_login_at)},
                "completion_rule": "customer_desktop_installed_and_first_login",
                "available_installers": ["macOS", "Windows"],
            }
        )
    return sorted(result, key=lambda row: (row["status"] == "completed", row["started_at"]))


def build_standard_delivery_rows(db: Session) -> list[dict[str, Any]]:
    """Permanent purchased accounts projected as standard desktop deliveries."""

    return _build_delivery_rows(db, "permanent")


def build_trial_delivery_rows(db: Session) -> list[dict[str, Any]]:
    """¥99 trial (saas-trial-30) accounts projected as trial desktop deliveries."""

    return _build_delivery_rows(db, "trial")


def _delivery_response(rows: list[dict[str, Any]], limit: int, ssot: str) -> dict[str, Any]:
    rows = rows[:limit]
    internal_ids = configured_internal_installation_ids()
    return {
        "items": rows,
        "total": len(rows),
        "summary": {
            "purchased_accounts": len(rows),
            "pending_install": sum(1 for row in rows if row["status"] == "pending_install"),
            "pending_first_login": sum(1 for row in rows if row["status"] == "pending_first_login"),
            "completed": sum(1 for row in rows if row["status"] == "completed"),
            "customer_installed_devices": sum(
                int(row["install"]["customer_installed_devices"]) for row in rows
            ),
            "internal_receipts_excluded": sum(
                int(row["install"]["internal_devices_excluded"]) for row in rows
            ),
            "internal_device_ids_configured": len(internal_ids),
        },
        "ssot": ssot,
        "policy": {
            "id": "customer_external_desktop_delivery",
            "completion_rule": "customer_desktop_installed_and_first_login",
            "internal_device_exclusion_enabled": bool(internal_ids),
            "internal_device_ids_configured": len(internal_ids),
            "login_only_counts_as_installation": False,
        },
    }


@router.get("/standard")
def list_standard_deliveries(
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    return _delivery_response(build_standard_delivery_rows(db), limit, "active_permanent_user_plan")


@router.get("/trial")
def list_trial_deliveries(
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    return _delivery_response(build_trial_delivery_rows(db), limit, "active_trial_user_plan")


__all__ = [
    "build_standard_delivery_rows",
    "build_trial_delivery_rows",
    "configured_internal_installation_ids",
    "router",
]
