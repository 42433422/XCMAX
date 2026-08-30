"""Market token, tenant, and entitlement finalization for enterprise login."""

from __future__ import annotations

import logging
from typing import Any, cast

from app.application.session_account_meta import AccountKind
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _login_flow_module():
    # Lazy facade lookup keeps established patch points on enterprise_login_flow.
    from app.application import enterprise_login_flow

    return enterprise_login_flow


async def finalize_enterprise_login(
    *,
    result: dict[str, Any],
    session_id: str | None,
    market_result: dict[str, Any] | None,
    account_kind: AccountKind,
    username: str,
    sku: str,
    skip_market_sync: bool = False,
) -> dict[str, Any]:
    """Bind market tokens, account metadata, MOD entitlements, and tenant state."""
    from app.fastapi_routes.market_account import (
        fetch_market_membership_tier,
        save_session_market_token,
    )

    if not session_id:
        return result
    flow = _login_flow_module()
    market_token = ""
    local_demo_market = False
    try:
        if skip_market_sync:
            market_result = market_result or {"success": False}
        elif market_result is None and sku != "enterprise":
            pass
        elif market_result is None:
            market_result = {"success": False}

        market_token = str((market_result or {}).get("token") or "").strip()
        market_refresh = str((market_result or {}).get("refresh_token") or "").strip()
        from app.application.surface_audit_demo_account import (
            is_local_demo_market_token,
        )

        local_demo_market = bool(market_token and is_local_demo_market_token(market_token))
        if market_result and market_result.get("success") and market_token:
            save_session_market_token(str(session_id), market_token, market_refresh or None)
            result["market_access_token"] = market_token
            if market_refresh:
                result["market_refresh_token"] = market_refresh

        if market_result and market_result.get("success"):
            user_blob = flow.extract_market_user_blob(market_result)
            market_user_id: int | None = None
            if user_blob.get("id") is not None:
                market_user_id = int(user_blob["id"])
            company_brand = flow.company_brand_from_user_blob(user_blob)
            tenant_id: int | None = None
            tenant_name = company_brand
            user_id = (result.get("user") or {}).get("id")
            if user_id is not None:
                tenant_info = flow.bind_tenant_for_login(
                    user_id=int(user_id),
                    company_brand=company_brand,
                    username=username,
                )
                if tenant_info.get("tenant_id") is not None:
                    tenant_id = int(tenant_info["tenant_id"])
                    result["tenant_id"] = tenant_id
                if tenant_info.get("tenant_name"):
                    tenant_name = str(tenant_info["tenant_name"])
                    result["tenant_name"] = tenant_name
                active_plan_id = str(market_result.get("active_plan_id") or "").strip()
                if active_plan_id:
                    from app.application.tenant_subscription_app_service import (
                        apply_paid_plan_for_user,
                    )

                    if apply_paid_plan_for_user(user_id=int(user_id), plan_id=active_plan_id):
                        result["account_license_plan_id"] = active_plan_id
                        result["account_tier"] = str(market_result.get("account_tier") or "normal")
            market_is_admin = bool(market_result.get("is_market_admin"))
            market_is_enterprise = bool(market_result.get("is_enterprise"))
            account_kind = flow._derive_and_heal_account_kind(
                user_id=user_id,
                market_is_admin=market_is_admin,
                market_is_enterprise=market_is_enterprise,
                fallback=account_kind,
            )
            flow.persist_session_account_meta(
                str(session_id),
                account_kind=account_kind,
                company_brand=company_brand,
                market_user_id=market_user_id,
                market_is_admin=market_is_admin,
                market_is_enterprise=market_is_enterprise,
                tenant_id=tenant_id,
            )
            result["account_kind"] = account_kind
            result["company_brand"] = company_brand
            result["market_is_admin"] = market_is_admin
            result["market_is_enterprise"] = market_is_enterprise
            if market_token and not local_demo_market:
                from app.application.session_account_meta import (
                    persist_session_membership_tier,
                )

                membership_tier = await fetch_market_membership_tier(market_token)
                if membership_tier:
                    persist_session_membership_tier(str(session_id), membership_tier)
                    result["market_membership_tier"] = membership_tier
        elif skip_market_sync:
            user_id = (result.get("user") or {}).get("id")
            if user_id is not None:
                tenant_info = flow.bind_tenant_for_login(
                    user_id=int(user_id),
                    company_brand=str(result.get("company_brand") or username),
                    username=username,
                )
                if tenant_info.get("tenant_id") is not None:
                    result["tenant_id"] = tenant_info["tenant_id"]
                if tenant_info.get("tenant_name"):
                    result["tenant_name"] = tenant_info["tenant_name"]
                flow.persist_session_account_meta(
                    str(session_id),
                    account_kind=account_kind,
                    company_brand=str(result.get("company_brand") or ""),
                    tenant_id=(
                        int(tenant_info["tenant_id"]) if tenant_info.get("tenant_id") else None
                    ),
                )
            result["account_kind"] = account_kind

        if (
            sku == "enterprise"
            and market_result
            and market_result.get("success")
            and market_token
            and not local_demo_market
        ):
            from app.enterprise.mod_entitlements import (
                get_cached_entitled_client_mod_ids,
                persist_entitlements_to_session_row,
                refresh_session_entitlements_from_market,
                reload_enterprise_mods_after_login,
            )

            market_user_id = None
            raw_login = market_result.get("raw")
            if isinstance(raw_login, dict):
                raw_user = raw_login.get("user")
                if isinstance(raw_user, dict) and raw_user.get("id") is not None:
                    market_user_id = int(raw_user["id"])
            client_ids = await refresh_session_entitlements_from_market(
                market_token=market_token,
                market_user_id=market_user_id,
                market_username=username,
                session_id=str(session_id),
            )
            persist_entitlements_to_session_row(str(session_id), client_ids)
            await reload_enterprise_mods_after_login()
            cached = get_cached_entitled_client_mod_ids()
            if cached is not None:
                result["entitled_mod_ids"] = sorted(cached)

        if market_result:
            result["market_account"] = {
                "success": bool(market_result.get("success")),
                "market_base_url": market_result.get("market_base_url"),
                "message": market_result.get("message", ""),
                "is_enterprise": bool(market_result.get("is_enterprise")),
                "is_market_admin": bool(market_result.get("is_market_admin")),
            }
    except RECOVERABLE_ERRORS as exc:
        result["market_account"] = {
            "success": False,
            "message": f"市场账号自动同步失败：{exc}",
        }

    if session_id and "entitled_mod_ids" not in result:
        try:
            from app.enterprise.account_mod_binding import (
                augment_entitled_client_mod_ids_for_username,
            )
            from app.enterprise.mod_entitlements import (
                enterprise_mod_filter_active,
                get_cached_entitled_client_mod_ids,
                persist_entitlements_to_session_row,
                reload_enterprise_mods_after_login,
                set_session_entitlements,
            )

            fallback = augment_entitled_client_mod_ids_for_username(username, set())
            if fallback:
                set_session_entitlements(
                    market_user_id=None,
                    market_username=username,
                    entitled_client_mod_ids=fallback,
                )
                persist_entitlements_to_session_row(str(session_id), fallback)
                if enterprise_mod_filter_active():
                    await reload_enterprise_mods_after_login()
                cached = get_cached_entitled_client_mod_ids()
                if cached:
                    result["entitled_mod_ids"] = sorted(cached)
        except RECOVERABLE_ERRORS:
            logger.exception("account_mod_binding fallback on login failed")

    denied = flow._reject_admin_on_desktop(
        session_id=str(session_id) if session_id else None,
        account_kind=str(result.get("account_kind") or account_kind or ""),
    )
    if denied is not None:
        return cast(dict[str, Any], denied)
    if (
        market_result
        and market_result.get("success")
        and market_token
        and not local_demo_market
        and flow._is_desktop_runtime()
    ):
        from app.application.desktop_delivery_receipt import (
            report_desktop_login_delivery_receipt,
        )

        result["delivery_receipt"] = await report_desktop_login_delivery_receipt(market_token)
    return result
