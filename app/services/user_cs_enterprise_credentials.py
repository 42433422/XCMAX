"""企业内部客服：修茈市场 / 企业版登录账号与可回显的初始密码。"""

from __future__ import annotations

import logging
import os
import secrets
import string
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_MARKET_BASE = (
    (os.environ.get("XCAGI_MARKET_BASE_URL", "https://xiu-ci.com") or "").strip().rstrip("/")
)
_INTERNAL_KEY = (
    os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY", "")
    or os.environ.get("XCAGI_CS_INTAKE_WEBHOOK_SECRET", "xcagi-cs-intake-dev-secret")
).strip()


def _generate_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(max(8, min(length, 24))))


def _fetch_market_account(market_user_id: int) -> dict[str, Any]:
    if not _MARKET_BASE or not _INTERNAL_KEY:
        return {"ok": False, "error": "market_internal_not_configured"}
    url = f"{_MARKET_BASE}/api/internal/cs-intake/enterprise-account"
    try:
        resp = httpx.get(
            url,
            params={"market_user_id": int(market_user_id)},
            headers={"X-Internal-Api-Key": _INTERNAL_KEY},
            timeout=12.0,
        )
        data = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        if resp.status_code >= 400:
            return {
                "ok": False,
                "error": str(data.get("detail") or data.get("message") or resp.text)[:300],
            }
        if isinstance(data, dict) and data.get("ok"):
            return {"ok": True, **{k: v for k, v in data.items() if k != "ok"}}
        return {"ok": False, "error": "unexpected_market_response", "data": data}
    except Exception as exc:
        logger.exception("fetch market enterprise account failed uid=%s", market_user_id)
        return {"ok": False, "error": str(exc)[:300]}


def _issue_market_password(market_user_id: int, password: str) -> dict[str, Any]:
    if not _MARKET_BASE or not _INTERNAL_KEY:
        return {"ok": False, "error": "market_internal_not_configured"}
    url = f"{_MARKET_BASE}/api/internal/cs-intake/issue-enterprise-password"
    try:
        resp = httpx.post(
            url,
            json={"market_user_id": int(market_user_id), "password": password},
            headers={"X-Internal-Api-Key": _INTERNAL_KEY},
            timeout=12.0,
        )
        data = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        if resp.status_code >= 400:
            return {
                "ok": False,
                "error": str(data.get("detail") or data.get("message") or resp.text)[:300],
            }
        if isinstance(data, dict) and data.get("ok"):
            return {"ok": True, **{k: v for k, v in data.items() if k != "ok"}}
        return {"ok": False, "error": "unexpected_market_response", "data": data}
    except Exception as exc:
        logger.exception("issue market password failed uid=%s", market_user_id)
        return {"ok": False, "error": str(exc)[:300]}


def _sync_local_fhd_password(username: str, password: str) -> bool:
    """企业版宿主登录与修茈市场同用户名；同步本地库密码便于运维台代登。"""
    try:
        from app.application.auth_app_service import get_auth_app_service
        from app.db.models.user import User
        from app.db.session import get_db

        un = (username or "").strip()
        if not un:
            return False
        with get_db() as db:
            row = db.query(User).filter(User.username == un).first()
            if not row:
                return False
            result = get_auth_app_service().reset_password(int(row.id), password)
            return bool(result.get("success"))
    except Exception:
        logger.debug("sync local fhd password skipped", exc_info=True)
        return False


def get_enterprise_credentials(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    uid = int(market_user_id)
    doc = load_pipeline(uid, username=username)
    market = _fetch_market_account(uid)
    login_username = str(doc.get("enterprise_login_username") or doc.get("username") or "").strip()
    login_password = str(doc.get("enterprise_login_password") or "").strip()
    issued_at = str(doc.get("enterprise_credentials_issued_at") or "").strip()
    email = ""
    is_enterprise = bool(doc.get("enterprise_auto_provisioned_at"))
    if market.get("ok"):
        login_username = str(market.get("username") or login_username).strip()
        email = str(market.get("email") or "").strip()
        is_enterprise = bool(market.get("is_enterprise")) or is_enterprise
        if login_username and login_username != doc.get("enterprise_login_username"):
            doc["enterprise_login_username"] = login_username
            if not str(doc.get("username") or "").strip():
                doc["username"] = login_username
            save_pipeline(doc)
    return {
        "market_user_id": uid,
        "username": login_username,
        "email": email,
        "password": login_password,
        "password_recorded": bool(login_password),
        "issued_at": issued_at,
        "is_enterprise": is_enterprise,
        "market_fetch_error": None if market.get("ok") else market.get("error"),
        "login_hint": "用于修茈市场 (xiu-ci.com) 与企业版 XCAGI 宿主登录",
    }


def issue_enterprise_credentials(
    market_user_id: int,
    *,
    username: str = "",
    password: str | None = None,
) -> dict[str, Any]:
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    uid = int(market_user_id)
    plain = (password or "").strip() or _generate_password()
    issued = _issue_market_password(uid, plain)
    if not issued.get("ok"):
        return {"ok": False, "error": issued.get("error") or "issue_failed"}

    login_username = str(issued.get("username") or "").strip()
    email = str(issued.get("email") or "").strip()
    doc = load_pipeline(uid, username=username or login_username)
    if login_username:
        doc["enterprise_login_username"] = login_username
        doc["username"] = login_username
    doc["enterprise_login_password"] = plain
    doc["enterprise_credentials_issued_at"] = datetime.now(timezone.utc).isoformat()
    if not doc.get("enterprise_auto_provisioned_at"):
        doc["enterprise_auto_provisioned_at"] = doc["enterprise_credentials_issued_at"]
    save_pipeline(doc)
    if login_username:
        _sync_local_fhd_password(login_username, plain)
    return {
        "ok": True,
        "market_user_id": uid,
        "username": login_username,
        "email": email,
        "password": plain,
        "password_recorded": True,
        "issued_at": doc["enterprise_credentials_issued_at"],
        "is_enterprise": True,
        "local_password_synced": bool(login_username),
    }
