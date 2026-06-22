"""Session 账号类型、企业品牌名、代管态（三档登录 / 管理员全球权）。"""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.db.models.user import Session as UserSession
from app.db.session import get_host_db
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

AccountKind = Literal["personal", "enterprise", "admin"]
VALID_ACCOUNT_KINDS: frozenset[str] = frozenset({"personal", "enterprise", "admin"})


def normalize_account_kind(raw: Any, *, default: str = "enterprise") -> AccountKind:
    v = str(raw or default).strip().lower()
    if v in VALID_ACCOUNT_KINDS:
        return v
    return default


def derive_account_kind_from_user(
    *,
    tier: Any,
    market_is_admin: bool = False,
    market_is_enterprise: bool = False,
) -> AccountKind:
    """单一真相源派生会话档位（account_kind）。

    以本地 ``User.tier`` 为主真相源；修茈市场身份只能向上提升，不能下调。
    优先级 admin > enterprise > personal。登录入口（前端 hint）不再决定档位。
    """
    t = str(tier or "").strip().lower()
    if t == "admin" or market_is_admin:
        return "admin"
    if t == "enterprise" or market_is_enterprise:
        return "enterprise"
    return "personal"


def extract_market_user_blob(market_result: dict[str, Any] | None) -> dict[str, Any]:
    if not market_result or not isinstance(market_result, dict):
        return {}
    raw = market_result.get("raw")
    if not isinstance(raw, dict):
        return {}
    user_blob = raw.get("user")
    if isinstance(user_blob, dict):
        return user_blob
    data = raw.get("data")
    if isinstance(data, dict):
        inner = data.get("user")
        if isinstance(inner, dict):
            return inner
        return data
    return {}


def company_brand_from_user_blob(blob: dict[str, Any] | None) -> str:
    if not blob or not isinstance(blob, dict):
        return ""
    company = str(blob.get("company") or "").strip()
    if company:
        return company
    display = str(blob.get("display_name") or "").strip()
    if display:
        return display
    return str(blob.get("username") or "").strip()


def validate_account_kind_for_market(
    account_kind: AccountKind,
    *,
    is_enterprise: bool,
    is_market_admin: bool,
) -> str | None:
    """返回错误文案；None 表示通过。"""
    if account_kind == "admin":
        if not is_market_admin:
            return "该入口需要平台管理员账号，请使用管理员账号登录或切换登录方式。"
        return None
    if account_kind == "enterprise":
        if is_market_admin:
            return "管理员账号不能从企业账号入口登录，请切换到管理员入口登录。"
        if not is_enterprise:
            return "该入口需要企业版账号。请联系管理员在修茈市场标注为企业用户。"
        return None
    # personal：阶段一与企业相同
    if is_market_admin:
        return "管理员账号请使用管理员入口登录。"
    if not is_enterprise:
        return "该账号未开通企业版。请联系管理员在修茈市场标注为企业用户。"
    return None


def persist_session_account_meta(
    session_id: str,
    *,
    account_kind: AccountKind,
    company_brand: str = "",
    market_user_id: int | None = None,
    market_is_admin: bool = False,
    market_is_enterprise: bool = False,
    impersonating_market_user_id: int | None = None,
    impersonating_username: str = "",
    tenant_id: int | None = None,
) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    try:
        with get_host_db() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            if row is None:
                return
            row.account_kind = account_kind
            row.company_brand = (company_brand or "").strip()[:256]
            if market_user_id is not None:
                row.market_user_id = int(market_user_id)
            row.market_is_admin = bool(market_is_admin)
            row.market_is_enterprise = bool(market_is_enterprise)
            row.impersonating_market_user_id = (
                int(impersonating_market_user_id)
                if impersonating_market_user_id is not None
                else None
            )
            row.impersonating_username = (impersonating_username or "").strip()[:128]
            if tenant_id is not None and hasattr(row, "tenant_id"):
                row.tenant_id = int(tenant_id)
            db.commit()
    except RECOVERABLE_ERRORS:
        logger.exception("persist_session_account_meta failed")


def persist_session_membership_tier(session_id: str, membership_tier: str | None) -> None:
    """单独写入会话的修茈市场会员等级（登录时从 /api/payment/my-plan 同步）。"""
    sid = (session_id or "").strip()
    if not sid:
        return
    try:
        with get_host_db() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            if row is None:
                return
            row.market_membership_tier = (membership_tier or "").strip()[:32] or None
            db.commit()
    except RECOVERABLE_ERRORS:
        logger.exception("persist_session_membership_tier failed")


def load_session_account_meta(session_id: str) -> dict[str, Any] | None:
    sid = (session_id or "").strip()
    if not sid:
        return None
    try:
        with get_host_db() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            if row is None:
                return None
            return session_row_to_meta_dict(row)
    except RECOVERABLE_ERRORS:
        logger.exception("load_session_account_meta failed")
        return None


def session_row_to_meta_dict(row: UserSession) -> dict[str, Any]:
    imp_uid = getattr(row, "impersonating_market_user_id", None)
    return {
        "account_kind": str(getattr(row, "account_kind", None) or "enterprise").strip()
        or "enterprise",
        "company_brand": str(getattr(row, "company_brand", None) or "").strip(),
        "market_user_id": getattr(row, "market_user_id", None),
        "market_is_admin": bool(getattr(row, "market_is_admin", False)),
        "market_is_enterprise": bool(getattr(row, "market_is_enterprise", False)),
        "market_membership_tier": (
            str(getattr(row, "market_membership_tier", None) or "").strip() or None
        ),
        "impersonating_market_user_id": int(imp_uid) if imp_uid is not None else None,
        "impersonating_username": str(getattr(row, "impersonating_username", None) or "").strip(),
        "tenant_id": getattr(row, "tenant_id", None),
    }


def enrich_session_meta_with_tenant(session_id: str, user: Any) -> dict[str, Any]:
    """补全 tenant_id / tenant_name，并与 users.tenant_id、sessions.tenant_id 对齐。

    企业用户若尚未绑定租户，登录后访问 /api/auth/me 时会自动 provision 试用租户。
    """
    sid = (session_id or "").strip()
    meta = load_session_account_meta(sid) if sid else None
    meta = dict(meta or {})

    if user is not None:
        uid = getattr(user, "id", None)
        if uid is not None:
            meta["local_user_id"] = int(uid)

    account_kind = str(meta.get("account_kind") or "enterprise").strip() or "enterprise"
    if account_kind == "admin":
        return meta

    tid = meta.get("tenant_id")
    if tid is None and user is not None:
        tid = getattr(user, "tenant_id", None)

    company_brand = str(meta.get("company_brand") or "").strip()
    username = str(getattr(user, "username", None) or "").strip() if user is not None else ""

    if tid is None and meta.get("local_user_id"):
        from app.application.enterprise_login_flow import bind_tenant_for_login

        tenant_info = bind_tenant_for_login(
            user_id=int(meta["local_user_id"]),
            company_brand=company_brand,
            username=username,
        )
        if tenant_info.get("tenant_id") is not None:
            tid = int(tenant_info["tenant_id"])
        if tenant_info.get("tenant_name"):
            meta["tenant_name"] = str(tenant_info["tenant_name"])

    if tid is not None:
        meta["tenant_id"] = int(tid)
        if not meta.get("tenant_name"):
            try:
                from app.db.models.tenant import Tenant

                with get_host_db() as db:
                    tenant = db.query(Tenant).filter(Tenant.id == int(tid)).first()
                    if tenant and (tenant.name or "").strip():
                        meta["tenant_name"] = str(tenant.name).strip()
            except RECOVERABLE_ERRORS:
                logger.exception("enrich_session_meta tenant name lookup failed")
        if not meta.get("tenant_name") and company_brand:
            meta["tenant_name"] = company_brand

        if sid:
            try:
                with get_host_db() as db:
                    row = db.query(UserSession).filter(UserSession.session_id == sid).first()
                    if row is not None and getattr(row, "tenant_id", None) != int(tid):
                        row.tenant_id = int(tid)
                        db.commit()
            except RECOVERABLE_ERRORS:
                logger.exception("persist sessions.tenant_id failed session=%s", sid)

    return meta


def clear_impersonation(session_id: str) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    try:
        with get_host_db() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            if row is None:
                return
            row.impersonating_market_user_id = None
            row.impersonating_username = ""
            db.commit()
    except RECOVERABLE_ERRORS:
        logger.exception("clear_impersonation failed")


def is_session_market_admin(session_id: str) -> bool:
    meta = load_session_account_meta(session_id)
    if not meta:
        return False
    return meta.get("account_kind") == "admin" and bool(meta.get("market_is_admin"))


def should_receive_enterprise_dedicated_cs(
    session_id: str | None,
    user_id: int | None,
    db: Any,
) -> bool:
    """Return whether this requester should see enterprise dedicated customer-service flow."""
    meta = load_session_account_meta(session_id or "") if session_id else None
    if meta:
        if meta.get("account_kind") == "admin" or bool(meta.get("market_is_admin")):
            return False
        return (
            meta.get("account_kind") == "enterprise"
            or bool(meta.get("market_is_enterprise"))
            or meta.get("impersonating_market_user_id") is not None
        )

    if user_id is None or db is None:
        return False
    try:
        from app.db.models.user import User

        user = db.get(User, int(user_id))
    except RECOVERABLE_ERRORS:
        logger.exception("enterprise dedicated CS fallback user lookup failed")
        return False
    except (TypeError, ValueError):
        return False
    role = str(getattr(user, "role", "") or "").strip().lower()
    return role not in {"admin", "market_admin", "super_admin"}


def effective_entitlement_market_user_id(session_id: str) -> int | None:
    meta = load_session_account_meta(session_id)
    if not meta:
        return None
    imp = meta.get("impersonating_market_user_id")
    if imp is not None:
        return int(imp)
    mid = meta.get("market_user_id")
    return int(mid) if mid is not None else None


def audit_admin_action(
    request: Any,
    action: str,
    *,
    target_user_id: int | None = None,
    mod_id: str = "",
    detail: str = "",
) -> None:
    try:
        from app.fastapi_routes.legacy_helpers import _session_id_from_request

        sid = _session_id_from_request(request)
        meta = load_session_account_meta(sid) if sid else None
        operator = (meta or {}).get("impersonating_username") or ""
        if not operator and sid:
            info = load_session_account_meta(sid)
            operator = str((info or {}).get("market_user_id") or "")
        logger.info(
            "admin_audit action=%s session=%s target_user=%s mod_id=%s detail=%s",
            action,
            sid,
            target_user_id,
            mod_id,
            detail or operator,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("audit_admin_action failed")
