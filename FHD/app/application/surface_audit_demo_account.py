"""P-S 企业版桌面截图 · 本地演示账号（非管理员）。"""

from __future__ import annotations

from app.utils.operational_errors import OPERATIONAL_ERRORS
import json
import logging
import os
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FHD_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _FHD_ROOT / "config" / "surface_audit_demo_account.json"
_DEMO_TOKEN_PREFIX = "xcagi-local-surface-audit-demo"


@lru_cache(maxsize=1)
def demo_account_config() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "username": "xcagi-enterprise-demo",
        "password": "Demo@2026",
        "display_name": "企业版演示",
        "company_brand": "修茈演示企业",
        "email": "enterprise-demo@xiu-ci.com",
        "market_user_id": 33,
        "market_token": _DEMO_TOKEN_PREFIX,
    }
    if not _CONFIG_PATH.is_file():
        return defaults
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {**defaults, **{k: v for k, v in raw.items() if not str(k).startswith("_")}}
    except OPERATIONAL_ERRORS:
        logger.debug("surface audit demo config read failed", exc_info=True)
    return defaults


def demo_username() -> str:
    return (
        os.environ.get("SURFACE_AUDIT_DEMO_USER")
        or os.environ.get("SURFACE_AUDIT_ENTERPRISE_USER")
        or str(demo_account_config().get("username") or "")
    ).strip()


def demo_password() -> str:
    return (
        os.environ.get("SURFACE_AUDIT_DEMO_PASSWORD")
        or os.environ.get("SURFACE_AUDIT_ENTERPRISE_PASSWORD")
        or str(demo_account_config().get("password") or "")
    ).strip()


def demo_market_token() -> str:
    return (
        os.environ.get("SURFACE_AUDIT_DEMO_MARKET_TOKEN")
        or str(demo_account_config().get("market_token") or _DEMO_TOKEN_PREFIX)
    ).strip()


def is_demo_market_token(token: str) -> bool:
    tok = (token or "").strip()
    if not tok:
        return False
    base = demo_market_token()
    return tok == base or tok.startswith(f"{base}:")


def credentials_match_demo(username: str, password: str) -> bool:
    user = demo_username()
    pwd = demo_password()
    if not user or not pwd:
        return False
    return (username or "").strip() == user and password == pwd


def try_local_demo_market_login(username: str, password: str) -> dict[str, Any] | None:
    """本地 MODstore 离线时的演示 shim（非 admin · enterprise 身份）。

    官网 xiu-ci.com 已注册同名账号时，远端市场应走 ``login_market_with_password`` 的真实 API，
    仅在 ``XCAGI_MARKET_BASE_URL`` 指向本机且市场不可达时使用本 shim。
    """
    if not credentials_match_demo(username, password):
        return None
    cfg = demo_account_config()
    user = demo_username()
    return {
        "success": True,
        "market_base_url": "",
        "token": demo_market_token(),
        "refresh_token": "",
        "is_enterprise": True,
        "is_market_admin": False,
        "raw": {
            "user": {
                "id": int(cfg.get("market_user_id") or 900001),
                "username": user,
                "display_name": str(cfg.get("display_name") or "企业版演示"),
                "company": str(cfg.get("company_brand") or "修茈演示企业"),
                "company_brand": str(cfg.get("company_brand") or "修茈演示企业"),
                "is_enterprise": True,
                "is_admin": False,
            }
        },
    }


def seed_demo_user_row(*, session_factory) -> None:
    """幂等写入演示企业本地用户（role=user，非 admin）及有效 SaaS 订阅。"""
    from app.db.models.tenant import Tenant
    from app.db.models.user import User
    from app.utils.password_hash import generate_password_hash
    from app.utils.time import utc_now_naive

    cfg = demo_account_config()
    username = demo_username()
    password = demo_password()
    if not username or not password:
        return
    display_name = str(cfg.get("display_name") or "企业版演示").strip() or "企业版演示"
    email = str(cfg.get("email") or f"{username}@local").strip()
    company = str(cfg.get("company_brand") or "修茈演示企业").strip()
    pwd_hash = generate_password_hash(password)
    now = utc_now_naive()

    with session_factory() as session:
        row = session.query(User).filter(User.username == username).first()
        if row is None:
            row = User(
                username=username,
                password=pwd_hash,
                display_name=display_name,
                email=email,
                role="user",
                is_active=True,
                mfa_enabled=False,
                created_at=now,
            )
            session.add(row)
            session.flush()

        changed = False
        if row.password != pwd_hash:
            row.password = pwd_hash
            changed = True
        if (row.display_name or "") != display_name:
            row.display_name = display_name
            changed = True
        if str(row.role or "") == "admin":
            row.role = "user"
            changed = True

        tenant: Tenant | None = None
        if row.tenant_id:
            tenant = session.query(Tenant).filter(Tenant.id == int(row.tenant_id)).first()
        try:
            if tenant is None:
                code = "xcagi-enterprise-demo"
                tenant = session.query(Tenant).filter(Tenant.code == code).first()
                if tenant is None:
                    tenant = Tenant(
                        code=code,
                        name=company[:256],
                        is_active=True,
                        trial_started_at=now,
                        trial_expires_at=now + timedelta(days=3650),
                        plan_id="saas-enterprise",
                        created_at=now,
                    )
                    session.add(tenant)
                    session.flush()
                    changed = True
                row.tenant_id = int(tenant.id)
                changed = True
            elif tenant.plan_id != "saas-enterprise":
                tenant.plan_id = "saas-enterprise"
                tenant.is_active = True
                if not tenant.trial_expires_at or tenant.trial_expires_at < now:
                    tenant.trial_expires_at = now + timedelta(days=3650)
                changed = True
        except OPERATIONAL_ERRORS:
            logger.debug("P-S 演示租户写入跳过（tenants 表未迁移）", exc_info=True)

        if changed:
            session.commit()
            logger.info(
                "已写入/更新 P-S 演示企业账号 username=%s tenant_id=%s", username, row.tenant_id
            )
