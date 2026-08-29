"""Purchased-account SSOT projected as standard desktop deliveries."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from modstore_server.account_license_plans import account_license_plan
from modstore_server.api.deps import get_db, require_admin
from modstore_server.db.delivery_commerce import UpdateInstallationReceipt
from modstore_server.models import Entitlement, User, UserPlan

router = APIRouter(prefix="/api/admin/customer-deliveries", tags=["admin-delivery"])


def _iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _entitlement_plan_id(row: Entitlement) -> str:
    try:
        payload = json.loads(str(row.metadata_json or "{}"))
    except (TypeError, ValueError):
        payload = {}
    return str(payload.get("plan_id") or "").strip() if isinstance(payload, dict) else ""


def _permanent_plan_rows(db: Session) -> list[UserPlan]:
    rows = (
        db.query(UserPlan)
        .filter(UserPlan.is_active.is_(True))
        .order_by(UserPlan.user_id.asc(), UserPlan.id.desc())
        .all()
    )
    latest_by_user: dict[int, UserPlan] = {}
    for row in rows:
        plan = account_license_plan(str(row.plan_id or "")) or {}
        if str(plan.get("license_type") or "") != "permanent":
            continue
        latest_by_user.setdefault(int(row.user_id), row)
    return list(latest_by_user.values())


def build_standard_delivery_rows(db: Session) -> list[dict[str, Any]]:
    """Return one real standard delivery per active permanent account.

    Account creation starts the delivery.  It completes automatically only when
    the same purchased account has both a successful desktop installation
    receipt and a successful first login timestamp.
    """

    plan_rows = _permanent_plan_rows(db)
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
    latest_receipt_by_user: dict[int, UpdateInstallationReceipt] = {}
    installed_receipt_by_user: dict[int, UpdateInstallationReceipt] = {}
    installed_devices_by_user: dict[int, set[str]] = {}
    for receipt in receipts:
        uid = int(receipt.user_id)
        latest_receipt_by_user.setdefault(uid, receipt)
        if str(receipt.status or "") == "installed":
            installed_receipt_by_user.setdefault(uid, receipt)
            installed_devices_by_user.setdefault(uid, set()).add(str(receipt.installation_id or ""))

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
        latest = latest_receipt_by_user.get(uid)
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
            status_label = "账号已创建，待安装"
        completed_at = ""
        if install_ok and first_login_ok:
            completed_at = max(
                _iso(installed.reported_at),
                _iso(first_login_at),
            )
        receipt_payload = None
        if latest is not None:
            receipt_payload = {
                "installation_id": str(latest.installation_id or ""),
                "platform": str(latest.platform or ""),
                "installed_version": str(latest.installed_version or ""),
                "installed_build_sha": str(latest.installed_build_sha or ""),
                "status": str(latest.status or ""),
                "source": str(latest.source or ""),
                "reported_at": _iso(latest.reported_at),
                "error": str(latest.error or ""),
            }
        result.append(
            {
                "delivery_no": f"STD-{order_no or f'U{uid}-P{plan_row.id}'}",
                "delivery_type": "standard_desktop",
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
                    "license_type": "permanent",
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
                    "latest_receipt": receipt_payload,
                },
                "first_login": {"ok": first_login_ok, "at": _iso(first_login_at)},
                "completion_rule": "installed_and_first_login",
                "available_installers": ["macOS", "Windows"],
            }
        )
    return sorted(result, key=lambda row: (row["status"] == "completed", row["started_at"]))


@router.get("/standard")
def list_standard_deliveries(
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    rows = build_standard_delivery_rows(db)
    rows = rows[:limit]
    return {
        "items": rows,
        "total": len(rows),
        "summary": {
            "purchased_accounts": len(rows),
            "pending_install": sum(1 for row in rows if row["status"] == "pending_install"),
            "pending_first_login": sum(1 for row in rows if row["status"] == "pending_first_login"),
            "completed": sum(1 for row in rows if row["status"] == "completed"),
        },
        "ssot": "active_permanent_user_plan",
    }


__all__ = ["build_standard_delivery_rows", "router"]
