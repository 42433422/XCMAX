"""内部客服：企业版登录账号/临时密码（存 pipeline 档案）。"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from typing import Any

from app.utils.operational_errors import OPERATIONAL_ERRORS

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _base_payload(doc: dict[str, Any], *, username: str = "") -> dict[str, Any]:
    login_user = str(
        doc.get("enterprise_login_username") or doc.get("username") or username or ""
    ).strip()
    return {
        "username": login_user,
        "password": str(doc.get("enterprise_login_password") or ""),
        "issued_at": str(doc.get("enterprise_credentials_issued_at") or ""),
        "email": str(doc.get("enterprise_login_email") or ""),
        "password_recorded": bool(doc.get("enterprise_login_password")),
        "is_enterprise": bool(doc.get("enterprise_auto_provisioned_at")),
        "market_fetch_error": "",
    }


def get_enterprise_credentials(market_user_id: int, *, username: str = "") -> dict[str, Any]:
    from app.services.user_cs_pipeline import load_pipeline

    doc = load_pipeline(int(market_user_id), username=username)
    payload = _base_payload(doc, username=username)
    base = (
        (__import__("os").environ.get("XCAGI_MARKET_BASE_URL") or "")  # optional market sync
        .strip()
        .rstrip("/")
    )
    if not base:
        return payload
    try:
        import httpx

        resp = httpx.get(
            f"{base}/api/enterprise/users/{int(market_user_id)}",
            timeout=8.0,
            trust_env=False,
        )
        if resp.status_code >= 400:
            payload["market_fetch_error"] = f"HTTP {resp.status_code}"
            return payload
        blob = resp.json()
        if isinstance(blob, dict):
            user = blob.get("data") if isinstance(blob.get("data"), dict) else blob
            if isinstance(user, dict):
                payload["email"] = str(user.get("email") or payload["email"])
                payload["is_enterprise"] = bool(user.get("is_enterprise", payload["is_enterprise"]))
                if user.get("username"):
                    payload["username"] = str(user["username"])
    except OPERATIONAL_ERRORS as exc:
        logger.debug("market enterprise user fetch failed", exc_info=True)
        payload["market_fetch_error"] = str(exc)[:200]
    return payload


def issue_enterprise_credentials(
    market_user_id: int,
    *,
    username: str = "",
    password: str | None = None,
) -> dict[str, Any]:
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    uid = int(market_user_id)
    doc = load_pipeline(uid, username=username)
    pwd = (password or "").strip() or secrets.token_urlsafe(10)
    login_user = str(doc.get("username") or username or f"user{uid}").strip()
    now = _now_iso()
    doc["enterprise_login_username"] = login_user
    doc["enterprise_login_password"] = pwd
    doc["enterprise_credentials_issued_at"] = now
    doc["enterprise_auto_provisioned_at"] = doc.get("enterprise_auto_provisioned_at") or now
    save_pipeline(doc)
    out = _base_payload(doc, username=username)
    out["success"] = True
    out["password"] = pwd
    return out
