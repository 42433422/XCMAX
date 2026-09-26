"""Verified market identity binding, conservative owner claim, and one-use invitations."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from app.application.tenant_subscription_app_service import _slug_code
from app.db.models.permission import Role
from app.db.models.tenant import Tenant
from app.db.models.tenant_invitation import TenantInvitation
from app.db.models.user import Session, User
from app.db.session import get_host_db
from app.utils.logging import audit_logger
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)


class TenantIdentityError(ValueError):
    """Market account or invitation cannot be bound without changing ownership."""


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _audit_owner(user_id: int, tenant_id: int, accepted: bool, reason: str) -> None:
    audit_logger.audit_log(
        "tenant_owner_claim",
        user_id,
        "",
        {"tenant_id": tenant_id, "reason": reason},
        success=accepted,
    )
    logger.info(
        "tenant owner claim user_id=%s tenant_id=%s accepted=%s reason=%s",
        user_id,
        tenant_id,
        accepted,
        reason,
    )


def _founder_fingerprint(db, tenant: Tenant, user: User) -> bool:
    if tenant.code != _slug_code(user.username):
        return False
    if tenant.created_at is None or user.created_at is None:
        return False
    age = (tenant.created_at - user.created_at).total_seconds()
    if not 0 <= age <= 300:
        return False
    members = db.query(User.id).filter(User.tenant_id == tenant.id).all()
    return len(members) == 1 and int(members[0][0]) == int(user.id)


def bind_verified_market_identity(
    *,
    user_id: int,
    market_user_id: int | None,
    market_username: str,
    market_is_enterprise: bool,
    market_is_admin: bool,
) -> None:
    """Only a live successful market login may claim an unowned legacy workspace."""
    if not market_is_enterprise or market_is_admin or not market_user_id or market_user_id <= 0:
        return
    with get_host_db() as db:
        user = db.get(User, int(user_id))
        if user is None or user.username.casefold() != market_username.casefold():
            raise TenantIdentityError("市场身份与本地账号不一致")
        other = (
            db.query(User.id)
            .filter(User.market_user_id == market_user_id, User.id != user_id)
            .first()
        )
        if other or (user.market_user_id is not None and user.market_user_id != market_user_id):
            raise TenantIdentityError("市场身份已绑定到其他本地账号")
        user.market_user_id = int(market_user_id)
        tenant = db.get(Tenant, int(user.tenant_id)) if user.tenant_id else None
        if tenant is None or tenant.owner_user_id is not None:
            return
        if _founder_fingerprint(db, tenant, user):
            tenant.owner_user_id = int(user.id)
            _audit_owner(user.id, tenant.id, True, "verified_founding_user")
        else:
            _audit_owner(user.id, tenant.id, False, "legacy_fingerprint_mismatch")


def create_tenant_invitation(*, inviter_user_id: int, tenant_id: int, target_username: str) -> dict:
    target = target_username.strip()
    if not target or len(target) > 128:
        raise TenantIdentityError("请输入有效的市场账号用户名")
    now = utc_now_naive()
    code = secrets.token_urlsafe(32)
    with get_host_db() as db:
        inviter = db.get(User, int(inviter_user_id))
        tenant = db.get(Tenant, int(tenant_id))
        if (
            not inviter
            or not tenant
            or not tenant.is_active
            or tenant.owner_user_id != inviter.id
            or inviter.tenant_id != tenant.id
            or not inviter.market_user_id
        ):
            raise TenantIdentityError("只有已验证的企业所有者可以邀请成员")
        if inviter.username.casefold() == target.casefold():
            raise TenantIdentityError("不能邀请自己")
        member_role = f"tenant:{tenant.id}:member"
        if db.query(Role.id).filter(Role.name == member_role).first() is None:
            db.add(Role(name=member_role, description="新成员（待分配权限）", is_system=False))
        invitation = TenantInvitation(
            tenant_id=tenant.id,
            inviter_user_id=inviter.id,
            target_username=target,
            token_sha256=_digest(code),
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
        db.add(invitation)
        db.flush()
        invite_id = invitation.id
        expires_at = invitation.expires_at.isoformat()
    audit_logger.audit_log(
        "tenant_invite_created",
        inviter_user_id,
        "",
        {"tenant_id": tenant_id, "invite_id": invite_id},
        success=True,
    )
    return {"code": code, "target_username": target, "expires_at": expires_at}


def accept_verified_tenant_invitation(
    *,
    user_id: int,
    market_user_id: int | None,
    market_username: str,
    code: str,
    session_id: str,
) -> dict:
    if not market_user_id or market_user_id <= 0 or not code.strip():
        raise TenantIdentityError("邀请需要已验证的市场企业身份")
    now = utc_now_naive()
    with get_host_db() as db:
        invitation = (
            db.query(TenantInvitation)
            .filter(TenantInvitation.token_sha256 == _digest(code.strip()))
            .first()
        )
        if invitation is None or invitation.accepted_at is not None or invitation.expires_at <= now:
            raise TenantIdentityError("邀请码无效或已过期")
        if invitation.target_username.casefold() != market_username.casefold():
            raise TenantIdentityError("邀请码与当前市场账号不匹配")
        user = db.get(User, int(user_id))
        tenant = db.get(Tenant, int(invitation.tenant_id))
        if not user or user.username.casefold() != market_username.casefold():
            raise TenantIdentityError("市场身份与本地账号不一致")
        if not tenant or not tenant.is_active or tenant.owner_user_id != invitation.inviter_user_id:
            raise TenantIdentityError("邀请所属企业不可用")
        if user.tenant_id is not None and user.tenant_id != tenant.id:
            raise TenantIdentityError("当前账号已有其他企业工作区，不能自动迁移其数据")
        other = (
            db.query(User.id)
            .filter(User.market_user_id == market_user_id, User.id != user_id)
            .first()
        )
        if other or (user.market_user_id is not None and user.market_user_id != market_user_id):
            raise TenantIdentityError("市场身份已绑定到其他本地账号")
        updated = (
            db.query(TenantInvitation)
            .filter(TenantInvitation.id == invitation.id, TenantInvitation.accepted_at.is_(None))
            .update(
                {"accepted_at": now, "accepted_market_user_id": market_user_id},
                synchronize_session=False,
            )
        )
        if updated != 1:
            raise TenantIdentityError("邀请码已被使用")
        user.market_user_id = market_user_id
        user.tenant_id = tenant.id
        member_role = f"tenant:{tenant.id}:member"
        if db.query(Role.id).filter(Role.name == member_role).first() is None:
            db.add(Role(name=member_role, description="新成员（待分配权限）", is_system=False))
        user.role = member_role
        db.query(Session).filter(
            Session.user_id == user.id, Session.session_id != session_id
        ).delete(synchronize_session=False)
        current = (
            db.query(Session)
            .filter(Session.session_id == session_id, Session.user_id == user.id)
            .first()
        )
        if current is None:
            raise TenantIdentityError("当前登录会话无效")
        current.tenant_id = tenant.id
        current.market_user_id = market_user_id
        result = {"tenant_id": tenant.id, "tenant_name": tenant.name, "role": user.role}
    audit_logger.audit_log(
        "tenant_invite_accepted",
        user_id,
        "",
        {"tenant_id": result["tenant_id"], "market_user_id": market_user_id},
        success=True,
    )
    return result
