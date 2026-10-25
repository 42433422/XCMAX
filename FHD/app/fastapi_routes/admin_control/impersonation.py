"""Admin impersonation lifecycle and enterprise bridge activation."""

from __future__ import annotations

from typing import Any

from fastapi import Body, Request
from fastapi.responses import JSONResponse

from app.application.admin_control.protocols import AdminGate, ErrorPolicy, RefreshEntitlements


class Impersonation:
    def __init__(
        self, *, errors: ErrorPolicy, gate: AdminGate, refresh_entitlements: RefreshEntitlements
    ) -> None:
        self._errors = errors
        self._refresh_entitlements = refresh_entitlements
        self._gate = gate

    async def admin_start_impersonate(
        self,
        request: Request,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        from app.application.impersonation_bridge import create_impersonation_bridge_token
        from app.application.session_account_meta import (
            audit_admin_action,
            load_session_account_meta,
            normalize_account_kind,
            persist_session_account_meta,
        )
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

        gate = self._gate(request)
        if gate is not None:
            return gate
        sid = _session_id_from_request(request)
        target_id = body.get("market_user_id")
        target_name = str(body.get("username") or "").strip()
        target_company = str(body.get("company") or body.get("company_brand") or "").strip()
        if target_id is None:
            return JSONResponse(
                {"success": False, "message": "market_user_id 必填"}, status_code=400
            )
        try:
            target_id = int(target_id)
        except (TypeError, ValueError):
            return JSONResponse(
                {"success": False, "message": "market_user_id 无效"}, status_code=400
            )
        meta = load_session_account_meta(sid) or {}
        persist_session_account_meta(
            sid,
            account_kind=normalize_account_kind(meta.get("account_kind"), default="admin"),
            company_brand=target_company or str(meta.get("company_brand") or ""),
            market_user_id=meta.get("market_user_id"),
            market_is_admin=True,
            market_is_enterprise=bool(meta.get("market_is_enterprise")),
            impersonating_market_user_id=target_id,
            impersonating_username=target_name,
        )
        await self._refresh_entitlements(sid, meta.get("market_user_id"), username=target_name)
        audit_admin_action(
            request, "impersonate_start", target_user_id=target_id, detail=target_name
        )
        return {
            "success": True,
            "impersonating_market_user_id": target_id,
            "impersonating_username": target_name,
            "bridge_token": create_impersonation_bridge_token(sid),
        }

    async def admin_activate_enterprise_impersonation(
        self,
        request: Request,
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        from app.application.impersonation_bridge import (
            consume_impersonation_bridge_token,
            mirror_admin_impersonation_to_enterprise_session,
        )
        from app.config import Config

        token = str(body.get("bridge_token") or body.get("token") or "").strip()
        if not token:
            return JSONResponse({"success": False, "message": "bridge_token 必填"}, status_code=400)
        admin_sid = consume_impersonation_bridge_token(token)
        if not admin_sid:
            return JSONResponse(
                {"success": False, "message": "bridge_token 无效或已过期"}, status_code=400
            )
        enterprise_sid = str(
            body.get("enterprise_session_id")
            or request.cookies.get(getattr(Config, "SESSION_COOKIE_NAME", "session_id"))
            or ""
        ).strip()
        try:
            sid = mirror_admin_impersonation_to_enterprise_session(
                admin_sid, enterprise_sid or None
            )
        except ValueError as exc:
            return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
        return {"success": True, "session_id": sid}

    async def admin_end_impersonate(self, request: Request):
        from app.application.session_account_meta import (
            audit_admin_action,
            clear_impersonation,
            load_session_account_meta,
        )
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

        gate = self._gate(request)
        if gate is not None:
            return gate
        sid = _session_id_from_request(request)
        meta = load_session_account_meta(sid) or {}
        clear_impersonation(sid)
        await self._refresh_entitlements(sid, meta.get("market_user_id"))
        audit_admin_action(request, "impersonate_end")
        return {"success": True}
