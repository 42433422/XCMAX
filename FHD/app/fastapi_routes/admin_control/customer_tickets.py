"""CustomerTickets control-plane operations with explicit callback dependencies."""

from __future__ import annotations

from typing import Any

from fastapi import Query, Request
from fastapi.responses import JSONResponse

from app.application.admin_control.protocols import AdminGate, ErrorPolicy, MarketProxy


class CustomerTickets:
    def __init__(self, *, errors: ErrorPolicy, proxy: MarketProxy, gate: AdminGate) -> None:
        self._errors = errors
        self._proxy = proxy
        self._gate = gate

    async def _customer_ticket_proxy(
        self,
        request: Request,
        path: str,
        *,
        method: str = "GET",
        json_body: dict[str, Any] | None = None,
    ):
        from app.fastapi_routes.market_account import session_market_token
        from app.infrastructure.auth.dependencies import (
            resolve_session_user,
            session_id_from_request,
        )

        gate = self._gate(request)
        if gate is not None:
            return gate
        try:
            user = resolve_session_user(request)
            sid = session_id_from_request(request)
            token = (
                session_market_token(sid)
                if sid and getattr(user, "id", None) and getattr(user, "is_active", True)
                else ""
            )
        except self._errors.recoverable():
            token = ""
        if not token:
            return JSONResponse(
                {"success": False, "message": "当前会话未绑定可验证的市场身份，请重新登录"},
                status_code=401,
            )
        # Strictly use this session's identity; never fall back to another session or a browser token.
        return await self._proxy(
            request, method, path, json_body=json_body, authorization_override=token
        )

    async def admin_customer_service_tickets(
        self,
        request: Request,
        search: str = Query("", max_length=200),
        submitter_type: str = Query("", max_length=16),
        intent: str = Query("", max_length=64),
        status: str = Query("", max_length=24),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
    ):
        from urllib.parse import urlencode

        query = urlencode(
            {
                "search": search,
                "submitter_type": submitter_type,
                "intent": intent,
                "status": status,
                "offset": offset,
                "limit": limit,
            }
        )
        return await self._customer_ticket_proxy(request, f"/api/customer-service/tickets?{query}")

    async def admin_customer_service_ticket(self, request: Request, ticket_id: int):
        return await self._customer_ticket_proxy(
            request, f"/api/customer-service/tickets/{ticket_id}"
        )

    async def close_admin_customer_service_ticket(
        self, request: Request, ticket_id: int, body: dict[str, Any]
    ):
        return await self._customer_ticket_proxy(
            request,
            f"/api/customer-service/tickets/{ticket_id}/close",
            method="POST",
            json_body=body,
        )

    async def reply_admin_customer_service_ticket(
        self, request: Request, ticket_id: int, body: dict[str, Any]
    ):
        return await self._customer_ticket_proxy(
            request,
            f"/api/customer-service/tickets/{ticket_id}/reply",
            method="POST",
            json_body=body,
        )

    async def admin_update_customer_ticket_expected_completion(
        self, request: Request, ticket_id: int
    ):
        try:
            body = await request.json()
        except self._errors.recoverable():
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"success": False, "message": "请求内容无效"}, status_code=422)
        return await self._customer_ticket_proxy(
            request,
            f"/api/customer-service/tickets/{ticket_id}/expected-completion",
            method="PATCH",
            json_body=body,
        )
