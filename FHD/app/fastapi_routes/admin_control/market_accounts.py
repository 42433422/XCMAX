"""MarketAccounts control-plane operations with explicit callback dependencies."""

from __future__ import annotations

from typing import Any

from fastapi import Body, Query, Request
from fastapi.responses import JSONResponse

from app.application.admin_control.protocols import AdminGate, ErrorPolicy, MarketProxy


class MarketAccounts:
    def __init__(self, *, errors: ErrorPolicy, proxy: MarketProxy, gate: AdminGate) -> None:
        self._errors = errors
        self._proxy = proxy
        self._gate = gate

    async def admin_list_market_users(
        self,
        request: Request,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        is_enterprise: bool | None = Query(None),
    ):
        """List market users without dropping pagination or enterprise filters."""
        from urllib.parse import urlencode

        requested = request.query_params
        params: dict[str, str | int] = {}
        if "limit" in requested:
            params["limit"] = limit
        if "offset" in requested:
            params["offset"] = offset
        if "is_enterprise" in requested and is_enterprise is not None:
            params["is_enterprise"] = "true" if is_enterprise else "false"
        query = f"?{urlencode(params)}" if params else ""
        return await self._proxy(request, "GET", f"/api/admin/users{query}")

    async def admin_create_market_user(
        self,
        request: Request,
        payload: dict[str, Any] = Body(default_factory=dict),
    ):
        from app.application.session_account_meta import audit_admin_action
        from app.fastapi_routes.market_account import register_market_user

        gate = self._gate(request)
        if gate is not None:
            return gate
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")
        email = str(payload.get("email") or "").strip()
        verification_code = str(
            payload.get("verification_code") or payload.get("code") or ""
        ).strip()
        if not username or not password:
            return JSONResponse(
                {"success": False, "message": "username、password 必填"}, status_code=422
            )
        if len(password) < 6:
            return JSONResponse(
                {"success": False, "message": "password 至少 6 位"}, status_code=422
            )
        if not email:
            email = f"{username.lower()}@xcagi.local"
        result = await register_market_user(username, password, email, verification_code)
        if not result.get("success"):
            return JSONResponse(
                {
                    "success": False,
                    "message": result.get("message") or "创建账号失败",
                    "data": result.get("raw"),
                },
                status_code=400,
            )
        audit_admin_action(
            request,
            "create_market_user",
            target_user_id=result.get("market_user_id"),
            detail=f"username={username}",
        )
        return {
            "success": True,
            "data": {
                "market_user_id": result.get("market_user_id"),
                "username": username,
                "email": email,
                "market_base_url": result.get("market_base_url"),
                "raw": result.get("raw"),
            },
        }

    async def admin_list_assignable_mods(self, request: Request):
        return await self._proxy(request, "GET", "/api/admin/enterprise/assignable-mods")

    async def admin_list_wallets(self, request: Request):
        """代理远端 ``/api/admin/wallets``，返回所有用户钱包余额。

        远端返回 ``{items: [{id, user_id, balance, updated_at}], total}``。
        """
        limit = request.query_params.get("limit", "500")
        offset = request.query_params.get("offset", "0")
        return await self._proxy(
            request, "GET", f"/api/admin/wallets?limit={limit}&offset={offset}"
        )

    async def admin_list_orders(self, request: Request):
        """经营看板：代理 MODstore ``/api/admin/orders``（订单列表 + 经营聚合）。

        打通「AI 不知道订单」断点：管理端经此接口读取平台订单数据，供 AI 员工感知与处理。
        """
        q = []
        if request.query_params.get("status"):
            q.append(f"status={request.query_params['status']}")
        if request.query_params.get("limit"):
            q.append(f"limit={request.query_params['limit']}")
        if request.query_params.get("offset"):
            q.append(f"offset={request.query_params['offset']}")
        query = "?" + "&".join(q) if q else ""
        return await self._proxy(request, "GET", f"/api/admin/orders{query}")

    async def admin_list_commerce_orders(self, request: Request):
        from urllib.parse import urlencode

        params = {
            key: request.query_params[key]
            for key in ("status", "limit", "offset")
            if request.query_params.get(key)
        }
        query = f"?{urlencode(params)}" if params else ""
        return await self._proxy(request, "GET", f"/api/admin/commerce/orders{query}")

    async def admin_mutate_commerce_order(
        self,
        request: Request,
        order_no: str,
        action: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ):
        from urllib.parse import quote

        from app.application.session_account_meta import audit_admin_action

        normalized = action.strip().lower()
        if normalized not in {"cancel", "reprice", "refund-request"}:
            return JSONResponse({"success": False, "message": "订单操作不支持"}, status_code=404)
        out = await self._proxy(
            request,
            "POST",
            f"/api/admin/commerce/orders/{quote(order_no, safe='')}/{normalized}",
            json_body=payload,
        )
        if not isinstance(out, JSONResponse) or out.status_code < 400:
            audit_admin_action(
                request,
                f"commerce_order_{normalized.replace('-', '_')}",
                detail=f"order={order_no}; reason={str(payload.get('reason') or '')[:240]}",
            )
        return out

    async def admin_list_pending_commerce_refunds(self, request: Request):
        return await self._proxy(request, "GET", "/api/admin/commerce/refunds/pending")

    async def admin_review_commerce_refund(
        self,
        request: Request,
        refund_id: int,
        payload: dict[str, Any] = Body(default_factory=dict),
    ):
        from app.application.session_account_meta import audit_admin_action

        out = await self._proxy(
            request,
            "POST",
            f"/api/admin/commerce/refunds/{refund_id}/review",
            json_body=payload,
        )
        if not isinstance(out, JSONResponse) or out.status_code < 400:
            audit_admin_action(
                request,
                "commerce_refund_review",
                detail=f"refund={refund_id}; action={str(payload.get('action') or '')}",
            )
        return out

    async def admin_list_standard_customer_deliveries(self, request: Request):
        """读取购买账户 SSOT 聚合出的标准桌面交付证据。"""

        return await self._proxy(
            request,
            "GET",
            "/api/admin/customer-deliveries/standard?limit=500",
        )

    async def admin_list_entitlement_fast_lane_plans(self, request: Request):
        """List every active account-license and membership plan from MODstore SSOT."""

        return await self._proxy(
            request,
            "GET",
            "/api/admin/entitlement-fast-lane/plans",
        )

    async def admin_get_entitlement_fast_lane_account(
        self,
        request: Request,
        account: str,
    ):
        from urllib.parse import quote

        return await self._proxy(
            request,
            "GET",
            f"/api/admin/entitlement-fast-lane/accounts/{quote(account, safe='')}",
        )

    async def admin_mutate_entitlement_fast_lane(
        self,
        request: Request,
        payload: dict[str, Any] = Body(default_factory=dict),
    ):
        """Proxy one audited, idempotent plan mutation without creating commerce data."""

        return await self._proxy(
            request,
            "POST",
            "/api/admin/entitlement-fast-lane/actions",
            json_body=payload,
        )

    async def admin_list_update_install_receipts(self, request: Request):
        """读取客户电脑完成安装或回滚后上报的真实回执。"""
        from urllib.parse import urlencode

        params = {
            key: request.query_params[key]
            for key in ("target_build_sha", "limit")
            if request.query_params.get(key)
        }
        query = f"?{urlencode(params)}" if params else ""
        return await self._proxy(
            request,
            "GET",
            "/api/update-installations/receipts" + query,
        )

    async def admin_credit_user_wallet(
        self,
        request: Request,
        user_id: int,
        payload: dict[str, Any] = Body(default_factory=dict),
    ):
        from app.application.session_account_meta import audit_admin_action

        try:
            amount = float(payload.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            return JSONResponse(
                {"success": False, "message": "加款金额必须大于 0"}, status_code=422
            )
        description = str(payload.get("description") or "").strip() or "后台加款"
        out = await self._proxy(
            request,
            "POST",
            f"/api/admin/users/{user_id}/wallet/credit",
            json_body={"amount": amount, "description": description},
        )
        audit_admin_action(
            request, "credit_user_wallet", target_user_id=user_id, detail=f"amount={amount}"
        )
        return out

    async def admin_list_user_mods(self, request: Request, user_id: int):
        return await self._proxy(request, "GET", f"/api/admin/users/{user_id}/mods")

    async def admin_bind_user_mod(self, request: Request, user_id: int, mod_id: str):
        from app.application.session_account_meta import audit_admin_action

        out = await self._proxy(request, "POST", f"/api/admin/users/{user_id}/mods/{mod_id}")
        audit_admin_action(request, "bind_user_mod", target_user_id=user_id, mod_id=mod_id)
        return out

    async def admin_unbind_user_mod(self, request: Request, user_id: int, mod_id: str):
        from app.application.session_account_meta import audit_admin_action

        out = await self._proxy(request, "DELETE", f"/api/admin/users/{user_id}/mods/{mod_id}")
        audit_admin_action(request, "unbind_user_mod", target_user_id=user_id, mod_id=mod_id)
        return out

    async def admin_set_user_admin(
        self, request: Request, user_id: int, is_admin: bool = Query(...)
    ):
        return await self._proxy(
            request,
            "PUT",
            f"/api/admin/users/{user_id}/admin?is_admin={('true' if is_admin else 'false')}",
        )

    async def admin_set_user_enterprise(
        self, request: Request, user_id: int, is_enterprise: bool = Query(...)
    ):
        return await self._proxy(
            request,
            "PUT",
            f"/api/admin/users/{user_id}/enterprise?is_enterprise={('true' if is_enterprise else 'false')}",
        )

    async def admin_list_trial_customer_deliveries(self, request: Request):
        """读取 ¥99 体验账户（saas-trial-30）SSOT 聚合出的体验交付证据。"""

        return await self._proxy(
            request,
            "GET",
            "/api/admin/customer-deliveries/trial?limit=500",
        )
