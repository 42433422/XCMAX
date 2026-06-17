"""Admin (:5011) → Enterprise (:5001) 代管会话桥接（一次性 token）。"""

from __future__ import annotations

import logging
import secrets
import time
import uuid
from datetime import timedelta
from typing import Any

from app.db.models.user import Session as UserSession
from app.db.session import get_host_db
from app.infrastructure.session.session_manager import SessionManager
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)

_BRIDGE_TTL_SEC = 120
_BRIDGE: dict[str, dict[str, Any]] = {}


def _purge_expired_bridge_tokens() -> None:
    now = time.time()
    expired = [
        k for k, v in _BRIDGE.items() if now - float(v.get("created_at") or 0) > _BRIDGE_TTL_SEC
    ]
    for key in expired:
        _BRIDGE.pop(key, None)


def create_impersonation_bridge_token(admin_session_id: str) -> str:
    token = secrets.token_urlsafe(32)
    _purge_expired_bridge_tokens()
    _BRIDGE[token] = {
        "admin_sid": (admin_session_id or "").strip(),
        "created_at": time.time(),
    }
    return token


def consume_impersonation_bridge_token(token: str) -> str | None:
    """校验并消费 bridge token，返回 admin session_id。"""
    _purge_expired_bridge_tokens()
    key = (token or "").strip()
    entry = _BRIDGE.pop(key, None)
    if not entry:
        return None
    if time.time() - float(entry.get("created_at") or 0) > _BRIDGE_TTL_SEC:
        return None
    admin_sid = str(entry.get("admin_sid") or "").strip()
    return admin_sid or None


def _copy_session_row_fields(source: UserSession, target: UserSession) -> None:
    target.user_id = source.user_id
    target.market_access_token = source.market_access_token
    target.market_refresh_token = source.market_refresh_token
    target.market_user_id = source.market_user_id
    target.entitled_mod_ids_json = source.entitled_mod_ids_json
    target.account_kind = source.account_kind
    target.company_brand = source.company_brand
    target.market_is_admin = bool(source.market_is_admin)
    target.market_is_enterprise = bool(source.market_is_enterprise)
    target.impersonating_market_user_id = source.impersonating_market_user_id
    target.impersonating_username = source.impersonating_username
    if hasattr(target, "tenant_id"):
        target.tenant_id = getattr(source, "tenant_id", None)


def mirror_admin_impersonation_to_enterprise_session(
    admin_session_id: str,
    enterprise_session_id: str | None = None,
) -> str:
    """将 admin 会话的代管态与市场 token 复制到 enterprise 会话，返回 enterprise session_id。"""
    admin_sid = (admin_session_id or "").strip()
    if not admin_sid:
        raise ValueError("admin session 无效")

    ent_sid_in = (enterprise_session_id or "").strip()
    now = utc_now_naive()
    expire = now + timedelta(hours=SessionManager.SESSION_EXPIRE_HOURS)

    with get_host_db() as db:
        admin_row = db.query(UserSession).filter(UserSession.session_id == admin_sid).first()
        if admin_row is None:
            raise ValueError("admin session 不存在")
        if admin_row.impersonating_market_user_id is None:
            raise ValueError("admin session 未处于代管态")

        ent_row = None
        if ent_sid_in:
            ent_row = db.query(UserSession).filter(UserSession.session_id == ent_sid_in).first()

        if ent_row is None:
            ent_sid = str(uuid.uuid4())
            ent_row = UserSession(
                session_id=ent_sid,
                user_id=admin_row.user_id,
                created_at=now,
                expires_at=expire,
            )
            db.add(ent_row)
        else:
            ent_sid = ent_row.session_id
            ent_row.expires_at = expire

        _copy_session_row_fields(admin_row, ent_row)
        db.commit()
        return ent_sid
