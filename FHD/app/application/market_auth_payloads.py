"""Normalize market authentication payloads without transport dependencies."""

from __future__ import annotations

from typing import Any


def user_blob_from_market_payload(payload: Any) -> dict[str, Any]:
    """Extract a user mapping from supported login and ``/me`` envelopes."""

    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("user"), dict):
        return dict(payload["user"])
    data = payload.get("data")
    if isinstance(data, dict):
        if isinstance(data.get("user"), dict):
            return dict(data["user"])
        if data.get("id") is not None and data.get("username"):
            return dict(data)
    if payload.get("id") is not None and payload.get("username"):
        return dict(payload)
    return {}


def truthy_identity_flag(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return raw != 0
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(raw)


def market_identity_from_payloads(*payloads: Any) -> tuple[bool, bool, dict[str, Any]]:
    """Merge login and ``/me`` payloads into enterprise/admin identity flags."""

    is_enterprise = False
    is_market_admin = False
    user_blob: dict[str, Any] = {}
    for payload in payloads:
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            continue
        blob = user_blob_from_market_payload(payload)
        if not blob:
            continue
        if not user_blob:
            user_blob = blob
        sources: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            sources.append(payload)
            data = payload.get("data")
            if isinstance(data, dict):
                sources.append(data)
        sources.append(blob)
        for source in sources:
            tier = str(source.get("tier") or "").strip().lower()
            account_kind = (
                str(source.get("account_kind") or source.get("accountKind") or "").strip().lower()
            )
            role = str(source.get("role") or "").strip().lower()
            if truthy_identity_flag(source.get("is_enterprise")) or truthy_identity_flag(
                source.get("market_is_enterprise")
            ):
                is_enterprise = True
            if truthy_identity_flag(source.get("desktop_access")):
                is_enterprise = True
            if tier == "enterprise" or account_kind == "enterprise":
                is_enterprise = True
            if truthy_identity_flag(source.get("is_admin")) or truthy_identity_flag(
                source.get("market_is_admin")
            ):
                is_market_admin = True
            if tier == "admin" or account_kind in {"admin", "admin_portal"}:
                is_market_admin = True
            if role in {"admin", "super_admin", "owner"}:
                is_market_admin = True
    return is_enterprise, is_market_admin, user_blob


def market_lifecycle_from_payloads(*payloads: Any) -> dict[str, Any]:
    """Resolve account lifecycle fields from supported response envelopes."""

    result: dict[str, Any] = {
        "account_state": "pending_plan",
        "next_action": "select_plan",
        "desktop_access": False,
        "active_plan_id": "",
        "account_tier": "",
    }
    for payload in payloads:
        sources: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            sources.append(payload)
            data = payload.get("data")
            if isinstance(data, dict):
                sources.append(data)
            user = payload.get("user")
            if isinstance(user, dict):
                sources.append(user)
        for source in sources:
            for source_key, result_key in (
                ("account_state", "account_state"),
                ("next_action", "next_action"),
                ("active_plan_id", "active_plan_id"),
            ):
                value = str(source.get(source_key) or "").strip()
                if value:
                    result[result_key] = value
            account_tier = str(source.get("account_tier") or "").strip().lower()
            if account_tier in {"normal", "pro", "max", "ultra"}:
                result["account_tier"] = account_tier
            if "desktop_access" in source:
                result["desktop_access"] = truthy_identity_flag(source.get("desktop_access"))
    return result


def market_user_id_from_auth_payload(payload: Any) -> int | None:
    """Extract a positive market user id from supported auth envelopes."""

    candidates: list[Any] = []
    blob = user_blob_from_market_payload(payload)
    if blob:
        candidates.extend([blob.get("id"), blob.get("user_id"), blob.get("market_user_id")])
    if isinstance(payload, dict):
        candidates.extend(
            [payload.get("id"), payload.get("user_id"), payload.get("market_user_id")]
        )
        data = payload.get("data")
        if isinstance(data, dict):
            candidates.extend([data.get("id"), data.get("user_id"), data.get("market_user_id")])
            user = data.get("user")
            if isinstance(user, dict):
                candidates.extend([user.get("id"), user.get("user_id"), user.get("market_user_id")])
    for raw in candidates:
        if isinstance(raw, bool) or raw is None:
            continue
        try:
            user_id = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if user_id > 0:
            return user_id
    return None
