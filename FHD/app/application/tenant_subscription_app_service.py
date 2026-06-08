"""租户试用与 SaaS 订阅状态。"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.session import get_db
from app.infrastructure.billing.saas_plans import is_saas_plan_id, trial_days
from app.utils.operational_errors import OPERATIONAL_ERRORS
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)


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
        return int(tenant.id)


def sync_tenant_display_name(*, user_id: int, company_brand: str) -> str:
    """若市场 company 与租户名不一致则更新 tenants.name。"""
    brand = (company_brand or "").strip()
    if not brand:
        return ""
    with get_db() as db:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user or not user.tenant_id:
            return brand
        tenant = db.query(Tenant).filter(Tenant.id == int(user.tenant_id)).first()
        if tenant is None:
            return brand
        if (tenant.name or "").strip() != brand:
            tenant.name = brand[:256]
            db.commit()
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
        except OPERATIONAL_ERRORS:
            logger.debug("surface audit demo subscription bypass skipped", exc_info=True)

        tenant: Tenant | None = None
        if user.tenant_id:
            tenant = db.query(Tenant).filter(Tenant.id == int(user.tenant_id)).first()

        if tenant and tenant.plan_id and is_saas_plan_id(str(tenant.plan_id)):
            return {
                "active": True,
                "reason": "paid_plan",
                "plan_id": tenant.plan_id,
                "tenant_id": tenant.id,
                "trial_expires_at": tenant.trial_expires_at.isoformat()
                if tenant.trial_expires_at
                else None,
            }

        if tenant and tenant.trial_expires_at and tenant.trial_expires_at >= now:
            return {
                "active": True,
                "reason": "trial",
                "plan_id": None,
                "tenant_id": tenant.id,
                "trial_expires_at": tenant.trial_expires_at.isoformat(),
                "trial_days_remaining": max(0, (tenant.trial_expires_at.date() - now.date()).days),
            }

        return {
            "active": False,
            "reason": "trial_expired",
            "plan_id": tenant.plan_id if tenant else None,
            "tenant_id": tenant.id if tenant else None,
            "trial_expires_at": (
                tenant.trial_expires_at.isoformat() if tenant and tenant.trial_expires_at else None
            ),
        }


def apply_paid_plan_to_tenant(*, tenant_id: int, plan_id: str) -> bool:
    if not is_saas_plan_id(plan_id):
        return False
    with get_db() as db:
        tenant = db.query(Tenant).filter(Tenant.id == int(tenant_id)).first()
        if not tenant:
            return False
        tenant.plan_id = str(plan_id).strip()
        db.commit()
        logger.info(
            "[tenant-subscription] plan applied tenant_id=%s plan_id=%s", tenant_id, plan_id
        )
        return True


def apply_paid_plan_for_user(*, user_id: int, plan_id: str) -> bool:
    with get_db() as db:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user or not user.tenant_id:
            return False
        return apply_paid_plan_to_tenant(tenant_id=int(user.tenant_id), plan_id=plan_id)
