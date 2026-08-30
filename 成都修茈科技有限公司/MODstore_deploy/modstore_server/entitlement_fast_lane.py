"""Audited administrator fast lane for account and membership plans.

The fast lane intentionally does not create orders, payments, wallet credits, or
transactions.  It only changes the plan/entitlement SSOT and records the full
before/after state in ``commerce_admin_actions``.  Both the HTTP API and the
operator CLI call this module so their safety and idempotency rules cannot drift.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modstore_server.account_license_plans import (
    ACCOUNT_LICENSE_PLANS,
    account_license_plan,
    is_account_license_plan_id,
)
from modstore_server.account_lifecycle import ACCOUNT_ACTIVE, ACCOUNT_PENDING_PLAN
from modstore_server.db.delivery_commerce import CommerceAdminAction
from modstore_server.models import Entitlement, PlanTemplate, Quota, User, UserPlan


class FastLaneError(ValueError):
    """Base error exposed as a safe operator-facing validation message."""


class FastLaneNotFound(FastLaneError):
    """Requested account or plan does not exist."""


class FastLaneConflict(FastLaneError):
    """An idempotency key was reused for a different request."""


class FastLaneForbidden(FastLaneError):
    """The selected actor is not an administrator."""


def _iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()


def _metadata(row: Entitlement) -> dict[str, Any]:
    try:
        payload = json.loads(str(row.metadata_json or "{}"))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_account(db: Session, account: str | int) -> User:
    """Resolve an account by numeric id, username, or email."""

    raw = str(account or "").strip()
    if not raw:
        raise FastLaneNotFound("账号不能为空")
    row: User | None = None
    if raw.isdigit():
        row = db.query(User).filter(User.id == int(raw)).first()
    if row is None:
        needle = raw.lower()
        row = (
            db.query(User)
            .filter(
                (func.lower(User.username) == needle)
                | (func.lower(User.email) == needle)
            )
            .first()
        )
    if row is None:
        raise FastLaneNotFound(f"账号不存在：{raw}")
    return row


def require_admin_actor(db: Session, actor: User | str | int) -> User:
    row = actor if isinstance(actor, User) else resolve_account(db, actor)
    if not bool(row.is_admin):
        raise FastLaneForbidden(f"操作人不是管理员：{row.username}")
    return row


def list_fast_lane_plans(db: Session) -> list[dict[str, Any]]:
    """Return every active plan with catalog and duration semantics."""

    rows = db.query(PlanTemplate).filter(PlanTemplate.is_active.is_(True)).all()
    result: list[dict[str, Any]] = []
    for row in rows:
        license_meta = account_license_plan(str(row.id or "")) or {}
        is_license = bool(license_meta)
        result.append(
            {
                "id": str(row.id),
                "title": str(license_meta.get("title") or row.name or row.id),
                "description": str(license_meta.get("description") or row.description or ""),
                "catalog": "account_license" if is_license else "membership",
                "license_type": str(
                    license_meta.get("license_type") or "membership"
                ),
                "account_tier": str(license_meta.get("account_tier") or ""),
                "duration_days": int(
                    license_meta.get("duration_days") or (0 if is_license else 30)
                ),
                "price": str(Decimal(str(row.price or 0)).quantize(Decimal("0.01"))),
            }
        )
    catalog_rank = {"account_license": 0, "membership": 1}
    license_rank = {
        str(plan["id"]): index for index, plan in enumerate(ACCOUNT_LICENSE_PLANS)
    }
    return sorted(
        result,
        key=lambda item: (
            catalog_rank.get(str(item["catalog"]), 9),
            license_rank.get(str(item["id"]), 999),
            str(item["id"]),
        ),
    )


def _active_plan_snapshot(db: Session, user_id: int) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    rows = (
        db.query(UserPlan, PlanTemplate)
        .join(PlanTemplate, PlanTemplate.id == UserPlan.plan_id)
        .filter(
            UserPlan.user_id == int(user_id),
            UserPlan.is_active.is_(True),
            or_(UserPlan.expires_at.is_(None), UserPlan.expires_at > now),
        )
        .order_by(UserPlan.id.asc())
        .all()
    )
    return [
        {
            "user_plan_id": int(user_plan.id),
            "plan_id": str(user_plan.plan_id),
            "title": str(
                (account_license_plan(str(user_plan.plan_id)) or {}).get("title")
                or plan.name
                or user_plan.plan_id
            ),
            "catalog": (
                "account_license"
                if is_account_license_plan_id(str(user_plan.plan_id))
                else "membership"
            ),
            "started_at": _iso(user_plan.started_at),
            "expires_at": _iso(user_plan.expires_at),
            "auto_renew": bool(user_plan.auto_renew),
        }
        for user_plan, plan in rows
    ]


def account_fast_lane_status(db: Session, account: str | int) -> dict[str, Any]:
    user = resolve_account(db, account)
    return {
        "account": {
            "id": int(user.id),
            "username": str(user.username or ""),
            "email": str(user.email or ""),
            "is_admin": bool(user.is_admin),
            "is_enterprise": bool(getattr(user, "is_enterprise", False)),
            "account_state": str(getattr(user, "account_state", "") or ""),
        },
        "active_plans": _active_plan_snapshot(db, int(user.id)),
        "commerce": {
            "order_generated": False,
            "payment_generated": False,
            "transaction_generated": False,
        },
    }


def _deactivate_plan_entitlements(db: Session, user_id: int, plan_ids: set[str]) -> None:
    if not plan_ids:
        return
    rows = (
        db.query(Entitlement)
        .filter(
            Entitlement.user_id == int(user_id),
            Entitlement.entitlement_type == "plan",
            Entitlement.is_active.is_(True),
        )
        .all()
    )
    for row in rows:
        if str(_metadata(row).get("plan_id") or "") in plan_ids:
            row.is_active = False
            db.add(row)


def _reset_plan_quotas(
    db: Session,
    *,
    user_id: int,
    plan: PlanTemplate,
    reset_at: datetime | None,
) -> None:
    try:
        quotas = json.loads(str(plan.quotas_json or "{}"))
    except (TypeError, ValueError):
        quotas = {}
    if not isinstance(quotas, dict):
        return
    for quota_type, raw_total in quotas.items():
        try:
            total = max(0, int(raw_total))
        except (TypeError, ValueError):
            continue
        row = (
            db.query(Quota)
            .filter(Quota.user_id == int(user_id), Quota.quota_type == str(quota_type))
            .first()
        )
        if row is None:
            row = Quota(
                user_id=int(user_id),
                quota_type=str(quota_type),
                total=total,
                used=0,
            )
        else:
            row.total = total
            row.used = 0
        row.reset_at = reset_at
        db.add(row)


def _existing_action(db: Session, idempotency_key: str) -> CommerceAdminAction | None:
    return (
        db.query(CommerceAdminAction)
        .filter(CommerceAdminAction.idempotency_key == idempotency_key)
        .first()
    )


def _replay_or_conflict(
    row: CommerceAdminAction,
    *,
    actor_id: int,
    action: str,
    account_id: int,
    plan_id: str,
    reason: str,
    duration_days: int | None,
) -> dict[str, Any]:
    try:
        payload = json.loads(str(row.after_json or "{}"))
    except (TypeError, ValueError):
        payload = {}
    fingerprint = payload.get("request") if isinstance(payload, dict) else {}
    expected = {
        "actor_user_id": int(actor_id),
        "action": action,
        "account_id": int(account_id),
        "plan_id": plan_id,
        "reason": reason,
        "duration_days": duration_days,
    }
    if row.action not in {"fast_lane_assign_plan", "fast_lane_revoke_plan"} or fingerprint != expected:
        raise FastLaneConflict("幂等键已被其他操作使用")
    result = dict(payload)
    result["duplicate"] = True
    return result


def apply_fast_lane_action(
    db: Session,
    *,
    actor: User | str | int,
    account: str | int,
    action: str,
    plan_id: str,
    reason: str,
    idempotency_key: str,
    duration_days: int | None = None,
) -> dict[str, Any]:
    """Assign/replace or revoke one plan and append an immutable audit row."""

    normalized_action = str(action or "").strip().lower()
    if normalized_action == "grant":
        normalized_action = "assign"
    if normalized_action not in {"assign", "revoke"}:
        raise FastLaneError("操作仅支持 assign/grant 或 revoke")
    normalized_plan_id = str(plan_id or "").strip()
    normalized_reason = str(reason or "").strip()
    normalized_key = str(idempotency_key or "").strip()
    if len(normalized_reason) < 4:
        raise FastLaneError("必须填写至少 4 个字的操作原因")
    if len(normalized_key) < 12:
        raise FastLaneError("幂等键至少 12 个字符")
    if not normalized_plan_id:
        raise FastLaneError("必须指定 plan_id")

    actor_row = require_admin_actor(db, actor)
    target = resolve_account(db, account)
    plan = (
        db.query(PlanTemplate)
        .filter(
            PlanTemplate.id == normalized_plan_id,
            PlanTemplate.is_active.is_(True),
        )
        .first()
    )
    if plan is None:
        raise FastLaneNotFound(f"套餐不存在或已停用：{normalized_plan_id}")

    is_license = is_account_license_plan_id(normalized_plan_id)
    license_meta = account_license_plan(normalized_plan_id) or {}
    fixed_days = int(license_meta.get("duration_days") or 0)
    if normalized_action == "revoke":
        normalized_duration_days: int | None = None
    elif is_license:
        normalized_duration_days = fixed_days or None
    else:
        normalized_duration_days = int(duration_days or 30)
        if normalized_duration_days < 1 or normalized_duration_days > 3650:
            raise FastLaneError("会员权益有效天数必须在 1–3650 之间")

    existing = _existing_action(db, normalized_key)
    if existing is not None:
        return _replay_or_conflict(
            existing,
            actor_id=int(actor_row.id),
            action=normalized_action,
            account_id=int(target.id),
            plan_id=normalized_plan_id,
            reason=normalized_reason,
            duration_days=normalized_duration_days,
        )

    before = account_fast_lane_status(db, int(target.id))
    now = datetime.now(UTC)
    changed_plan_ids: set[str] = set()

    try:
        if normalized_action == "assign":
            active_rows = (
                db.query(UserPlan)
                .filter(UserPlan.user_id == int(target.id), UserPlan.is_active.is_(True))
                .with_for_update()
                .all()
            )
            for row in active_rows:
                if is_account_license_plan_id(str(row.plan_id)) is is_license:
                    row.is_active = False
                    changed_plan_ids.add(str(row.plan_id))
                    db.add(row)
            _deactivate_plan_entitlements(db, int(target.id), changed_plan_ids)

            effective_days = normalized_duration_days or 0
            expires_at = now + timedelta(days=effective_days) if effective_days else None
            db.add(
                UserPlan(
                    user_id=int(target.id),
                    plan_id=normalized_plan_id,
                    started_at=now,
                    expires_at=expires_at,
                    is_active=True,
                    auto_renew=False,
                )
            )
            db.add(
                Entitlement(
                    user_id=int(target.id),
                    entitlement_type="plan",
                    source_order_id="",
                    metadata_json=json.dumps(
                        {
                            "plan_id": normalized_plan_id,
                            "source": "admin_entitlement_fast_lane",
                            "idempotency_key": normalized_key,
                        },
                        ensure_ascii=False,
                    ),
                    granted_at=now,
                    expires_at=expires_at,
                    is_active=True,
                )
            )
            if is_license:
                target.account_state = ACCOUNT_ACTIVE
                db.add(target)
            _reset_plan_quotas(
                db,
                user_id=int(target.id),
                plan=plan,
                reset_at=expires_at or (now + timedelta(days=30)),
            )
        else:
            rows = (
                db.query(UserPlan)
                .filter(
                    UserPlan.user_id == int(target.id),
                    UserPlan.plan_id == normalized_plan_id,
                    UserPlan.is_active.is_(True),
                )
                .with_for_update()
                .all()
            )
            for row in rows:
                row.is_active = False
                db.add(row)
            changed_plan_ids.add(normalized_plan_id)
            _deactivate_plan_entitlements(db, int(target.id), changed_plan_ids)
            if is_license:
                other_license = any(
                    item["catalog"] == "account_license"
                    for item in _active_plan_snapshot(db, int(target.id))
                    if item["plan_id"] != normalized_plan_id
                )
                if not other_license:
                    target.account_state = ACCOUNT_PENDING_PLAN
                    db.add(target)

        db.flush()
        after = account_fast_lane_status(db, int(target.id))
        request_fingerprint = {
            "actor_user_id": int(actor_row.id),
            "action": normalized_action,
            "account_id": int(target.id),
            "plan_id": normalized_plan_id,
            "reason": normalized_reason,
            "duration_days": normalized_duration_days,
        }
        result = {
            "ok": True,
            "duplicate": False,
            "request": request_fingerprint,
            "action": normalized_action,
            "reason": normalized_reason,
            **after,
            "audit": {
                "idempotency_key": normalized_key,
                "actor_user_id": int(actor_row.id),
                "actor_username": str(actor_row.username or ""),
                "aggregate_type": "account_entitlement",
            },
        }
        audit = CommerceAdminAction(
            actor_user_id=int(actor_row.id),
            action=(
                "fast_lane_assign_plan"
                if normalized_action == "assign"
                else "fast_lane_revoke_plan"
            ),
            aggregate_type="account_entitlement",
            aggregate_id=str(target.id),
            idempotency_key=normalized_key,
            status="completed",
            reason=normalized_reason,
            before_json=json.dumps(before, ensure_ascii=False, default=str),
            after_json=json.dumps(result, ensure_ascii=False, default=str),
        )
        db.add(audit)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        existing = _existing_action(db, normalized_key)
        if existing is None:
            raise
        return _replay_or_conflict(
            existing,
            actor_id=int(actor_row.id),
            action=normalized_action,
            account_id=int(target.id),
            plan_id=normalized_plan_id,
            reason=normalized_reason,
            duration_days=normalized_duration_days,
        )
    except Exception:
        db.rollback()
        raise


__all__ = [
    "FastLaneConflict",
    "FastLaneError",
    "FastLaneForbidden",
    "FastLaneNotFound",
    "account_fast_lane_status",
    "apply_fast_lane_action",
    "list_fast_lane_plans",
    "require_admin_actor",
    "resolve_account",
]
