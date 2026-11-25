"""租户试用与 SaaS 订阅状态。"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case

from app.db.models.tenant import Tenant
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.db.session import get_host_db as get_db
from app.infrastructure.billing.saas_plans import (
    PERSONAL_PLAN_ID,
    is_saas_plan_id,
    list_saas_plans,
    plan_by_id,
    trial_days,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)
_ACCOUNT_TIERS = ("normal", "pro", "max", "ultra")


def _tier_rank(value: Any) -> int:
    return _ACCOUNT_TIERS.index(value) if value in _ACCOUNT_TIERS else 0


def _parse_trial_deadline(value: str | None) -> datetime | None:
    try:
        expires = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return expires.astimezone(UTC).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _select_license(
    current_plan_id: str | None,
    plan: dict[str, Any],
    *,
    sync_from_market: bool = False,
    active_plan_expires_at: str | None = None,
    verified_account_sync: bool = False,
) -> tuple[dict[str, Any], datetime | None] | None:
    """Keep stronger purchased rights; market sync uses the original trial deadline."""
    current = plan_by_id(str(current_plan_id or "")) or {}
    if (
        not verified_account_sync
        and current.get("license_type") == "permanent"
        and (
            plan.get("license_type") != "permanent"
            or _tier_rank(current.get("account_tier")) >= _tier_rank(plan.get("account_tier"))
        )
    ):
        return current, None
    expires = None
    if plan.get("license_type") == "trial":
        if sync_from_market:
            expires = _parse_trial_deadline(active_plan_expires_at)
            if expires is None:
                return None
        else:
            expires = utc_now_naive() + timedelta(
                days=max(1, int(plan.get("duration_days") or trial_days()))
            )
    return plan, expires


def _apply_tenant_license(
    tenant: Tenant,
    plan: dict[str, Any],
    *,
    sync_from_market: bool = False,
    active_plan_expires_at: str | None = None,
) -> dict[str, Any] | None:
    selected = _select_license(
        tenant.plan_id,
        plan,
        sync_from_market=sync_from_market,
        active_plan_expires_at=active_plan_expires_at,
    )
    if selected is None:
        return None
    effective, expires = selected
    tenant.plan_id = str(effective["id"])
    tenant.trial_expires_at = expires
    if expires is not None:
        tenant.trial_started_at = expires - timedelta(
            days=max(1, int(effective.get("duration_days") or trial_days()))
        )
    return effective


def _legacy_account_plan(user: User, tenant: Tenant | None) -> dict[str, Any] | None:
    plan = plan_by_id(str(tenant.plan_id or "")) if tenant else None
    if (
        plan
        and plan.get("license_type") == "permanent"
        and user.account_tier in _ACCOUNT_TIERS
        and _tier_rank(user.account_tier) < _tier_rank(plan.get("account_tier"))
    ):
        # A shared tenant can retain another member's higher purchased plan.
        return next(
            (
                row
                for row in list_saas_plans(include_legacy=True)
                if row.get("license_type") == "permanent"
                and row.get("account_tier") == user.account_tier
            ),
            None,
        )
    return plan


def _account_plan_id(user: User, tenant: Tenant | None) -> str | None:
    if user.account_tier == "personal":
        return PERSONAL_PLAN_ID
    if isinstance(user.account_license_plan_id, str):
        return user.account_license_plan_id
    current = _legacy_account_plan(user, tenant)
    # An unmigrated account cannot inherit a higher member's tenant tier.
    if current and _tier_rank(user.account_tier) >= _tier_rank(current.get("account_tier")):
        return str(current["id"])
    return None


def _slug_code(username: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9_-]+", "-", (username or "tenant").strip().lower()).strip("-")
    return (base or "tenant")[:48]


def provision_trial_for_user(*, user_id: int, username: str, display_name: str = "") -> int | None:
    """为新注册用户创建试用租户并绑定 users.tenant_id。"""
    now = utc_now_naive()
    expires = now + timedelta(days=trial_days())
    code_base = _slug_code(username)

    with get_db() as db:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            return None
        if user.tenant_id:
            tenant = db.query(Tenant).filter(Tenant.id == int(user.tenant_id)).first()
            if tenant:
                return int(tenant.id)

        code = code_base
        suffix = 0
        while db.query(Tenant).filter(Tenant.code == code).first():
            suffix += 1
            code = f"{code_base}-{suffix}"

        tenant = Tenant(
            code=code,
            name=(display_name or username or code)[:256],
            is_active=True,
            trial_started_at=now,
            trial_expires_at=expires,
            plan_id=None,
            created_at=now,
        )
        db.add(tenant)
        db.flush()
        user.tenant_id = int(tenant.id)
        db.commit()
        logger.info(
            "[tenant-subscription] trial provisioned user_id=%s tenant_id=%s expires=%s",
            user_id,
            tenant.id,
            expires.isoformat(),
        )
        try:
            from app.neuro_bus.application_neuro_bridge import neuro_notify_tenant_changed

            neuro_notify_tenant_changed(
                "created",
                tenant_id=str(tenant.id),
                tenant_name=tenant.name or "",
            )
        except RECOVERABLE_ERRORS:
            logger.debug("neuro_notify_tenant_changed skipped", exc_info=True)
        return int(tenant.id)


def sync_tenant_display_name(*, user_id: int, company_brand: str, db: Any = None) -> str:
    """若市场 company 与租户名不一致则更新 tenants.name。"""
    brand = (company_brand or "").strip()
    if not brand:
        return ""
    if db is not None:
        # The company-name endpoint owns one host transaction for the tenant
        # and session, so a failed session write cannot leave half a local save.
        user = db.query(User).filter(User.id == int(user_id)).first()
        tenant = (
            db.query(Tenant).filter(Tenant.id == int(user.tenant_id)).first()
            if user and user.tenant_id
            else None
        )
        if tenant is None:
            raise ValueError("当前账号尚未建立工作区，请重新登录")
        if tenant.owner_user_id is not None and tenant.owner_user_id != user.id:
            raise ValueError("只有企业所有者可以修改企业名称")
        tenant.name = brand[:256]
        return str(tenant.name)
    with get_db() as db:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user or not user.tenant_id:
            return brand
        tenant = db.query(Tenant).filter(Tenant.id == int(user.tenant_id)).first()
        if tenant is None:
            return brand
        if tenant.owner_user_id is not None and tenant.owner_user_id != user.id:
            return str(tenant.name or brand)
        if (tenant.name or "").strip() != brand:
            tenant.name = brand[:256]
            db.commit()
            try:
                from app.neuro_bus.application_neuro_bridge import neuro_notify_tenant_changed

                neuro_notify_tenant_changed(
                    "updated",
                    tenant_id=str(tenant.id),
                    tenant_name=tenant.name or "",
                )
            except RECOVERABLE_ERRORS:
                logger.debug("neuro_notify_tenant_changed skipped", exc_info=True)
        return str(tenant.name or brand)


def subscription_status_for_user(user_id: int) -> dict[str, Any]:
    now = utc_now_naive()
    with get_db() as db:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            return {"active": False, "reason": "user_not_found"}
        if (user.role or "").lower() in {"admin", "superadmin"}:
            return {"active": True, "reason": "admin_bypass", "plan_id": None}

        try:
            from app.application.surface_audit_demo_account import demo_username

            if (user.username or "").strip() == demo_username():
                return {
                    "active": True,
                    "reason": "surface_audit_demo",
                    "plan_id": "saas-enterprise",
                }
        except RECOVERABLE_ERRORS:
            logger.debug("surface audit demo subscription bypass skipped", exc_info=True)

        if user.account_tier == "personal":
            return {"active": True, "reason": "personal_plan", "plan_id": PERSONAL_PLAN_ID}

        tenant: Tenant | None = None
        if user.tenant_id:
            tenant = db.query(Tenant).filter(Tenant.id == int(user.tenant_id)).first()

        account_plan = isinstance(user.account_license_plan_id, str)
        plan_id = (
            user.account_license_plan_id if account_plan else tenant.plan_id if tenant else None
        )
        expires = (
            user.account_license_expires_at
            if account_plan
            else tenant.trial_expires_at
            if tenant
            else None
        )
        plan = (
            plan_by_id(str(plan_id or "")) if account_plan else _legacy_account_plan(user, tenant)
        )
        if plan:
            plan_id = str(plan["id"])
        paid_plan_active = bool(plan)
        if plan and str(plan.get("license_type") or "") == "trial":
            paid_plan_active = bool(expires and expires >= now)
        if tenant and plan_id and paid_plan_active:
            return {
                "active": True,
                "reason": "paid_plan",
                "plan_id": plan_id,
                "tenant_id": tenant.id,
                "trial_expires_at": expires.isoformat() if expires else None,
            }

        if not account_plan and tenant and expires and expires >= now:
            return {
                "active": True,
                "reason": "trial",
                "plan_id": None,
                "tenant_id": tenant.id,
                "trial_expires_at": expires.isoformat(),
                "trial_days_remaining": max(0, (expires.date() - now.date()).days),
            }

        return {
            "active": False,
            "reason": "trial_expired",
            "plan_id": plan_id,
            "tenant_id": tenant.id if tenant else None,
            "trial_expires_at": expires.isoformat() if expires else None,
        }


def apply_paid_plan_to_tenant(*, tenant_id: int, plan_id: str) -> bool:
    if not is_saas_plan_id(plan_id):
        return False
    with get_db() as db:
        tenant = db.query(Tenant).filter(Tenant.id == int(tenant_id)).first()
        if not tenant:
            return False
        plan = plan_by_id(plan_id)
        if not plan or plan_id == PERSONAL_PLAN_ID:
            return False
        _apply_tenant_license(tenant, plan)
        db.commit()
        logger.info(
            "[tenant-subscription] plan applied tenant_id=%s plan_id=%s", tenant_id, plan_id
        )
        try:
            from app.neuro_bus.application_neuro_bridge import neuro_notify_tenant_changed

            neuro_notify_tenant_changed(
                "updated",
                tenant_id=str(tenant.id),
                tenant_name=tenant.name or "",
            )
        except RECOVERABLE_ERRORS:
            logger.debug("neuro_notify_tenant_changed skipped", exc_info=True)
        return True


def apply_paid_plan_for_user(
    *,
    user_id: int,
    plan_id: str,
    sync_from_market: bool = False,
    active_plan_expires_at: str | None = None,
    verified_account_sync: bool = False,
    verified_payment_grant: bool = False,
) -> bool:
    if verified_account_sync and not sync_from_market:
        return False
    if not is_saas_plan_id(plan_id):
        return False
    plan = plan_by_id(plan_id) or {}
    verified_grant = verified_account_sync or verified_payment_grant
    with get_db() as db:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            return False
        tenant = (
            db.query(Tenant).filter(Tenant.id == int(user.tenant_id)).first()
            if user.tenant_id
            else None
        )
        current_plan_id = _account_plan_id(user, tenant)
        if plan_id == PERSONAL_PLAN_ID:
            current = plan_by_id(str(current_plan_id or ""))
            expires = (
                user.account_license_expires_at
                if isinstance(user.account_license_plan_id, str)
                else tenant.trial_expires_at
                if tenant
                else None
            )
            # Ordinary purchases preserve paid rights; authenticated market sync
            # can reclaim this account's grant after the market revokes it.
            if not sync_from_market and (
                _tier_rank(user.account_tier) > 0
                or (
                    current
                    and tenant is not None
                    and (
                        current.get("license_type") == "permanent"
                        or (
                            current.get("license_type") == "trial"
                            and expires
                            and expires >= utc_now_naive()
                        )
                    )
                )
            ):
                return False
            user.account_tier = "personal"
            user.account_license_plan_id = PERSONAL_PLAN_ID
            user.account_license_expires_at = None
            db.commit()
            return True
        if tenant is None:
            return False
        selected = _select_license(
            current_plan_id,
            plan,
            sync_from_market=sync_from_market,
            active_plan_expires_at=active_plan_expires_at,
            verified_account_sync=verified_account_sync,
        )
        if selected is None:
            return False
        effective, expires = selected
        # The tenant aggregate may retain another account's stronger grant.
        # It is never the authority for this account's newly purchased license.
        _apply_tenant_license(
            tenant,
            effective,
            sync_from_market=True,
            active_plan_expires_at=expires.isoformat() if expires else None,
        )
        user.account_license_plan_id = str(effective["id"])
        user.account_license_expires_at = expires
        if user.tier != "admin":
            user.tier = "enterprise"
        # Only this account's previous grant and newly purchased plan can upgrade it.
        rank = _tier_rank(effective.get("account_tier"))
        user.account_tier = _ACCOUNT_TIERS[
            rank if verified_account_sync else max(_tier_rank(user.account_tier), rank)
        ]
        if (
            verified_grant
            and effective.get("license_type") == "trial"
            and expires is not None
            and user.account_tier == "normal"
            and user.tier != "admin"
            and (user.role or "").lower() not in {"admin", "superadmin"}
        ):
            # The account grant owns the deadline; sessions retain only the
            # narrower credential bound established by this verified grant.
            db.query(UserSession).filter(UserSession.user_id == user.id).update(
                {
                    "expires_at": case(
                        (UserSession.expires_at > expires, expires),
                        else_=UserSession.expires_at,
                    ),
                    "verified_trial_expires_at": expires,
                },
                synchronize_session=False,
            )
        elif verified_grant and plan.get("license_type") == "permanent":
            # Only this account's verified upgrade replaces its trial evidence;
            # another tenant member's license cannot renew this session.
            db.query(UserSession).filter(UserSession.user_id == user.id).update(
                {"verified_trial_expires_at": None}, synchronize_session=False
            )
        db.commit()
        logger.info(
            "[tenant-subscription] market license applied user_id=%s tenant_id=%s account_tier=%s",
            user_id,
            tenant.id,
            user.account_tier,
        )
        try:
            from app.neuro_bus.application_neuro_bridge import neuro_notify_tenant_changed

            neuro_notify_tenant_changed(
                "updated",
                tenant_id=str(tenant.id),
                tenant_name=tenant.name or "",
            )
        except RECOVERABLE_ERRORS:
            logger.debug("neuro_notify_tenant_changed skipped", exc_info=True)
        return True
