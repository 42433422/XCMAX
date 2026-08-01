"""生产员工私有交付所需的会话身份与 Mod 权益投影。"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.enterprise import mod_entitlements as entitlements

logger = logging.getLogger(__name__)


def load_entitled_client_mod_ids_for_session(session_id: str) -> set[str]:
    """读取会话绑定的客户 Mod 权益，不依赖 enterprise SKU 过滤开关。"""
    return set(load_session_private_delivery_binding(session_id).get("mod_ids") or set())


def load_session_private_delivery_binding(session_id: str) -> dict[str, Any]:
    """以 sessions 行返回定制线身份与权益，禁止回退为全量客户目录。"""
    sid = str(session_id or "").strip()
    empty: dict[str, Any] = {
        "mod_ids": set(),
        "market_user_id": None,
        "username": "",
        "company_brand": "",
    }
    if not sid:
        return empty

    mod_ids: set[str] = set()
    if entitlements.enterprise_mod_filter_active():
        cached = entitlements.get_cached_entitled_client_mod_ids()
        if cached:
            mod_ids = set(cached)

    market_user_id: int | None = None
    username = ""
    company_brand = ""
    try:
        from app.db.models.user import Session as UserSession

        with entitlements._session_row_db_context() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            if row is None:
                return {
                    "mod_ids": mod_ids,
                    "market_user_id": entitlements._cached_market_user_id,
                    "username": entitlements._cached_market_username or "",
                    "company_brand": "",
                }
            if not mod_ids:
                raw = getattr(row, "entitled_mod_ids_json", None) or "[]"
                mod_ids = {str(value).strip() for value in json.loads(raw) if str(value).strip()}
            raw_market_user_id = getattr(row, "market_user_id", None)
            if raw_market_user_id is not None and str(raw_market_user_id).strip():
                try:
                    market_user_id = int(raw_market_user_id)
                except (TypeError, ValueError):
                    market_user_id = None
            company_brand = str(getattr(row, "company_brand", None) or "").strip()
            username = str(getattr(row, "impersonating_username", None) or "").strip()
            if not username:
                username = company_brand
    except Exception:
        logger.exception("load_session_private_delivery_binding failed")
        return {
            "mod_ids": mod_ids,
            "market_user_id": entitlements._cached_market_user_id,
            "username": entitlements._cached_market_username or "",
            "company_brand": "",
        }

    if market_user_id is None:
        market_user_id = entitlements._cached_market_user_id
    if not username:
        username = (
            entitlements._cached_market_username
            or entitlements._session_username_for_entitlements(sid)
        )
    return {
        "mod_ids": mod_ids,
        "market_user_id": market_user_id,
        "username": username,
        "company_brand": company_brand,
    }


__all__ = ["load_entitled_client_mod_ids_for_session", "load_session_private_delivery_binding"]
