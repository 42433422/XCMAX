"""移动端 API 扩展 — 中继相关纯计算辅助函数。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.security.mobile_jwt import issue_mobile_tokens


def _mobile_user_identity(user: Any) -> tuple[int, str]:
    uid = int(getattr(user, "id", 0) or 0)
    username = str(
        getattr(user, "username", "")
        or getattr(user, "display_name", "")
        or getattr(user, "email", "")
        or ""
    ).strip()
    return uid, username


def _mobile_user_public_dict(user: Any) -> dict[str, Any]:
    return {
        "id": int(getattr(user, "id", 0) or 0),
        "username": str(getattr(user, "username", "") or ""),
        "display_name": str(getattr(user, "display_name", "") or ""),
        "email": str(getattr(user, "email", "") or ""),
        "role": str(getattr(user, "role", "") or ""),
        "is_active": bool(getattr(user, "is_active", True)),
        "account_id": str(getattr(user, "account_id", "") or ""),
        "tenant_id": str(getattr(user, "tenant_id", "") or ""),
    }


def _relay_admin_fallback_user() -> dict[str, Any]:
    return {
        "id": 1,
        "username": "admin",
        "display_name": "管理员账号",
        "email": "",
        "role": "admin",
        "is_active": True,
    }


def _relay_mobile_auth_payload(
    user_public: dict[str, Any],
    desktop: dict[str, Any] | None = None,
) -> dict[str, Any]:
    uid = int(user_public.get("id") or 0)
    username = str(user_public.get("username") or user_public.get("display_name") or "mobile")
    role = str(user_public.get("role") or "")
    account_kind = "admin" if role in {"admin", "super_admin", "owner"} else "enterprise"
    session_id = f"mobile-relay-{uuid.uuid4().hex}"
    relay = desktop or {}
    return {
        "user": user_public,
        "session_id": session_id,
        "session_token": str(relay.get("session_token") or user_public.get("session_token") or session_id).strip(),
        "account_id": str(relay.get("account_id") or user_public.get("account_id") or uid).strip(),
        "tenant_id": str(relay.get("tenant_id") or user_public.get("tenant_id") or "").strip(),
        "relay_base_url": str(relay.get("relay_base_url") or user_public.get("relay_base_url") or "").strip(),
        "local_base_url": str(relay.get("local_base_url") or user_public.get("local_base_url") or "").strip(),
        "paired_at": str(relay.get("paired_at") or user_public.get("paired_at") or "").strip(),
        "account_kind": account_kind,
        **issue_mobile_tokens(
            user_id=uid,
            session_id=session_id,
            account_kind=account_kind,
            username=username,
        ),
        "expires_in": 24 * 3600,
    }
