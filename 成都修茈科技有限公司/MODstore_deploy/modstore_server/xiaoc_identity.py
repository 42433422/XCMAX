"""Visitor identity helpers for the XiaoC customer-service SSOT."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)
_VISITOR_ID_RE = re.compile(r"^v_[A-Za-z0-9_-]{8,64}$")


@dataclass(frozen=True)
class VisitorIdentity:
    """小C 对话对象（注入 system prompt，不落敏感明文）。"""

    kind: str  # guest | user
    source: str  # corp | butler | market_cs
    display_name: str = ""
    user_id: Optional[int] = None
    visitor_id: str = ""
    membership: str = ""  # 展示档：普通用户 / VIP / VIP+ / svip / SVIP2…
    account_role: str = ""  # user | enterprise | admin
    plan_id: str = ""
    email_hint: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "source": self.source,
            "display_name": self.display_name,
            "user_id": self.user_id,
            "visitor_id": self.visitor_id,
            "membership": self.membership,
            "account_role": self.account_role,
            "plan_id": self.plan_id,
            "email_hint": self.email_hint,
        }


def sanitize_visitor_id(raw: Optional[str]) -> str:
    v = (raw or "").strip()
    if not v or not _VISITOR_ID_RE.match(v):
        return ""
    return v


def sanitize_visitor_label(raw: Optional[str], *, max_len: int = 32) -> str:
    label = re.sub(r"\s+", " ", (raw or "").strip())
    if not label:
        return ""
    # 去掉控制字符
    label = "".join(ch for ch in label if ch.isprintable())
    return label[:max_len]


def mask_email(email: Optional[str]) -> str:
    e = (email or "").strip()
    if "@" not in e:
        return ""
    local, _, domain = e.partition("@")
    if not local or not domain:
        return ""
    if len(local) <= 1:
        head = "*"
    elif len(local) == 2:
        head = local[0] + "*"
    else:
        head = local[0] + "***" + local[-1]
    return f"{head}@{domain}"


def identity_from_guest(
    *,
    visitor_id: str = "",
    visitor_label: str = "",
    source: str = "corp",
) -> VisitorIdentity:
    vid = sanitize_visitor_id(visitor_id)
    label = sanitize_visitor_label(visitor_label) or ("访客" if vid else "匿名访客")
    return VisitorIdentity(
        kind="guest",
        source=source or "corp",
        display_name=label,
        visitor_id=vid,
    )


def _account_role_of(user: Any) -> str:
    if bool(getattr(user, "is_admin", False)):
        return "admin"
    if bool(getattr(user, "is_enterprise", False)):
        return "enterprise"
    return "user"


def _membership_label_for_plan(plan_id: str) -> str:
    """套餐展示名（与 payment_common 会员档对齐；无套餐=普通用户）。"""
    pid = (plan_id or "").strip()
    if not pid:
        return "普通用户"
    try:
        from modstore_server.payment_common import _membership_meta

        meta = _membership_meta(pid)
        label = str(meta.get("label") or "").strip()
        if label:
            return label
    except Exception:  # noqa: BLE001
        pass
    # llm_api 旧映射兜底
    try:
        from modstore_server.llm_api import _membership_meta as _llm_meta

        label = str((_llm_meta(pid) or {}).get("label") or "").strip()
        if label:
            return label
    except Exception:  # noqa: BLE001
        pass
    return pid


def active_plan_id_for_user(db: Any, user_id: int) -> str:
    """读取 user_plans 当前生效套餐（账号 SSOT）。"""
    if db is None or not user_id:
        return ""
    try:
        from modstore_server.models import UserPlan

        # SAVEPOINT：查询失败时只回滚嵌套事务，避免吞掉异常后污染外层事务
        # （否则后续客服建会话 INSERT 会变成 InFailedSqlTransaction → 500）
        nested = db.begin_nested() if hasattr(db, "begin_nested") else None
        try:
            row = (
                db.query(UserPlan)
                .filter(UserPlan.user_id == int(user_id), UserPlan.is_active == True)  # noqa: E712
                .order_by(UserPlan.id.desc())
                .first()
            )
            plan_id = str(row.plan_id) if row else ""
            if nested is not None:
                nested.commit()
            return plan_id
        except Exception:
            if nested is not None:
                nested.rollback()
            raise
    except Exception:  # noqa: BLE001
        logger.debug("active_plan_id_for_user failed", exc_info=True)
        return ""


def identity_from_user(
    user: Any,
    *,
    source: str = "butler",
    membership_tier: Optional[str] = None,
    visitor_id: str = "",
    plan_id: str = "",
    account_role: Optional[str] = None,
    db: Any = None,
) -> VisitorIdentity:
    """从 User（+ 可选 DB 套餐）构建对话对象。

    会员档优先读 ``user_plans``；口语「体验版」≈ 无付费套餐（普通用户）。
    """
    uid = getattr(user, "id", None)
    try:
        user_id = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        user_id = None
    username = str(getattr(user, "username", None) or "").strip()
    email = str(getattr(user, "email", None) or "").strip()
    display = (
        username
        or (email.split("@")[0] if email else "")
        or (f"用户{user_id}" if user_id else "用户")
    )
    role = (account_role or _account_role_of(user)).strip() or "user"
    pid = (plan_id or "").strip()
    if not pid and db is not None and user_id:
        pid = active_plan_id_for_user(db, user_id)
    membership = (membership_tier or "").strip()
    if not membership:
        membership = _membership_label_for_plan(pid)
    return VisitorIdentity(
        kind="user",
        source=source or "butler",
        display_name=sanitize_visitor_label(display) or "用户",
        user_id=user_id,
        visitor_id=sanitize_visitor_id(visitor_id),
        membership=membership,
        account_role=role,
        plan_id=pid,
        email_hint=mask_email(email),
    )


def resolve_user_identity(
    user: Any,
    *,
    db: Any = None,
    source: str = "butler",
    visitor_id: str = "",
) -> VisitorIdentity:
    """已登录用户身份 SSOT：档案 + 管理员/企业旗标 + 当前会员套餐。"""
    return identity_from_user(user, source=source, visitor_id=visitor_id, db=db)


def format_visitor_block(identity: Optional[VisitorIdentity]) -> str:
    if identity is None:
        return ""
    parts = [
        f"kind={identity.kind}",
        f"称呼={identity.display_name or '访客'}",
    ]
    if identity.user_id is not None:
        parts.append(f"user_id={identity.user_id}")
    role = (identity.account_role or "").strip()
    if role and role != "user":
        role_label = {"admin": "管理员", "enterprise": "企业账号"}.get(role, role)
        parts.append(f"角色={role_label}")
    if identity.membership:
        parts.append(f"会员={identity.membership}")
    if identity.plan_id:
        parts.append(f"套餐={identity.plan_id}")
    if identity.visitor_id:
        parts.append(f"visitor_id={identity.visitor_id}")
    if identity.email_hint:
        parts.append(f"邮箱={identity.email_hint}")
    parts.append(f"入口={identity.source}")
    return (
        "【当前对话对象】" + "；".join(parts) + "。可自然称呼并按会员/角色调整话术（如权益说明），"
        "勿复读整段 ID/内部字段，勿向访客复述敏感信息。"
    )
