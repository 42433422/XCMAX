"""客户定制 Mod 的接口隔离。

客户定制蓝图（例如 ``/api/mod/sz-qsm-pro/*``）即使被打进某个宿主机，
也必须要求当前账号持有签名安装与市场授权，否则一律拒绝。
"""

from __future__ import annotations

import re

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.mod_sdk.client_private_mods import is_customer_private_mod
from app.utils.operational_errors import RECOVERABLE_ERRORS

_MOD_PATH = re.compile(r"^/api/mods?/(?P<mod_id>[^/]+)")


class CustomerModScopeMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        match = _MOD_PATH.match(scope.get("path") or "")
        mod_id = match.group("mod_id") if match else ""
        if not is_customer_private_mod(mod_id):
            await self.app(scope, receive, send)
            return

        from app.mod_sdk.runtime_frontend import authorized_install

        try:
            authorized_install(Request(scope, receive), mod_id)
        except HTTPException as exc:
            response = JSONResponse(
                {"success": False, "message": str(exc.detail)},
                status_code=exc.status_code,
            )
        except RECOVERABLE_ERRORS:
            response = JSONResponse(
                {"success": False, "message": "客户定制扩展不可用"},
                status_code=404,
            )
        else:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)
