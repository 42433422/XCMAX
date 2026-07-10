"""移动端 API 扩展 — 中继相关纯计算辅助函数。"""

from __future__ import annotations

import uuid
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


def _relay_mobile_auth_payload(
    user_public: dict[str, Any],
    desktop: dict[str, Any] | None = None,
    *,
    account_kind_override: str = "enterprise",
    token_scope: str = "enterprise_relay",
    tenant_id: int | None = None,
    company_brand: str = "",
    paired_by_user_id: int | None = None,
) -> dict[str, Any]:
    uid = int(user_public.get("id") or 0)
    if uid <= 0:
        raise ValueError("relay credential requires an authenticated user")
    username = str(user_public.get("username") or user_public.get("display_name") or "mobile")
    account_kind = account_kind_override.strip().lower()
    if account_kind != "enterprise":
        raise ValueError("relay credentials are enterprise-only")
    # A relay credential is an enterprise-side execution credential even when
    # the bound DB subject is the administrator who opened the settings page.
    # Never echo the administrator role into the phone-side identity payload.
    token_user = dict(user_public)
    if account_kind == "enterprise":
        token_user["role"] = "enterprise"
        token_user["tier"] = "enterprise"
    if tenant_id is None:
        raw_tenant_id = user_public.get("tenant_id")
        tenant_id = int(raw_tenant_id) if raw_tenant_id is not None else 0
    if not company_brand:
        company_brand = str(user_public.get("company_brand") or username).strip()
    if paired_by_user_id is None:
        paired_by_user_id = uid
    session_id = f"mobile-relay-{uuid.uuid4().hex}"
    relay = desktop or {}
    return {
        "user": token_user,
        "session_id": session_id,
        "session_token": str(
            relay.get("session_token") or user_public.get("session_token") or session_id
        ).strip(),
        "account_id": str(relay.get("account_id") or user_public.get("account_id") or uid).strip(),
        "tenant_id": str(relay.get("tenant_id") or user_public.get("tenant_id") or "").strip(),
        "relay_base_url": str(
            relay.get("relay_base_url") or user_public.get("relay_base_url") or ""
        ).strip(),
        "local_base_url": str(
            relay.get("local_base_url") or user_public.get("local_base_url") or ""
        ).strip(),
        "paired_at": str(relay.get("paired_at") or user_public.get("paired_at") or "").strip(),
        "account_kind": account_kind,
        **issue_mobile_tokens(
            user_id=uid,
            session_id=session_id,
            account_kind=account_kind,
            username=username,
            token_scope=token_scope,
            tenant_id=tenant_id,
            company_brand=company_brand,
            paired_by_user_id=paired_by_user_id,
        ),
        "expires_in": 24 * 3600,
        **({"token_scope": token_scope} if token_scope else {}),
        **({"tenant_id": tenant_id} if tenant_id is not None else {}),
        **({"company_brand": company_brand} if company_brand else {}),
        **({"paired_by_user_id": paired_by_user_id} if paired_by_user_id is not None else {}),
    }
